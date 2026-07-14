from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import BatchResult, ExtractedLabel, FieldResult, VerificationResult


def _field_result() -> FieldResult:
    return FieldResult(
        field="brand_name",
        match_type="fuzzy",
        expected="Ketel One",
        found="Ketel One",
        status="PASS",
        reason="Fuzzy match at 100.0%",
    )


def _verification_result() -> VerificationResult:
    return VerificationResult(
        overall_verdict="APPROVED",
        field_results=[_field_result()],
        timestamp=datetime.now(timezone.utc),
        latency_ms=12.5,
    )


def test_field_result_serializes_required_field_names():
    result = _field_result()

    assert result.model_dump() == {
        "field": "brand_name",
        "match_type": "fuzzy",
        "expected": "Ketel One",
        "found": "Ketel One",
        "status": "PASS",
        "reason": "Fuzzy match at 100.0%",
    }


def test_extracted_label_includes_raw_text_and_extraction_confidence():
    extracted = ExtractedLabel(raw_text="label OCR text", extraction_confidence=0.92)

    payload = extracted.model_dump()
    assert payload["raw_text"] == "label OCR text"
    assert payload["extraction_confidence"] == 0.92


def test_verification_result_requires_and_contains_latency_ms():
    result = _verification_result()
    assert result.model_dump()["latency_ms"] == 12.5

    with pytest.raises(ValidationError):
        VerificationResult(
            overall_verdict="APPROVED",
            field_results=[_field_result()],
            timestamp=datetime.now(timezone.utc),
        )


def test_batch_result_top_level_has_only_items_and_summary():
    result = BatchResult(
        items=[_verification_result()],
        summary={"passed": 1, "needs_review": 0, "total": 1},
    )

    assert set(result.model_dump().keys()) == {"items", "summary"}
