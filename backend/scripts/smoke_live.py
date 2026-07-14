"""Smoke-check deployed health, single verification, and batch verification endpoints."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark_live import (
    FIELD_RESULT_KEYS,
    FIVE_SECONDS_MS,
    REQUIRED_METADATA_FIELDS,
    VERIFY_PATH,
    RequestFailure,
    positive_float,
    read_image,
    read_metadata,
    send_request,
    url_for,
    validate_verification_result,
    verify_multipart_body,
    multipart_body,
)


HEALTH_PATH = "/health"
BATCH_PATH = "/verify/batch"
BATCH_RESULT_KEYS = {"items", "summary"}
BATCH_SUMMARY_KEYS = {"passed", "needs_review", "total"}
EXPECTED_VERIFY_FIELDS = REQUIRED_METADATA_FIELDS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run live smoke checks against the deployed TTB verification API. "
            "Example: python scripts/smoke_live.py --base-url https://your-app.example.com "
            "--image path/to/label.png --metadata-file path/to/metadata.json"
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
    return parser.parse_args()


def validate_health(payload: object) -> None:
    if not isinstance(payload, dict):
        raise RequestFailure("Health response was not a JSON object.")
    if payload.get("status") != "ok" or not isinstance(payload.get("ts"), str):
        raise RequestFailure("Health response did not match the expected contract.")


def validate_batch_result(payload: object) -> None:
    if not isinstance(payload, dict):
        raise RequestFailure("Batch response was not a JSON object.")
    if set(payload) != BATCH_RESULT_KEYS:
        raise RequestFailure("Batch response did not match the expected contract.")

    items = payload["items"]
    summary = payload["summary"]
    if not isinstance(items, list):
        raise RequestFailure("Batch items was not a list.")
    if not isinstance(summary, dict) or set(summary) != BATCH_SUMMARY_KEYS:
        raise RequestFailure("Batch summary did not match the expected contract.")
    if not all(isinstance(summary[key], int) and summary[key] >= 0 for key in BATCH_SUMMARY_KEYS):
        raise RequestFailure("Batch summary values were missing or invalid.")
    if summary["total"] != len(items):
        raise RequestFailure("Batch summary total did not match item count.")

    for item in items:
        validate_verification_result(item)
        for field_result in item["field_results"]:
            if set(field_result) != FIELD_RESULT_KEYS:
                raise RequestFailure("Batch field result did not match the expected contract.")


def validate_smoke_verification_result(payload: object) -> None:
    validate_verification_result(payload)

    field_results = payload["field_results"]
    if not field_results:
        raise RequestFailure("Verification field_results must include all seven label fields.")

    fields = [field_result["field"] for field_result in field_results]
    unique_fields = set(fields)
    if len(fields) != len(unique_fields):
        duplicates = sorted({field for field in fields if fields.count(field) > 1})
        raise RequestFailure(
            "Verification field_results contained duplicate fields: "
            + ", ".join(duplicates)
        )

    if unique_fields != EXPECTED_VERIFY_FIELDS:
        missing = sorted(EXPECTED_VERIFY_FIELDS - unique_fields)
        unexpected = sorted(unique_fields - EXPECTED_VERIFY_FIELDS)
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected fields: {', '.join(unexpected)}")
        raise RequestFailure(
            "Verification field_results must contain exactly the seven label fields; "
            + "; ".join(details)
        )

    latency_ms = payload["latency_ms"]
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, (int, float)):
        raise RequestFailure("Verification latency_ms was missing or invalid.")
    if latency_ms >= FIVE_SECONDS_MS:
        raise RequestFailure("Verification latency_ms must be less than 5000 ms.")


def batch_multipart_body(
    metadata: dict[str, object],
    filename: str,
    image_bytes: bytes,
    image_content_type: str,
) -> tuple[bytes, str]:
    if set(metadata) != REQUIRED_METADATA_FIELDS:
        raise ValueError("Metadata must contain exactly the submitted label fields.")
    return multipart_body(
        {"metadata": json.dumps([metadata])},
        [("images", filename, image_bytes, image_content_type)],
        boundary_prefix="smoke",
    )


def run_check(name: str, action) -> bool:
    try:
        action()
    except RequestFailure as exc:
        print(f"FAIL {name}: {exc}")
        return False
    print(f"PASS {name}")
    return True


def main() -> int:
    args = parse_args()

    try:
        health_url = url_for(args.base_url, HEALTH_PATH)
        verify_url = url_for(args.base_url, VERIFY_PATH)
        batch_url = url_for(args.base_url, BATCH_PATH)
        filename, image_bytes, image_content_type = read_image(args.image)
        metadata = read_metadata(args.metadata_file)
        verify_body, verify_content_type = verify_multipart_body(
            metadata,
            filename,
            image_bytes,
            image_content_type,
        )
        batch_body, batch_content_type = batch_multipart_body(
            metadata,
            filename,
            image_bytes,
            image_content_type,
        )
    except ValueError as exc:
        print(f"FAIL setup: {exc}", file=sys.stderr)
        return 2

    def check_health() -> None:
        payload = send_request(
            health_url,
            None,
            None,
            method="GET",
            timeout_seconds=args.timeout_seconds,
            user_agent="ttb-label-verification-smoke/1.0",
        )
        validate_health(payload)

    def check_verify() -> None:
        payload = send_request(
            verify_url,
            verify_body,
            verify_content_type,
            method="POST",
            timeout_seconds=args.timeout_seconds,
            user_agent="ttb-label-verification-smoke/1.0",
        )
        validate_smoke_verification_result(payload)

    def check_batch() -> None:
        payload = send_request(
            batch_url,
            batch_body,
            batch_content_type,
            method="POST",
            timeout_seconds=args.timeout_seconds,
            user_agent="ttb-label-verification-smoke/1.0",
        )
        validate_batch_result(payload)

    checks = [
        run_check("GET /health", check_health),
        run_check("POST /verify", check_verify),
        run_check("POST /verify/batch", check_batch),
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
