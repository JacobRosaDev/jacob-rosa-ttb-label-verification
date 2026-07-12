"""VisionService implementations: interface, OpenAI-backed, and Mock for tests."""
from __future__ import annotations

import base64
import io
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from PIL import Image
from pydantic import ValidationError

from openai import OpenAI

from .extraction_prompt import EXTRACTION_JSON_SCHEMA, SYSTEM_INSTRUCTIONS, build_user_prompt
from .models import ExtractedLabel

logger = logging.getLogger(__name__)


class VisionTimeoutError(RuntimeError):
    """Vision provider did not return a result before the timeout."""


class VisionInvalidResponseError(RuntimeError):
    """Vision provider returned malformed or schema-invalid output."""


class VisionAuthError(RuntimeError):
    """Vision provider rejected authentication or authorization."""


class VisionModelValidationError(RuntimeError):
    """Configured vision model is unavailable or cannot be validated."""


class VisionService(ABC):
    @abstractmethod
    def extract(self, image_bytes: bytes) -> ExtractedLabel:
        """Extract structured label data from image bytes."""


class MockVisionService(VisionService):
    """A simple mock service for tests. Returns preconfigured results based on a key."""

    def __init__(self, scenario: str = "clear"):
        self.scenario = scenario

    def extract(self, image_bytes: bytes) -> ExtractedLabel:
        if self.scenario == "clear":
            return ExtractedLabel(
                brand_name="Ketel One",
                class_type="Vodka",
                producer="Ketel Distillery",
                country_of_origin="Netherlands",
                abv=40.0,
                net_contents="750 mL",
                government_warning=(
                    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink..."
                ),
            )
        elif self.scenario == "blurry":
            return ExtractedLabel()  # all None
        elif self.scenario == "partial":
            return ExtractedLabel(
                brand_name="Ketel One",
                class_type=None,
                producer=None,
                country_of_origin="Netherlands",
                abv=None,
                net_contents="750 mL",
                government_warning=None,
            )
        else:
            return ExtractedLabel()


class OpenAIVisionService(VisionService):
    """Uses OpenAI's Responses API with image input and JSON schema structured output.

    Note: network calls are not used in tests.
    """

    VISION_MODEL = os.environ.get("VISION_MODEL", "gpt-4o-mini")
    MAX_IMAGE_DIMENSION = int(os.environ.get("MAX_IMAGE_DIMENSION", 900))
    JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", 80))
    MODEL_TIMEOUT_SECONDS = int(os.environ.get("MODEL_TIMEOUT_SECONDS", 4))

    def __init__(self, api_key: Optional[str] = None, client: Any | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.client = client
        if self.client is None and self.api_key:
            self.client = OpenAI(api_key=self.api_key, timeout=self.MODEL_TIMEOUT_SECONDS)

    def validate_model_available(self) -> None:
        if not self.client:
            raise VisionModelValidationError(
                f"Vision model '{self.VISION_MODEL}' could not be validated."
            )

        try:
            self.client.models.retrieve(self.VISION_MODEL)
        except Exception:
            raise VisionModelValidationError(
                f"Vision model '{self.VISION_MODEL}' is unavailable or could not be validated."
            ) from None

    def _preprocess(self, image_bytes: bytes) -> bytes:
        # Downscale to a reasonable max dimension and re-encode as JPEG to reduce payload
        try:
            img = Image.open(io.BytesIO(image_bytes))
            img = img.convert("RGB")
            max_dim = self.MAX_IMAGE_DIMENSION
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                new_size = (int(w * scale), int(h * scale))
                img = img.resize(new_size, Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=self.JPEG_QUALITY)
            return out.getvalue()
        except Exception as e:
            logger.warning("Image preprocessing failed: %s", e)
            return image_bytes

    def _has_refusal(self, response: Any) -> bool:
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "refusal" or getattr(content, "refusal", None):
                    return True
        return False

    def _validate_parsed_response(self, response: Any) -> ExtractedLabel:
        status = getattr(response, "status", None)
        if status == "incomplete" or getattr(response, "incomplete_details", None):
            raise VisionInvalidResponseError("Vision model response was incomplete.")

        if status is not None and status != "completed":
            raise VisionInvalidResponseError("Vision model did not complete extraction.")

        if getattr(response, "error", None):
            raise VisionInvalidResponseError("Vision model returned a provider failure response.")

        if self._has_refusal(response):
            raise VisionInvalidResponseError("Vision model refused to extract label data.")

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise VisionInvalidResponseError("Vision model returned no parsed structured output.")

        if isinstance(parsed, dict):
            try:
                parsed = ExtractedLabel.model_validate(parsed)
            except ValidationError as exc:
                raise VisionInvalidResponseError("Vision model output did not match the expected schema.") from exc

        if not isinstance(parsed, ExtractedLabel):
            raise VisionInvalidResponseError("Vision model output did not match the expected schema.")

        required_fields = EXTRACTION_JSON_SCHEMA.get("required", [])
        missing_fields = [field for field in required_fields if field not in parsed.model_fields_set]
        if missing_fields:
            raise VisionInvalidResponseError("Vision model output was missing required fields.")

        return parsed

    def _map_provider_exception(self, exc: Exception) -> Exception:
        exc_name = exc.__class__.__name__.lower()
        status_code = getattr(exc, "status_code", None)

        if isinstance(exc, TimeoutError) or "timeout" in exc_name:
            return VisionTimeoutError("Vision provider timed out.")

        if status_code in (401, 403) or any(token in exc_name for token in ("auth", "permission", "forbidden", "unauthorized")):
            return VisionAuthError("Vision provider authentication failed.")

        return exc

    def extract(self, image_bytes: bytes) -> ExtractedLabel:
        # preprocess image
        processed = self._preprocess(image_bytes)

        if not self.client:
            raise VisionAuthError("Vision provider authentication failed.")

        b64 = base64.b64encode(processed).decode("ascii")
        user_prompt = build_user_prompt("")
        image_url = f"data:image/jpeg;base64,{b64}"

        try:
            response = self.client.responses.parse(
                model=self.VISION_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": SYSTEM_INSTRUCTIONS}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": user_prompt},
                            {"type": "input_image", "image_url": image_url, "detail": "auto"},
                        ],
                    },
                ],
                text_format=ExtractedLabel,
            )

            return self._validate_parsed_response(response)
        except VisionInvalidResponseError:
            raise
        except ValidationError as exc:
            raise VisionInvalidResponseError("Vision model output did not match the expected schema.") from exc
        except Exception as e:
            mapped = self._map_provider_exception(e)
            if mapped is e:
                raise
            raise mapped from e
