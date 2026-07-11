import pytest
from types import SimpleNamespace

from app.vision_service import (
    MockVisionService,
    OpenAIVisionService,
    VisionAuthError,
    VisionInvalidResponseError,
    VisionTimeoutError,
)
from app.models import ExtractedLabel


def _openai_service_with_response(response=None, exc=None):
    class FakeResponses:
        def create(self, **kwargs):
            if exc is not None:
                raise exc
            return response

    service = OpenAIVisionService(api_key="test-key")
    service.openai = SimpleNamespace(responses=FakeResponses())
    return service


def _json_schema_response(data):
    return SimpleNamespace(
        output=[
            SimpleNamespace(
                type="json_schema",
                data=data,
            )
        ]
    )


def _valid_payload():
    return {
        "brand_name": "Ketel One",
        "class_type": "Vodka",
        "producer": "Ketel Distillery",
        "country_of_origin": "Netherlands",
        "abv": 40.0,
        "net_contents": "750 mL",
        "government_warning": (
            "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink..."
        ),
        "raw_text": "Ketel One\nVodka\n40% ALC/VOL\n750 mL",
        "extraction_confidence": 0.92,
    }


def test_mock_clear_label_returns_populated():
    svc = MockVisionService(scenario="clear")
    res = svc.extract(b"fakebytes")
    assert isinstance(res, ExtractedLabel)
    assert res.brand_name == "Ketel One"
    assert res.class_type == "Vodka"
    assert res.abv == 40.0


def test_mock_blurry_returns_all_none():
    svc = MockVisionService(scenario="blurry")
    res = svc.extract(b"fakebytes")
    # all fields should be None
    assert res.brand_name is None
    assert res.government_warning is None


def test_mock_partial_returns_some_fields():
    svc = MockVisionService(scenario="partial")
    res = svc.extract(b"fakebytes")
    assert res.brand_name == "Ketel One"
    assert res.net_contents == "750 mL"
    assert res.class_type is None


def test_openai_valid_output_populates_metadata():
    svc = _openai_service_with_response(_json_schema_response(_valid_payload()))

    res = svc.extract(b"not-really-an-image")

    assert res.raw_text == "Ketel One\nVodka\n40% ALC/VOL\n750 mL"
    assert res.extraction_confidence == 0.92


def test_openai_timeout_maps_to_typed_exception():
    svc = _openai_service_with_response(exc=TimeoutError("provider timed out"))

    with pytest.raises(VisionTimeoutError):
        svc.extract(b"not-really-an-image")


def test_openai_auth_failure_maps_to_typed_exception():
    class AuthenticationError(Exception):
        status_code = 401

    svc = _openai_service_with_response(exc=AuthenticationError("sk-secret provider response"))

    with pytest.raises(VisionAuthError):
        svc.extract(b"not-really-an-image")


def test_openai_invalid_json_maps_to_typed_exception():
    svc = _openai_service_with_response(SimpleNamespace(text="{not valid json"))

    with pytest.raises(VisionInvalidResponseError):
        svc.extract(b"not-really-an-image")


def test_openai_invalid_structured_output_maps_to_typed_exception():
    payload = _valid_payload()
    payload.pop("raw_text")
    svc = _openai_service_with_response(_json_schema_response(payload))

    with pytest.raises(VisionInvalidResponseError):
        svc.extract(b"not-really-an-image")


def test_vision_failures_do_not_return_all_none_label():
    svc = _openai_service_with_response(SimpleNamespace(output=[]))

    with pytest.raises(VisionInvalidResponseError) as exc_info:
        svc.extract(b"not-really-an-image")

    assert not isinstance(exc_info.value, ExtractedLabel)
