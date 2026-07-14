import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_modules():
    benchmark_spec = importlib.util.spec_from_file_location(
        "benchmark_live",
        SCRIPT_DIR / "benchmark_live.py",
    )
    benchmark = importlib.util.module_from_spec(benchmark_spec)
    sys.modules["benchmark_live"] = benchmark
    benchmark_spec.loader.exec_module(benchmark)

    smoke_spec = importlib.util.spec_from_file_location(
        "smoke_live",
        SCRIPT_DIR / "smoke_live.py",
    )
    smoke = importlib.util.module_from_spec(smoke_spec)
    sys.modules["smoke_live"] = smoke
    smoke_spec.loader.exec_module(smoke)
    return benchmark, smoke


@pytest.fixture
def modules():
    return load_modules()


@pytest.fixture
def metadata():
    return {
        "brand_name": "Ketel One",
        "class_type": "Vodka",
        "producer": "Ketel Distillery",
        "country_of_origin": "Netherlands",
        "abv": 40.0,
        "net_contents": "750 mL",
        "government_warning": "GOVERNMENT WARNING: sample text",
    }


def write_sample_files(tmp_path, metadata):
    image_path = tmp_path / "label.png"
    image_path.write_bytes(b"PNGDATA")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(__import__("json").dumps(metadata), encoding="utf-8")
    return image_path, metadata_path


def _field_result(field):
    return {
        "field": field,
        "match_type": "fuzzy" if field in {"brand_name", "class_type", "producer"} else "exact",
        "expected": "expected",
        "found": "found",
        "status": "PASS",
        "reason": "match",
    }


def verification_payload(*, fields=None, latency_ms=12.5, overall_verdict="NEEDS_REVIEW"):
    if fields is None:
        fields = [
            "brand_name",
            "class_type",
            "producer",
            "country_of_origin",
            "abv",
            "net_contents",
            "government_warning",
        ]
    return {
        "overall_verdict": overall_verdict,
        "field_results": [_field_result(field) for field in fields],
        "timestamp": "2026-07-12T00:00:00+00:00",
        "latency_ms": latency_ms,
    }


def batch_payload():
    return {
        "items": [verification_payload()],
        "summary": {"passed": 0, "needs_review": 1, "total": 1},
    }


def test_smoke_main_prints_pass_for_all_checks(tmp_path, monkeypatch, capsys, modules, metadata):
    _, smoke = modules
    image_path, metadata_path = write_sample_files(tmp_path, metadata)
    requested_urls = []
    verify_body_seen = None

    def fake_send_request(url, body, content_type, *, method, timeout_seconds, user_agent):
        nonlocal verify_body_seen
        requested_urls.append((url, method, timeout_seconds))
        if url.endswith("/health"):
            return {"status": "ok", "ts": "2026-07-12T00:00:00+00:00"}
        if url.endswith("/verify/batch"):
            return batch_payload()
        verify_body_seen = body
        return verification_payload()

    monkeypatch.setattr(smoke, "send_request", fake_send_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_live.py",
            "--base-url",
            "https://example.test",
            "--image",
            str(image_path),
            "--metadata-file",
            str(metadata_path),
            "--timeout-seconds",
            "9",
        ],
    )

    assert smoke.main() == 0
    assert requested_urls == [
        ("https://example.test/health", "GET", 9),
        ("https://example.test/verify", "POST", 9),
        ("https://example.test/verify/batch", "POST", 9),
    ]
    assert b'name="image"; filename="label.png"' in verify_body_seen
    for field, value in metadata.items():
        assert f'name="{field}"'.encode("ascii") in verify_body_seen
        assert str(value).encode("utf-8") in verify_body_seen

    output = capsys.readouterr().out
    assert "PASS GET /health" in output
    assert "PASS POST /verify" in output
    assert "PASS POST /verify/batch" in output


