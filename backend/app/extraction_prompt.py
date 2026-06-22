"""Prompt templates and JSON schema for OpenAI Vision structured extraction."""
from __future__ import annotations

EXTRACTION_JSON_SCHEMA = {
    "name": "ExtractedLabel",
    "description": "Structured TTB label extraction result",
    "type": "object",
    "properties": {
        "brand_name": {"type": ["string", "null"], "description": "Brand name"},
        "class_type": {"type": ["string", "null"], "description": "Spirit class, e.g., Vodka"},
        "producer": {"type": ["string", "null"], "description": "Producer name"},
        "country_of_origin": {"type": ["string", "null"], "description": "Country of origin"},
        "abv": {"type": ["number", "null"], "description": "Alcohol by volume as a number (0-100)"},
        "net_contents": {"type": ["string", "null"], "description": "Bottle size text, e.g., '750 mL'"},
        "government_warning": {
            "type": ["string", "null"],
            "description": "The EXACT government warning text copied verbatim from the image. Case-sensitive. Do NOT normalize, paraphrase, or summarize. If not present, return null."
        },
    },
    "required": ["brand_name", "class_type", "producer", "country_of_origin", "abv", "net_contents", "government_warning"],
}


SYSTEM_INSTRUCTIONS = (
    "You are a strict data extraction assistant for TTB (alcohol) labels.\n"
    "Return ONLY a single JSON object that conforms to the provided JSON schema.\n"
    "The 'government_warning' field must be copied VERBATIM from the image, case-sensitive.\n"
    "If any field is not visible or not confidently readable, return null for that field.\n"
    "Do NOT include explanatory text outside the JSON object.\n"
)


def build_user_prompt(image_b64: str) -> str:
    return f"Extract the label data from this image (base64):\n{image_b64}\nReturn the JSON object only."
