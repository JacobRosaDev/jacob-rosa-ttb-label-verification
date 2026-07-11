"""
Phase 1: Comparison functions for TTB label verification.
Pure functions with no side effects.
"""

import re
from datetime import datetime, timezone
from typing import TypeVar

from rapidfuzz import fuzz

from app.models import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    VerificationResult,
)

T = TypeVar("T")

# Country canonicalization map (normalized to uppercase)
COUNTRY_SYNONYMS = {
    "USA": "USA",
    "UNITED STATES": "USA",
    "US": "USA",
    "GB": "UNITED KINGDOM",
    "UNITED KINGDOM": "UNITED KINGDOM",
    "UK": "UNITED KINGDOM",
    "NL": "NETHERLANDS",
    "NETHERLANDS": "NETHERLANDS",
    "FR": "FRANCE",
    "FRANCE": "FRANCE",
    "DE": "GERMANY",
    "GERMANY": "GERMANY",
}

# Canonical TTB government warning
CANONICAL_WARNING = "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."


def _normalize_whitespace(text: str | None) -> str:
    """Collapse multiple spaces/tabs to single space, strip leading/trailing."""
    if text is None:
        return ""
    return " ".join(text.split()).strip()


def _normalize_text(text: str | None) -> str:
    """Normalize optional text for comparison functions."""
    if text is None:
        return ""
    return text.strip()


def _fuzzy_match(extracted: str | None, submitted: str | None, threshold: float = 90.0) -> tuple[bool, float]:
    """
    Fuzzy string matching (case-insensitive).
    Returns (is_pass, similarity_ratio).
    """
    norm_extracted = _normalize_text(extracted).lower()
    norm_submitted = _normalize_text(submitted).lower()
    ratio = fuzz.token_sort_ratio(norm_extracted, norm_submitted)
    return (ratio >= threshold, ratio)


def compare_brand_name(extracted: str | None, submitted: str) -> FieldResult:
    """Compare brand_name with fuzzy matching (>=90%)."""
    extracted_value = extracted or ""
    is_pass, ratio = _fuzzy_match(extracted_value, submitted, threshold=90.0)
    return FieldResult(
        field="brand_name",
        match_type="fuzzy",
        expected=submitted,
        found=extracted_value,
        status="PASS" if is_pass else "FAIL",
        reason=f"Fuzzy match at {ratio:.1f}%",
    )


def compare_class_type(extracted: str | None, submitted: str) -> FieldResult:
    """Compare class_type with fuzzy matching (>=90%)."""
    extracted_value = extracted or ""
    is_pass, ratio = _fuzzy_match(extracted_value, submitted, threshold=90.0)
    return FieldResult(
        field="class_type",
        match_type="fuzzy",
        expected=submitted,
        found=extracted_value,
        status="PASS" if is_pass else "FAIL",
        reason=f"Fuzzy match at {ratio:.1f}%",
    )


def compare_producer(extracted: str | None, submitted: str) -> FieldResult:
    """Compare producer with fuzzy matching (>=90%)."""
    extracted_value = extracted or ""
    is_pass, ratio = _fuzzy_match(extracted_value, submitted, threshold=90.0)
    return FieldResult(
        field="producer",
        match_type="fuzzy",
        expected=submitted,
        found=extracted_value,
        status="PASS" if is_pass else "FAIL",
        reason=f"Fuzzy match at {ratio:.1f}%",
    )


def compare_country_of_origin(extracted: str | None, submitted: str) -> FieldResult:
    """
    Compare country with exact match or synonym lookup.
    Both values normalized to uppercase.
    """
    norm_extracted = _normalize_text(extracted).upper()
    norm_submitted = _normalize_text(submitted).upper()

    # Check direct match
    extracted_value = extracted or ""
    if norm_extracted == norm_submitted:
        return FieldResult(
            field="country_of_origin",
            match_type="exact",
            expected=submitted,
            found=extracted_value,
            status="PASS",
            reason="Exact match",
        )

    # Check canonicalized synonym match
    canonical_extracted = COUNTRY_SYNONYMS.get(norm_extracted, norm_extracted)
    canonical_submitted = COUNTRY_SYNONYMS.get(norm_submitted, norm_submitted)

    if canonical_extracted == canonical_submitted:
        return FieldResult(
            field="country_of_origin",
            match_type="synonym",
            expected=submitted,
            found=extracted_value,
            status="PASS",
            reason="Synonym match",
        )

    return FieldResult(
        field="country_of_origin",
        match_type="synonym",
        expected=submitted,
        found=extracted_value,
        status="FAIL",
        reason=f"No match (extracted: {norm_extracted}, submitted: {norm_submitted})",
    )


