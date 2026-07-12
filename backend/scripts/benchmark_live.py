"""Benchmark the deployed single-label verification endpoint.

Percentiles use the nearest-rank method: sort successful request latencies,
then select ceil(percentile * sample_size) with a 1-based rank.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request


VERIFY_PATH = "/verify"
FIVE_SECONDS_MS = 5_000.0
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
REQUIRED_METADATA_FIELDS = {
    "brand_name",
    "class_type",
    "producer",
    "country_of_origin",
    "abv",
    "net_contents",
    "government_warning",
}
VERIFICATION_RESULT_KEYS = {"overall_verdict", "field_results", "timestamp", "latency_ms"}
FIELD_RESULT_KEYS = {"field", "match_type", "expected", "found", "status", "reason"}
ALLOWED_VERDICTS = {"APPROVED", "NEEDS_REVIEW"}
ALLOWED_FIELD_STATUSES = {"PASS", "FAIL"}


class RequestFailure(Exception):
    def __init__(self, message: str, *, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--runs must be a positive integer") from exc

    if parsed < 1:
        raise argparse.ArgumentTypeError("--runs must be a positive integer")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--timeout-seconds must be positive") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("--timeout-seconds must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a live benchmark against the deployed TTB single-label verification API. "
            "Example: python scripts/benchmark_live.py --base-url https://your-app.example.com "
            "--image path/to/label.png --metadata-file path/to/metadata.json --runs 20"
        )
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Deployed API base URL, for example https://your-app.example.com.",
    )
    parser.add_argument(
        "--image",
        required=True,
        type=Path,
        help="Path to a real JPEG, PNG, or WEBP label image.",
    )
    parser.add_argument(
        "--metadata-file",
        required=True,
        type=Path,
        help="Path to a JSON object with exactly the submitted label fields.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=positive_float,
        default=30.0,
        help="Per-request timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--runs",
        type=positive_int,
        default=20,
        help="Number of benchmark attempts to send. Default: 20.",
    )
    return parser.parse_args()


def url_for(base_url: str, path: str) -> str:
    parsed = parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be a full http or https URL")
    return base_url.rstrip("/") + path


def read_image(image_path: Path) -> tuple[str, bytes, str]:
    if not image_path.exists():
        raise ValueError(f"Image file not found: {image_path}")
    if not image_path.is_file():
        raise ValueError(f"Image path is not a file: {image_path}")

    content_type = mimetypes.guess_type(image_path.name)[0]
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Image must be a JPEG, PNG, or WEBP file.")

    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Unable to read image file: {exc}") from exc

    if not image_bytes:
        raise ValueError("Image file is empty.")

    return image_path.name, image_bytes, content_type


def read_metadata(metadata_path: Path) -> dict[str, object]:
    if not metadata_path.exists():
        raise ValueError(f"Metadata file not found: {metadata_path}")
    if not metadata_path.is_file():
        raise ValueError(f"Metadata path is not a file: {metadata_path}")

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read metadata file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Metadata file must contain valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Metadata file must contain one JSON object.")

    fields = set(payload)
    missing = sorted(REQUIRED_METADATA_FIELDS - fields)
    extra = sorted(fields - REQUIRED_METADATA_FIELDS)
    if missing or extra:
        messages = []
        if missing:
            messages.append(f"missing fields: {', '.join(missing)}")
        if extra:
            messages.append(f"extra fields: {', '.join(extra)}")
        raise ValueError("Metadata must contain exactly the submitted label fields; " + "; ".join(messages))

    return payload


def _add_form_field(chunks: list[bytes], boundary: str, name: str, value: object) -> None:
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
            str(value).encode("utf-8"),
            b"\r\n",
        ]
    )


def _add_file_field(
    chunks: list[bytes],
    boundary: str,
    field_name: str,
    filename: str,
    image_bytes: bytes,
    image_content_type: str,
) -> None:
    safe_filename = filename.replace('"', "")
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{safe_filename}"\r\n'
            ).encode("ascii"),
            f"Content-Type: {image_content_type}\r\n\r\n".encode("ascii"),
            image_bytes,
            b"\r\n",
        ]
    )


def multipart_body(
    fields: dict[str, object],
    files: list[tuple[str, str, bytes, str]],
    *,
    boundary_prefix: str,
) -> tuple[bytes, str]:
    boundary = f"{boundary_prefix}-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        _add_form_field(chunks, boundary, name, value)

    for field_name, filename, image_bytes, image_content_type in files:
        _add_file_field(chunks, boundary, field_name, filename, image_bytes, image_content_type)

    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def verify_multipart_body(
    metadata: dict[str, object],
    filename: str,
    image_bytes: bytes,
    image_content_type: str,
) -> tuple[bytes, str]:
    return multipart_body(
        metadata,
        [("image", filename, image_bytes, image_content_type)],
        boundary_prefix="benchmark",
    )


def response_message(body: bytes) -> str:
    if not body:
        return "empty response body"

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = body.decode("utf-8", errors="replace").strip()
        return text[:200] if text else "empty response body"

    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("detail") or payload.get("error")
        if message:
            return str(message)
    return json.dumps(payload)[:200]


def _is_timeout_reason(reason: object) -> bool:
    return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()


def send_request(
    url: str,
    body: bytes | None,
    content_type: str | None,
    *,
    method: str,
    timeout_seconds: float,
    user_agent: str,
) -> dict[str, object]:
    headers = {"User-Agent": user_agent}
    if content_type is not None:
        headers["Content-Type"] = content_type
    if body is not None:
        headers["Content-Length"] = str(len(body))

    req = request.Request(url, data=body, method=method, headers=headers)

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response_body = response.read()
            status = response.status
    except error.HTTPError as exc:
        message = response_message(exc.read())
        raise RequestFailure(f"HTTP {exc.code}: {message}", timed_out=exc.code == 504) from exc
    except error.URLError as exc:
        if _is_timeout_reason(exc.reason):
            raise RequestFailure("Request timed out.", timed_out=True) from exc
        raise RequestFailure(f"Request failed: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RequestFailure("Request timed out.", timed_out=True) from exc

    if status < 200 or status >= 300:
        raise RequestFailure(f"HTTP {status}: {response_message(response_body)}")

    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestFailure("Response body was not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise RequestFailure("Response body was not a JSON object.")
    return payload


def validate_verification_result(payload: object) -> None:
    if not isinstance(payload, dict):
        raise RequestFailure("Verification response was not a JSON object.")
    if set(payload) != VERIFICATION_RESULT_KEYS:
        raise RequestFailure("Verification response did not match the expected contract.")
    if payload["overall_verdict"] not in ALLOWED_VERDICTS:
        raise RequestFailure("Verification response had an unknown overall_verdict.")
    if not isinstance(payload["field_results"], list):
        raise RequestFailure("Verification field_results was not a list.")
    if not isinstance(payload["latency_ms"], (int, float)) or payload["latency_ms"] < 0:
        raise RequestFailure("Verification latency_ms was missing or invalid.")

    for field_result in payload["field_results"]:
        if not isinstance(field_result, dict) or set(field_result) != FIELD_RESULT_KEYS:
            raise RequestFailure("Verification field result did not match the expected contract.")
        if field_result["status"] not in ALLOWED_FIELD_STATUSES:
            raise RequestFailure("Verification field result had an unknown status.")


def post_verify(
    url: str,
    body: bytes,
    content_type: str,
    *,
    timeout_seconds: float,
    user_agent: str,
) -> None:
    payload = send_request(
        url,
        body,
        content_type,
        method="POST",
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
    )
    validate_verification_result(payload)


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("Cannot calculate percentile with no samples.")

    sorted_values = sorted(values)
    rank = math.ceil(percentile * len(sorted_values))
    return sorted_values[rank - 1]


def print_report(
    *,
    endpoint: str,
    requested_runs: int,
    latencies_ms: list[float],
    failed_runs: int,
    timed_out_runs: int,
    first_request_latency_ms: float | None,
) -> None:
    successful_runs = len(latencies_ms)
    p50_ms = percentile_nearest_rank(latencies_ms, 0.50) if latencies_ms else None
    p95_ms = percentile_nearest_rank(latencies_ms, 0.95) if latencies_ms else None
    successful_under_target = sum(1 for value in latencies_ms if value <= FIVE_SECONDS_MS)
    all_successes_under_target = successful_runs > 0 and successful_under_target == successful_runs
    measured_at = datetime.now(timezone.utc).isoformat()

    print("Live API benchmark")
    print(f"UTC measurement date/time: {measured_at}")
    print(f"Tested endpoint: {endpoint}")
    print(f"Requested runs: {requested_runs}")
    print(f"Successful runs: {successful_runs}")
    print(f"Failed runs: {failed_runs}")
    print(f"Timed-out runs: {timed_out_runs}")
    print("First-request latency is a cold-start indicator only; it does not prove a cold start.")
    if first_request_latency_ms is None:
        print("First-request latency: unavailable")
    else:
        print(f"First-request latency: {first_request_latency_ms:.1f} ms")
    print("Percentile method: nearest-rank over successful requests.")

    if p50_ms is None or p95_ms is None:
        print("p50 latency: unavailable")
        print("p95 latency: unavailable")
    else:
        print(f"p50 latency: {p50_ms:.1f} ms")
        print(f"p95 latency: {p95_ms:.1f} ms")

    print(f"Successful requests at or below 5 seconds: {successful_under_target}")
    print(f"All successful requests met 5-second target: {'yes' if all_successes_under_target else 'no'}")


def main() -> int:
    args = parse_args()

    try:
        endpoint = url_for(args.base_url, VERIFY_PATH)
        filename, image_bytes, image_content_type = read_image(args.image)
        metadata = read_metadata(args.metadata_file)
        body, content_type = verify_multipart_body(
            metadata,
            filename,
            image_bytes,
            image_content_type,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    latencies_ms: list[float] = []
    failures: list[str] = []
    timed_out_runs = 0
    first_request_latency_ms: float | None = None

    for run_number in range(1, args.runs + 1):
        start = time.perf_counter()
        succeeded = False
        try:
            post_verify(
                endpoint,
                body,
                content_type,
                timeout_seconds=args.timeout_seconds,
                user_agent="ttb-label-verification-benchmark/1.0",
            )
            succeeded = True
        except RequestFailure as exc:
            failures.append(f"run {run_number}: {exc}")
            if exc.timed_out:
                timed_out_runs += 1
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if run_number == 1:
                first_request_latency_ms = elapsed_ms

        if succeeded:
            latencies_ms.append(elapsed_ms)

    failed_runs = len(failures)
    print_report(
        endpoint=endpoint,
        requested_runs=args.runs,
        latencies_ms=latencies_ms,
        failed_runs=failed_runs,
        timed_out_runs=timed_out_runs,
        first_request_latency_ms=first_request_latency_ms,
    )

    for failure in failures:
        print(f"Error: {failure}", file=sys.stderr)

    return 1 if failed_runs else 0


if __name__ == "__main__":
    raise SystemExit(main())
