import io

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_vision_service
from app.models import ExtractedLabel
from app.vision_service import MockVisionService, VisionAuthError, VisionInvalidResponseError, VisionService
import json


@pytest.fixture(autouse=True)
def mock_vision_service_override():
    get_vision_service.cache_clear()
    app.dependency_overrides[get_vision_service] = lambda: MockVisionService(scenario="clear")
    yield
    app.dependency_overrides.clear()
    get_vision_service.cache_clear()


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
    assert payload["field_results"][0]["field"] == "brand_name"
    assert payload["latency_ms"] >= 0


def test_get_vision_service_returns_cached_instance(monkeypatch):
    instances = []

    class FakeOpenAIVisionService(VisionService):
        def __init__(self):
            instances.append(self)

        def extract(self, image_bytes: bytes):
            return ExtractedLabel()

    import app.main as main_module

    get_vision_service.cache_clear()
    monkeypatch.setattr(main_module, "OpenAIVisionService", FakeOpenAIVisionService)

    first = get_vision_service()
    second = get_vision_service()

    assert first is second
    assert instances == [first]


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


class AuthFailingVisionService(VisionService):
    def extract(self, image_bytes: bytes):
        raise VisionAuthError("OPENAI_API_KEY=sk-secret provider body stacktrace")


def test_verify_typed_vision_error_is_structured_and_sanitized(client):
    app.dependency_overrides[get_vision_service] = lambda: AuthFailingVisionService()
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(b"PNGDATA"), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["error"] == "Verification failed"
    assert "temporarily unavailable" in payload["message"].lower()
    body = response.text.lower()
    assert "sk-secret" not in body
    assert "openai_api_key" not in body
    assert "provider body" not in body
    assert "stacktrace" not in body


def _batch_meta_items(n, brand_names=None):
    base = {
        "brand_name": "Ketel One",
        "class_type": "Vodka",
        "producer": "Ketel Distillery",
        "country_of_origin": "Netherlands",
        "abv": 40.0,
        "net_contents": "750 mL",
        "government_warning": (
            "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink..."
        ),
    }
    items = []
    for i in range(n):
        item = base.copy()
        if brand_names is not None:
            item["brand_name"] = brand_names[i]
        items.append(item)
    return items


def _assert_verification_result_contract(item):
    assert set(item.keys()) == {"overall_verdict", "field_results", "timestamp", "latency_ms"}
    assert item["overall_verdict"] in {"APPROVED", "NEEDS_REVIEW"}
    assert isinstance(item["field_results"], list)
    assert item["latency_ms"] >= 0
    for field in item["field_results"]:
        assert set(field.keys()) == {"field", "match_type", "expected", "found", "status", "reason"}


def _collect_keys(value):
    if isinstance(value, dict):
        keys = set(value.keys())
        for child in value.values():
            keys.update(_collect_keys(child))
        return keys
    if isinstance(value, list):
        keys = set()
        for child in value:
            keys.update(_collect_keys(child))
        return keys
    return set()


def test_verify_batch_response_contract_all_pass(client):
    files = [
        ("images", (f"label{i}.png", io.BytesIO(b"PNGDATA"), "image/png"))
        for i in range(3)
    ]
    meta = json.dumps(_batch_meta_items(3))
    response = client.post("/verify/batch", files=files, data={"metadata": meta})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"items", "summary"}
    assert set(payload["summary"].keys()) == {"passed", "needs_review", "total"}
    assert payload["summary"] == {"passed": 3, "needs_review": 0, "total": 3}
    assert len(payload["items"]) == 3
    for item in payload["items"]:
        _assert_verification_result_contract(item)


class MixedVisionService(VisionService):
    def extract(self, image_bytes: bytes):
        if image_bytes == b"PARTIAL":
            return MockVisionService(scenario="partial").extract(image_bytes)
        return MockVisionService(scenario="clear").extract(image_bytes)


