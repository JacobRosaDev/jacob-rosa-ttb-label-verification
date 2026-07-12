import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_benchmark_module():
    spec = importlib.util.spec_from_file_location(
        "benchmark_live",
        SCRIPT_DIR / "benchmark_live.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_live"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def benchmark():
    return load_benchmark_module()


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
        "overall_verdict": "APPROVED",
        "field_results": [
            {
                "field": "brand_name",
                "match_type": "fuzzy",
                "expected": "Ketel One",
                "found": "Ketel One",
                "status": "PASS",
                "reason": "match",
            }
        ],
        "timestamp": "2026-07-12T00:00:00+00:00",
        "latency_ms": 12.5,
    }


def test_read_metadata_requires_exact_submitted_label_fields(tmp_path, benchmark, metadata):
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(__import__("json").dumps(metadata), encoding="utf-8")

    assert benchmark.read_metadata(valid_path) == metadata

    missing = metadata.copy()
    missing.pop("producer")
    missing_path = tmp_path / "missing.json"
    missing_path.write_text(__import__("json").dumps(missing), encoding="utf-8")

    with pytest.raises(ValueError, match="missing fields: producer"):
        benchmark.read_metadata(missing_path)

    extra = metadata | {"unexpected": "nope"}
    extra_path = tmp_path / "extra.json"
    extra_path.write_text(__import__("json").dumps(extra), encoding="utf-8")

    with pytest.raises(ValueError, match="extra fields: unexpected"):
        benchmark.read_metadata(extra_path)


def test_benchmark_runs_exact_requested_attempts_without_warmup(
    tmp_path,
    monkeypatch,
    capsys,
    benchmark,
    metadata,
):
    image_path, metadata_path = write_sample_files(tmp_path, metadata)
    calls = []

    def fake_post_verify(*args, **kwargs):
        calls.append((args, kwargs))

    times = iter([1.0, 1.1, 2.0, 2.2, 3.0, 3.3])

    monkeypatch.setattr(benchmark, "post_verify", fake_post_verify)
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_live.py",
            "--base-url",
            "https://example.test",
            "--image",
            str(image_path),
            "--metadata-file",
            str(metadata_path),
            "--timeout-seconds",
            "7",
            "--runs",
            "3",
        ],
    )

    assert benchmark.main() == 0
    assert len(calls) == 3
    assert all(call[1]["timeout_seconds"] == 7 for call in calls)

    output = capsys.readouterr().out
    assert "Requested runs: 3" in output
    assert "Successful runs: 3" in output
    assert "First-request latency: 100.0 ms" in output
    assert "Successful requests at or below 5 seconds: 3" in output
    assert "All successful requests met 5-second target: yes" in output
    assert "does not prove a cold start" in output


def test_benchmark_reports_failures_and_timeouts(
    tmp_path,
    monkeypatch,
    capsys,
    benchmark,
    metadata,
):
    image_path, metadata_path = write_sample_files(tmp_path, metadata)
    call_count = 0

    def fake_post_verify(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise benchmark.RequestFailure("Request timed out.", timed_out=True)

    times = iter([1.0, 1.1, 2.0, 2.2, 3.0, 3.3])

    monkeypatch.setattr(benchmark, "post_verify", fake_post_verify)
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_live.py",
            "--base-url",
            "https://example.test",
            "--image",
            str(image_path),
            "--metadata-file",
            str(metadata_path),
            "--runs",
            "3",
        ],
    )

    assert benchmark.main() == 1

    captured = capsys.readouterr()
    assert "Successful runs: 2" in captured.out
    assert "Failed runs: 1" in captured.out
    assert "Timed-out runs: 1" in captured.out
    assert "Error: run 2: Request timed out." in captured.err


def test_send_request_uses_mocked_urlopen_and_validates_json_response(monkeypatch, benchmark):
    request_seen = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return __import__("json").dumps(verification_payload()).encode("utf-8")

    def fake_urlopen(req, timeout):
        request_seen["url"] = req.full_url
        request_seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(benchmark.request, "urlopen", fake_urlopen)

    payload = benchmark.send_request(
        "https://example.test/verify",
        b"body",
        "multipart/form-data; boundary=test",
        method="POST",
        timeout_seconds=4.5,
        user_agent="test-agent",
    )

    assert payload["overall_verdict"] == "APPROVED"
    assert request_seen == {"url": "https://example.test/verify", "timeout": 4.5}


def test_send_request_marks_urlopen_timeouts(monkeypatch, benchmark):
    def fake_urlopen(req, timeout):
        raise benchmark.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(benchmark.request, "urlopen", fake_urlopen)

    with pytest.raises(benchmark.RequestFailure) as exc_info:
        benchmark.send_request(
            "https://example.test/verify",
            b"body",
            "multipart/form-data; boundary=test",
            method="POST",
            timeout_seconds=1,
            user_agent="test-agent",
        )

    assert exc_info.value.timed_out is True


def test_send_request_marks_http_504_as_timed_out(monkeypatch, benchmark):
    def fake_urlopen(req, timeout):
        raise benchmark.error.HTTPError(
            req.full_url,
            504,
            "Gateway Timeout",
            hdrs=None,
            fp=__import__("io").BytesIO(b'{"message": "Label extraction timed out."}'),
        )

    monkeypatch.setattr(benchmark.request, "urlopen", fake_urlopen)

    with pytest.raises(benchmark.RequestFailure) as exc_info:
        benchmark.send_request(
            "https://example.test/verify",
            b"body",
            "multipart/form-data; boundary=test",
            method="POST",
            timeout_seconds=1,
            user_agent="test-agent",
        )

    assert str(exc_info.value) == "HTTP 504: Label extraction timed out."
    assert exc_info.value.timed_out is True


def test_validate_verification_result_rejects_shape_changes(benchmark):
    payload = verification_payload()
    payload["unexpected"] = "field"

    with pytest.raises(benchmark.RequestFailure, match="expected contract"):
        benchmark.validate_verification_result(payload)


def test_percentile_nearest_rank(benchmark):
    assert benchmark.percentile_nearest_rank([300, 100, 200, 400], 0.50) == 200
    assert benchmark.percentile_nearest_rank([300, 100, 200, 400], 0.95) == 400
