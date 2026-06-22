"""VisionService implementations: interface, OpenAI-backed, and Mock for tests."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from PIL import Image

from .models import ExtractedLabel
from .extraction_prompt import EXTRACTION_JSON_SCHEMA, SYSTEM_INSTRUCTIONS, build_user_prompt

logger = logging.getLogger(__name__)


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

    def extract(self, image_bytes: bytes) -> ExtractedLabel:
        # preprocess image
        processed = self._preprocess(image_bytes)

        if not self.openai:
            logger.warning("OpenAI SDK not available; returning empty ExtractedLabel")
            return ExtractedLabel()

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

            # SDK returns structured output under 'output' or 'json_schema' depending on version.
            parsed = None
            # Try common locations defensively
            if hasattr(response, "output"):
                for item in response.output:
                    if getattr(item, "type", None) == "json_schema":
                        parsed = item.data
                        break
            if parsed is None and hasattr(response, "json"):
                parsed = response.json()
            if parsed is None:
                # Fallback: try to extract content and parse
                text = getattr(response, "text", None) or str(response)
                try:
                    parsed = json.loads(text)
                except Exception:
                    logger.exception("Failed to parse model response as JSON")
                    return ExtractedLabel()

            # parsed should be a dict matching schema
            if isinstance(parsed, dict):
                # Convert fields and defensively map types
                def get_str(k):
                    v = parsed.get(k)
                    return v if isinstance(v, str) else None

                def get_num(k):
                    v = parsed.get(k)
                    if isinstance(v, (int, float)):
                        return float(v)
                    try:
                        return float(v)
                    except Exception:
                        return None

                return ExtractedLabel(
                    brand_name=get_str("brand_name"),
                    class_type=get_str("class_type"),
                    producer=get_str("producer"),
                    country_of_origin=get_str("country_of_origin"),
                    abv=get_num("abv"),
                    net_contents=get_str("net_contents"),
                    government_warning=get_str("government_warning"),
                )

            logger.warning("Model returned unexpected structured payload: %r", parsed)
            return ExtractedLabel()

        except Exception as e:
            logger.exception("Vision model call failed: %s", e)
            return ExtractedLabel()