def test_verify_batch_mixed_approved_and_needs_review_summary_counts(client):
    app.dependency_overrides[get_vision_service] = lambda: MixedVisionService()
    files = [
        ("images", ("label0.png", io.BytesIO(b"PNGDATA"), "image/png")),
        ("images", ("label1.png", io.BytesIO(b"PARTIAL"), "image/png")),
    ]
    meta = json.dumps(_batch_meta_items(2))
    response = client.post("/verify/batch", files=files, data={"metadata": meta})

    assert response.status_code == 200
    payload = response.json()
    assert [item["overall_verdict"] for item in payload["items"]] == ["APPROVED", "NEEDS_REVIEW"]
    assert payload["summary"] == {"passed": 1, "needs_review": 1, "total": 2}
    assert all("latency_ms" in item for item in payload["items"])


class UnreadableVisionService(VisionService):
    def extract(self, image_bytes: bytes):
        raise VisionInvalidResponseError("unreadable")


def test_verify_batch_unreadable_image_becomes_needs_review_item(client):
    app.dependency_overrides[get_vision_service] = lambda: UnreadableVisionService()
    files = [("images", ("label.png", io.BytesIO(b"BADIMAGE"), "image/png"))]
    meta = json.dumps(_batch_meta_items(1))
    response = client.post("/verify/batch", files=files, data={"metadata": meta})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {"passed": 0, "needs_review": 1, "total": 1}
    item = payload["items"][0]
    _assert_verification_result_contract(item)
    assert item["overall_verdict"] == "NEEDS_REVIEW"
    raw_text_failure = item["field_results"][0]
    assert raw_text_failure["field"] == "raw_text"
    assert raw_text_failure["found"] is None
    assert "photo could not be read" in raw_text_failure["reason"].lower()


class OrderedVisionService(VisionService):
    def extract(self, image_bytes: bytes):
        brand_name = image_bytes.decode("ascii")
        return ExtractedLabel(
            brand_name=brand_name,
            class_type="Vodka",
            producer="Ketel Distillery",
            country_of_origin="Netherlands",
            abv=40.0,
            net_contents="750 mL",
            government_warning=(
                "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink..."
            ),
        )


def test_verify_batch_preserves_original_item_order(client):
    app.dependency_overrides[get_vision_service] = lambda: OrderedVisionService()
    brand_names = ["First Label", "Second Label", "Third Label"]
    files = [
        ("images", (f"label{i}.png", io.BytesIO(name.encode("ascii")), "image/png"))
        for i, name in enumerate(brand_names)
    ]
    meta = json.dumps(_batch_meta_items(3, brand_names=brand_names))
    response = client.post("/verify/batch", files=files, data={"metadata": meta})

    assert response.status_code == 200
    payload = response.json()
    assert [
        item["field_results"][0]["expected"]
        for item in payload["items"]
    ] == brand_names


def test_verify_single_response_contract_and_no_old_names(client):
    response = client.post(
        "/verify",
        files={"image": ("label.png", io.BytesIO(b"PNGDATA"), "image/png")},
        data=_base_form_data(),
    )

    assert response.status_code == 200
    payload = response.json()
    _assert_verification_result_contract(payload)
    forbidden = {"field_name", "extracted_value", "submitted_value", "VerificationResponse", "BatchResponse"}
    assert _collect_keys(payload).isdisjoint(forbidden)


def test_verify_batch_serialized_response_has_no_old_names(client):
    files = [("images", ("label.png", io.BytesIO(b"PNGDATA"), "image/png"))]
    meta = json.dumps(_batch_meta_items(1))
    response = client.post("/verify/batch", files=files, data={"metadata": meta})

    assert response.status_code == 200
    payload = response.json()
    forbidden = {
        "field_name",
        "extracted_value",
        "submitted_value",
        "VerificationResponse",
        "BatchResponse",
        "errors",
        "results",
        "total",
        "passed",
        "needs_review",
    }
    assert set(payload.keys()) == {"items", "summary"}
    assert _collect_keys(payload).isdisjoint(forbidden - {"total", "passed", "needs_review"})
    assert "results" not in payload
    assert "errors" not in payload


def test_verify_batch_exceeds_max_size(client):
    # default MAX_BATCH_SIZE is 8; create 9 metadata entries
    files = [("images", (f"label{i}.png", io.BytesIO(b"PNGDATA"), "image/png")) for i in range(9)]
    meta = json.dumps(_batch_meta_items(9))
    response = client.post("/verify/batch", files=files, data={"metadata": meta})
    assert response.status_code == 400
