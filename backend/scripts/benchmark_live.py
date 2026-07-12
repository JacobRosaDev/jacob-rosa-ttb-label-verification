"""Benchmark the deployed single-label verification endpoint.

Percentiles use the nearest-rank method: sort successful request latencies,
then select ceil(percentile * sample_size) with a 1-based rank.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request


ENDPOINT_PATH = "/verify"
FIVE_SECONDS_MS = 5_000.0
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

FORM_FIELDS = {
    "brand_name": "Ketel One",
    "class_type": "Vodka",
    "producer": "Ketel Distillery",
    "country_of_origin": "Netherlands",
    "abv": "40.0",
    "net_contents": "750 mL",
    "government_warning": (
        "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
        "alcoholic beverages during pregnancy because of the risk of birth defects. "
        "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
        "operate machinery, and may cause health problems."
    ),
}


class RequestFailure(Exception):
    pass


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--runs must be a positive integer") from exc

    if parsed < 1:
        raise argparse.ArgumentTypeError("--runs must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a live benchmark against the deployed TTB single-label verification API. "
            "Example: python backend/scripts/benchmark_live.py "
            "--base-url https://your-app.example.com --image path/to/label.png --runs 20"
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
        "--runs",
        type=positive_int,
        default=20,
        help="Number of measured requests to send after one warm-up request. Default: 20.",
    )
    return parser.parse_args()


def endpoint_url(base_url: str) -> str:
    parsed = parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be a full http or https URL")
    return base_url.rstrip("/") + ENDPOINT_PATH


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


def multipart_body(
    filename: str,
    image_bytes: bytes,
    image_content_type: str,
) -> tuple[bytes, str]:
    boundary = f"benchmark-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in FORM_FIELDS.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    safe_filename = filename.replace('"', "")
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="image"; filename="{safe_filename}"\r\n'
            ).encode("ascii"),
            f"Content-Type: {image_content_type}\r\n\r\n".encode("ascii"),
            image_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )

    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


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


def send_request(url: str, body: bytes, content_type: str) -> None:
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "User-Agent": "ttb-label-verification-benchmark/1.0",
        },
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            response_body = response.read()
            status = response.status
    except error.HTTPError as exc:
        message = response_message(exc.read())
        raise RequestFailure(f"HTTP {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise RequestFailure(f"Request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RequestFailure("Request timed out.") from exc

    if status < 200 or status >= 300:
        raise RequestFailure(f"HTTP {status}: {response_message(response_body)}")


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
    failed_count: int,
) -> None:
    sample_size = len(latencies_ms)
    p50_ms = percentile_nearest_rank(latencies_ms, 0.50) if latencies_ms else None
    p95_ms = percentile_nearest_rank(latencies_ms, 0.95) if latencies_ms else None
    measured_at = datetime.now(timezone.utc).isoformat()

    print("Live API benchmark")
    print(f"UTC measurement date/time: {measured_at}")
    print(f"Tested endpoint: {endpoint}")
    print(f"Requested measured runs: {requested_runs}")
    print(f"Successful sample size: {sample_size}")
    print(f"Failed request count: {failed_count}")
    print("Percentile method: nearest-rank over successful measured requests.")

    if p50_ms is None or p95_ms is None:
        print("p50 latency: unavailable")
        print("p95 latency: unavailable")
        print("p50 under 5 seconds: no")
        print("p95 under 5 seconds: no")
        return

    print(f"p50 latency: {p50_ms:.1f} ms")
    print(f"p95 latency: {p95_ms:.1f} ms")
    print(f"p50 under 5 seconds: {'yes' if p50_ms < FIVE_SECONDS_MS else 'no'}")
    print(f"p95 under 5 seconds: {'yes' if p95_ms < FIVE_SECONDS_MS else 'no'}")


def main() -> int:
    args = parse_args()

    try:
        endpoint = endpoint_url(args.base_url)
        filename, image_bytes, image_content_type = read_image(args.image)
        body, content_type = multipart_body(filename, image_bytes, image_content_type)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Warm-up request: {endpoint}")
    try:
        send_request(endpoint, body, content_type)
    except RequestFailure as exc:
        print(f"Error: warm-up request failed. {exc}", file=sys.stderr)
        return 1

    latencies_ms: list[float] = []
    failures: list[str] = []

    for run_number in range(1, args.runs + 1):
        start = time.perf_counter()
        try:
            send_request(endpoint, body, content_type)
        except RequestFailure as exc:
            failures.append(f"run {run_number}: {exc}")
            continue
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000

        latencies_ms.append(elapsed_ms)

    failed_count = len(failures)
    print_report(
        endpoint=endpoint,
        requested_runs=args.runs,
        latencies_ms=latencies_ms,
        failed_count=failed_count,
    )

    for failure in failures:
        print(f"Error: {failure}", file=sys.stderr)

    if failed_count > 0:
        return 1
    if len(latencies_ms) != args.runs:
        print("Error: requested successful sample size was not collected.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
