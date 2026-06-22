import io

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_vision_service
from app.vision_service import MockVisionService, VisionService


@pytest.fixture(autouse=True)
def mock_vision_service_override():
    app.dependency_overrides[get_vision_service] = lambda: MockVisionService(scenario="clear")
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _base_form_data():
    return {
        "brand_name": "Ketel One",
        "class_type": "Vodka",
        "producer": "Ketel Distillery",
        "country_of_origin": "Netherlands",
        "abv": "40.0",
        "net_contents": "750 mL",
        "government_warning": (
            "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink..."
        ),
    }


def test_verify_returns_approved_with_clear_mock(client):
    file_bytes = b"PNGDATA"
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(file_bytes), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_verdict"] == "APPROVED"
    assert isinstance(payload["field_results"], list)
    assert payload["field_results"][0]["field_name"] == "brand_name"
    assert payload["latency_ms"] >= 0


def test_verify_returns_needs_review_for_partial_extraction(client):
    app.dependency_overrides[get_vision_service] = lambda: MockVisionService(scenario="partial")
    file_bytes = b"PNGDATA"
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(file_bytes), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_verdict"] == "NEEDS_REVIEW"
    assert any(fr["status"] == "FAIL" for fr in payload["field_results"])
    assert payload["latency_ms"] >= 0


def test_verify_rejects_missing_image(client):
    response = client.post(
        "/verify",
        data=_base_form_data(),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "Invalid request"
    assert "Image file is required" in payload["message"]


def test_verify_rejects_invalid_file_type(client):
    file_bytes = b"NOTANIMAGE"
    response = client.post(
        "/verify",
        files={"image": ("label.txt", io.BytesIO(file_bytes), "text/plain")},
        data=_base_form_data(),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "Invalid request"
    assert "Unsupported file type" in payload["message"]


def test_verify_rejects_oversized_image(client):
    file_bytes = b"0" * (8 * 1024 * 1024 + 1)
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(file_bytes), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "Invalid request"
    assert "smaller than" in payload["message"]


def test_verify_rejects_invalid_abv(client):
    data = _base_form_data()
    data["abv"] = "invalid"
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(b"PNGDATA"), "image/png")},
        data=data,
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "Invalid request"
    assert "abv must be a number" in payload["message"]


def test_verify_includes_latency_ms_in_response(client):
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(b"PNGDATA"), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert "latency_ms" in payload
    assert isinstance(payload["latency_ms"], float)
    assert payload["latency_ms"] >= 0


class FailingVisionService(VisionService):
    def extract(self, image_bytes: bytes):
        raise RuntimeError("simulated vision failure")


def test_verify_handles_vision_service_failure_gracefully(client):
    app.dependency_overrides[get_vision_service] = lambda: FailingVisionService()
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(b"PNGDATA"), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["error"] == "Verification failed"
    assert "unable to extract label text" in payload["message"].lower()
