import pytest
from types import SimpleNamespace

import app.vision_service as vision_service_module
from app.vision_service import (
    MockVisionService,
    OpenAIVisionService,
    VisionAuthError,
    VisionInvalidResponseError,
    VisionTimeoutError,
)
from app.models import ExtractedLabel


class FakeResponses:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.response


class FakeClient:
    def __init__(self, response=None, exc=None):
        self.responses = FakeResponses(response=response, exc=exc)


def _openai_service_with_response(response=None, exc=None):
    client = FakeClient(response=response, exc=exc)
    return OpenAIVisionService(api_key="test-key", client=client)


def _parsed_response(parsed, *, status="completed", output=None, incomplete_details=None, error=None):
    return SimpleNamespace(
        status=status,
        output=output or [],
        output_parsed=parsed,
        incomplete_details=incomplete_details,
        error=error,
    )


def _refusal_response():
    return _parsed_response(
        None,
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="refusal",
                        refusal="I cannot extract this label.",
                    )
                ],
            )
        ],
    )


def test_openai_default_model_is_gpt_4o_mini():
    assert OpenAIVisionService.VISION_MODEL == "gpt-4o-mini"


def test_openai_service_instantiates_modern_client(monkeypatch):
    constructed = {}

    class FakeResponses:
        def parse(self, **kwargs):
            raise AssertionError("network should not be called")

    class FakeOpenAI:
        def __init__(self, *, api_key, timeout):
            constructed["api_key"] = api_key
            constructed["timeout"] = timeout
            self.responses = FakeResponses()

    monkeypatch.setattr(vision_service_module, "OpenAI", FakeOpenAI)

    service = OpenAIVisionService(api_key="test-key")

    assert isinstance(service.client, FakeOpenAI)
    assert constructed == {
        "api_key": "test-key",
        "timeout": OpenAIVisionService.MODEL_TIMEOUT_SECONDS,
    }


def _label_from_payload(data):
    return ExtractedLabel(**data)


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
    svc = _openai_service_with_response(_parsed_response(_label_from_payload(_valid_payload())))

    res = svc.extract(b"not-really-an-image")

    assert res.raw_text == "Ketel One\nVodka\n40% ALC/VOL\n750 mL"
    assert res.extraction_confidence == 0.92


def test_openai_request_contains_image_and_structured_output_configuration():
    svc = _openai_service_with_response(_parsed_response(_label_from_payload(_valid_payload())))

    svc.extract(b"not-really-an-image")

    call = svc.client.responses.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["text_format"] is ExtractedLabel
    assert call["input"][0]["role"] == "system"
    assert call["input"][0]["content"][0]["text"]

    user_content = call["input"][1]["content"]
    image_part = next(part for part in user_content if part["type"] == "input_image")
    assert image_part["image_url"].startswith("data:image/jpeg;base64,")
    assert image_part["detail"] == "auto"


def test_openai_valid_null_fields_are_allowed_when_contract_keys_are_present():
    payload = _valid_payload()
    for field in (
        "brand_name",
        "class_type",
        "producer",
        "country_of_origin",
        "abv",
        "net_contents",
        "government_warning",
        "raw_text",
        "extraction_confidence",
    ):
        payload[field] = None

    svc = _openai_service_with_response(_parsed_response(_label_from_payload(payload)))

    res = svc.extract(b"not-really-an-image")

    assert isinstance(res, ExtractedLabel)
    assert res.brand_name is None
    assert res.government_warning is None


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
    svc = _openai_service_with_response(_parsed_response({"abv": "not a number"}))

    with pytest.raises(VisionInvalidResponseError):
        svc.extract(b"not-really-an-image")


def test_openai_invalid_structured_output_maps_to_typed_exception():
    payload = _valid_payload()
    payload.pop("raw_text")
    svc = _openai_service_with_response(_parsed_response(payload))

    with pytest.raises(VisionInvalidResponseError):
        svc.extract(b"not-really-an-image")


def test_vision_failures_do_not_return_all_none_label():
    svc = _openai_service_with_response(_parsed_response(None))

    with pytest.raises(VisionInvalidResponseError) as exc_info:
        svc.extract(b"not-really-an-image")

    assert not isinstance(exc_info.value, ExtractedLabel)


def test_openai_refusal_maps_to_typed_exception():
    svc = _openai_service_with_response(_refusal_response())

    with pytest.raises(VisionInvalidResponseError):
        svc.extract(b"not-really-an-image")


def test_openai_incomplete_response_maps_to_typed_exception():
    svc = _openai_service_with_response(
        _parsed_response(
            None,
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
    )

    with pytest.raises(VisionInvalidResponseError):
        svc.extract(b"not-really-an-image")
