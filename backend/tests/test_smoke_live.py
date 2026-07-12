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


def verification_payload():
    return {
        "overall_verdict": "NEEDS_REVIEW",
        "field_results": [
            {
                "field": "brand_name",
                "match_type": "fuzzy",
                "expected": "Ketel One",
                "found": "Different",
                "status": "FAIL",
                "reason": "mismatch",
            }
        ],
        "timestamp": "2026-07-12T00:00:00+00:00",
        "latency_ms": 12.5,
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

    def fake_send_request(url, body, content_type, *, method, timeout_seconds, user_agent):
        requested_urls.append((url, method, timeout_seconds))
        if url.endswith("/health"):
            return {"status": "ok", "ts": "2026-07-12T00:00:00+00:00"}
        if url.endswith("/verify/batch"):
            return batch_payload()
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