def test_smoke_main_returns_nonzero_when_any_check_fails(
    tmp_path,
    monkeypatch,
    capsys,
    modules,
    metadata,
):
    benchmark, smoke = modules
    image_path, metadata_path = write_sample_files(tmp_path, metadata)

    def fake_send_request(url, body, content_type, *, method, timeout_seconds, user_agent):
        if url.endswith("/verify"):
            raise benchmark.RequestFailure("HTTP 500: broken")
        if url.endswith("/health"):
            return {"status": "ok", "ts": "2026-07-12T00:00:00+00:00"}
        return batch_payload()

    monkeypatch.setattr(smoke, "send_request", fake_send_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_live.py",
            "--base-url",
            "https://example.test",
            "--image",
            str(image_path),
            "--metadata-file",
            str(metadata_path),
        ],
    )

    assert smoke.main() == 1

    output = capsys.readouterr().out
    assert "PASS GET /health" in output
    assert "FAIL POST /verify: HTTP 500: broken" in output
    assert "PASS POST /verify/batch" in output


def test_batch_multipart_body_uses_metadata_array_and_images_field(modules, metadata):
    _, smoke = modules

    body, content_type = smoke.batch_multipart_body(metadata, "label.png", b"PNGDATA", "image/png")

    assert content_type.startswith("multipart/form-data; boundary=smoke-")
    assert b'name="metadata"' in body
    assert b'"brand_name": "Ketel One"' in body
    assert b'name="images"; filename="label.png"' in body


def test_validate_smoke_verification_result_accepts_valid_seven_field_response(modules):
    _, smoke = modules

    smoke.validate_smoke_verification_result(verification_payload())


def test_validate_smoke_verification_result_rejects_empty_field_results(modules):
    benchmark, smoke = modules
    payload = verification_payload(fields=[])

    with pytest.raises(benchmark.RequestFailure, match="all seven label fields"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_smoke_verification_result_rejects_missing_field(modules):
    benchmark, smoke = modules
    payload = verification_payload(fields=[
        "brand_name",
        "class_type",
        "country_of_origin",
        "abv",
        "net_contents",
        "government_warning",
    ])

    with pytest.raises(benchmark.RequestFailure, match="missing fields: producer"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_smoke_verification_result_rejects_duplicate_field(modules):
    benchmark, smoke = modules
    payload = verification_payload(fields=[
        "brand_name",
        "brand_name",
        "class_type",
        "producer",
        "country_of_origin",
        "abv",
        "net_contents",
        "government_warning",
    ])

    with pytest.raises(benchmark.RequestFailure, match="duplicate fields: brand_name"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_smoke_verification_result_rejects_unexpected_field(modules):
    benchmark, smoke = modules
    payload = verification_payload(fields=[
        "brand_name",
        "class_type",
        "producer",
        "country_of_origin",
        "abv",
        "net_contents",
        "unexpected",
    ])

    with pytest.raises(benchmark.RequestFailure, match="unexpected fields: unexpected"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_smoke_verification_result_rejects_latency_equal_to_5000(modules):
    benchmark, smoke = modules
    payload = verification_payload(latency_ms=5000)

    with pytest.raises(benchmark.RequestFailure, match="less than 5000 ms"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_smoke_verification_result_rejects_latency_above_5000(modules):
    benchmark, smoke = modules
    payload = verification_payload(latency_ms=5000.1)

    with pytest.raises(benchmark.RequestFailure, match="less than 5000 ms"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_smoke_verification_result_rejects_invalid_verdict(modules):
    benchmark, smoke = modules
    payload = verification_payload(overall_verdict="BROKEN")

    with pytest.raises(benchmark.RequestFailure, match="unknown overall_verdict"):
        smoke.validate_smoke_verification_result(payload)


def test_validate_health_rejects_contract_change(modules):
    benchmark, smoke = modules

    with pytest.raises(benchmark.RequestFailure, match="Health response"):
        smoke.validate_health({"status": "up", "ts": "2026-07-12T00:00:00+00:00"})


def test_validate_batch_result_rejects_contract_change(modules):
    benchmark, smoke = modules
    payload = batch_payload()
    payload["summary"]["total"] = 2

    with pytest.raises(benchmark.RequestFailure, match="total did not match"):
        smoke.validate_batch_result(payload)