def _valid_abv(value: float) -> float | None:
    return value if 0.0 <= value <= 100.0 else None


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _parse_abv(text: str | None) -> float | None:
    """
    Parse ABV from various formats: "45", "45%", "45% Alc./Vol.", "45% Alcohol by Volume", etc.
    Returns float or None if unparseable.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None

    number = r"(-?\d+(?:\.\d+)?)"
    upper_text = text.upper()

    context_patterns = [
        rf"{number}\s*%",
        rf"{number}\s*PERCENT\b",
        rf"{number}\s*(?:%?\s*)ABV\b",
        rf"\bABV\b\s*{number}",
        rf"{number}\s*%?\s*ALC\.?\s*/\s*VOL\.?",
        rf"\bALC\.?\s*/\s*VOL\.?\s*{number}",
        rf"{number}\s*%?\s*ALCOHOL\s+BY\s+VOLUME\b",
        rf"\bALCOHOL\s+BY\s+VOLUME\b\s*{number}",
    ]
    for pattern in context_patterns:
        match = re.search(pattern, upper_text)
        if match:
            value = _to_float(match.group(1))
            return _valid_abv(value) if value is not None else None

    proof_match = re.search(rf"{number}\s*PROOF\b", upper_text)
    if proof_match:
        proof = _to_float(proof_match.group(1))
        return _valid_abv(proof / 2.0) if proof is not None else None

    bare_match = re.fullmatch(number, upper_text)
    if bare_match:
        value = _to_float(bare_match.group(1))
        return _valid_abv(value) if value is not None else None

    return None


def compare_abv(extracted: str | float | None, submitted: str | float) -> FieldResult:
    """
    Compare ABV with numeric parsing and +/-0.1% tolerance.
    """
    submitted_text = str(submitted)

    if extracted is None:
        return FieldResult(
            field="abv",
            match_type="numeric",
            expected=submitted_text,
            found="",
            status="FAIL",
            reason="ABV not extracted",
        )

    extracted_text = str(extracted)
    extracted_abv = _parse_abv(extracted_text)
    submitted_abv = _parse_abv(submitted_text)

    if extracted_abv is None or submitted_abv is None:
        return FieldResult(
            field="abv",
            match_type="numeric",
            expected=submitted_text,
            found=extracted_text,
            status="FAIL",
            reason=f"Unable to parse ABV (extracted: {extracted_abv}, submitted: {submitted_abv})",
        )

    tolerance = 0.1
    diff = abs(extracted_abv - submitted_abv)

    is_pass = diff <= tolerance
    return FieldResult(
        field="abv",
        match_type="numeric",
        expected=submitted_text,
        found=extracted_text,
        status="PASS" if is_pass else "FAIL",
        reason=f"Difference: {diff:.2f}% (tolerance: +/-{tolerance}%)",
    )


def _parse_net_contents(text: str | None) -> float | None:
    """
    Parse net contents to mL. Supports: "750 mL", "750ml", "0.75L", "25 FL OZ", etc.
    Returns volume in mL or None if unparseable.
    """
    if text is None:
        return None
    text = text.strip().upper()

    # Extract quantity and unit (handle multi-word units like "FL OZ")
    match = re.search(r"(\d+\.?\d*)\s*([A-Z]+(?:\s+[A-Z]+)?)", text)
    if not match:
        return None

    qty = float(match.group(1))
    unit = match.group(2).strip()

    # Normalize to mL
    conversions = {
        "ML": 1.0,
        "L": 1000.0,
        "FL OZ": 29.5735,
        "FLOZ": 29.5735,
        "OZ": 29.5735,
    }

    if unit in conversions:
        return qty * conversions[unit]

    return None


def compare_net_contents(extracted: str, submitted: str) -> FieldResult:
    """
    Compare net contents: normalize both to mL, allow +/-1 mL tolerance.
    """
    extracted_ml = _parse_net_contents(extracted)
    submitted_ml = _parse_net_contents(submitted)

    if extracted_ml is None or submitted_ml is None:
        return FieldResult(
            field="net_contents",
            match_type="unit",
            expected=submitted,
            found=extracted,
            status="FAIL",
            reason=f"Unable to parse (extracted: {extracted_ml} mL, submitted: {submitted_ml} mL)",
        )

    diff = abs(extracted_ml - submitted_ml)

    is_pass = diff <= 1.0

    return FieldResult(
        field="net_contents",
        match_type="unit",
        expected=submitted,
        found=extracted,
        status="PASS" if is_pass else "FAIL",
        reason=f"Difference: {diff:.2f} mL (tolerance: +/-1.0 mL)",
    )


def compare_government_warning(extracted: str, submitted: str) -> FieldResult:
    """
    Compare government warning: exact case-sensitive match after whitespace collapse.
    No fuzzy matching - exact only.
    """
    # Normalize whitespace (collapse multiple spaces, trim)
    norm_extracted = _normalize_whitespace(extracted)
    norm_submitted = _normalize_whitespace(submitted)

    is_pass = norm_extracted == norm_submitted

    extracted_value = extracted or ""
    return FieldResult(
        field="government_warning",
        match_type="exact",
        expected=submitted,
        found=extracted_value,
        status="PASS" if is_pass else "FAIL",
        reason="Exact case-sensitive match after whitespace collapse" if is_pass else "Mismatch in text or case",
    )


def verify_label(extracted: ExtractedLabel, submitted: ApplicationData, latency_ms: float = 0.0) -> VerificationResult:
    """
    Compare extracted label against submitted application data.
    Returns VerificationResult with individual field results.
    """
    field_results = [
        compare_brand_name(extracted.brand_name, submitted.brand_name),
        compare_class_type(extracted.class_type, submitted.class_type),
        compare_producer(extracted.producer, submitted.producer),
        compare_country_of_origin(extracted.country_of_origin, submitted.country_of_origin),
        compare_abv(extracted.abv, submitted.abv),
        compare_net_contents(extracted.net_contents, submitted.net_contents),
        compare_government_warning(extracted.government_warning, submitted.government_warning),
    ]

    # Verdict: any FAIL means NEEDS_REVIEW
    has_fail = any(result.status == "FAIL" for result in field_results)
    overall_verdict = "NEEDS_REVIEW" if has_fail else "APPROVED"

    return VerificationResult(
        overall_verdict=overall_verdict,
        field_results=field_results,
        timestamp=datetime.now(timezone.utc),
        latency_ms=latency_ms,
    )

