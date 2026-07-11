"""VisionService implementations: interface, OpenAI-backed, and Mock for tests."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from PIL import Image
from pydantic import ValidationError

from .models import ExtractedLabel
from .extraction_prompt import EXTRACTION_JSON_SCHEMA, SYSTEM_INSTRUCTIONS, build_user_prompt

logger = logging.getLogger(__name__)


class VisionTimeoutError(RuntimeError):
    """Vision provider did not return a result before the timeout."""


class VisionInvalidResponseError(RuntimeError):
    """Vision provider returned malformed or schema-invalid output."""


class VisionAuthError(RuntimeError):
    """Vision provider rejected authentication or authorization."""


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

    VISION_MODEL = os.environ.get("VISION_MODEL", "gpt-4o-mini-vision")
    MAX_IMAGE_DIMENSION = int(os.environ.get("MAX_IMAGE_DIMENSION", 900))
    JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", 80))
    MODEL_TIMEOUT_SECONDS = int(os.environ.get("MODEL_TIMEOUT_SECONDS", 4))

    def __init__(self, api_key: Optional[str] = None):
        try:
            import openai

            self.openai = openai
        except Exception:  # pragma: no cover - environment dependent
            self.openai = None
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if self.openai and self.api_key:
            self.openai.api_key = self.api_key

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

    def _parse_response_payload(self, response: Any) -> dict[str, Any]:
        parsed = None

        if hasattr(response, "output"):
            for item in response.output:
                if getattr(item, "type", None) == "json_schema":
                    parsed = getattr(item, "data", None)
                    break
                content = getattr(item, "content", None)
                if content:
                    for part in content:
                        text = getattr(part, "text", None)
                        if text:
                            parsed = json.loads(text)
                            break
                if parsed is not None:
                    break

        if parsed is None and hasattr(response, "output_parsed"):
            parsed = response.output_parsed

        if parsed is None and hasattr(response, "json"):
            parsed = response.json()

        if parsed is None:
            text = getattr(response, "text", None) or getattr(response, "output_text", None)
            if text:
                parsed = json.loads(text)

        if not isinstance(parsed, dict):
            raise VisionInvalidResponseError("Vision model returned no structured JSON object.")

        return parsed

    def _build_extracted_label(self, parsed: dict[str, Any]) -> ExtractedLabel:
        required_fields = EXTRACTION_JSON_SCHEMA.get("required", [])
        missing_fields = [field for field in required_fields if field not in parsed]
        if missing_fields:
            raise VisionInvalidResponseError("Vision model output was missing required fields.")

        try:
            return ExtractedLabel(**parsed)
        except ValidationError as exc:
            raise VisionInvalidResponseError("Vision model output did not match the expected schema.") from exc

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

        if not self.openai:
            raise RuntimeError("OpenAI SDK is not available.")

        b64 = base64.b64encode(processed).decode("ascii")
        user_prompt = build_user_prompt(b64)

        try:
            # Use the Responses API with structured output via json_schema
            response = self.openai.responses.create(
                model=self.VISION_MODEL,
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_prompt},
                ],
                # Structured output via json_schema (SDK-specific)
                json_schema=EXTRACTION_JSON_SCHEMA,
                # Timeout control
                timeout=self.MODEL_TIMEOUT_SECONDS,
            )

            parsed = self._parse_response_payload(response)
            return self._build_extracted_label(parsed)
        except json.JSONDecodeError as exc:
            raise VisionInvalidResponseError("Vision model returned invalid JSON.") from exc
        except VisionInvalidResponseError:
            raise
        except Exception as e:
            mapped = self._map_provider_exception(e)
            if mapped is e:
                raise
            raise mapped from e
