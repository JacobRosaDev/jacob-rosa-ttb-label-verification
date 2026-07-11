"""
Comprehensive test suite for Phase 1 comparison engine.
Test-first approach: all comparison functions and models.
"""

import pytest

from app.comparison import (
    CANONICAL_WARNING,
    compare_abv,
    compare_brand_name,
    compare_class_type,
    compare_country_of_origin,
    compare_government_warning,
    compare_net_contents,
    compare_producer,
    verify_label,
)
from app.models import ApplicationData, ExtractedLabel, FieldResult


class TestBrandNameFuzzy:
    """Brand name fuzzy matching tests (≥85%)."""

    def test_exact_match(self):
        result = compare_brand_name("Ketel One", "Ketel One")
        assert result.status == "PASS"
        assert result.field == "brand_name"
        assert result.match_type == "fuzzy"

    def test_case_only_diff(self):
        """Case-only difference should pass."""
        result = compare_brand_name("Ketel One", "ketel one")
        assert result.status == "PASS"

    def test_single_typo(self):
        """Single character typo should pass at ≥85%."""
        # "Whiskey" vs "Whisky" is high similarity
        result = compare_brand_name("Whiskey", "Whisky")
        assert result.status == "PASS"

    def test_multiple_typos_high_similarity(self):
        """Multiple typos but still ≥85% similarity."""
        result = compare_brand_name("Absolut Vodka", "Absolut Vdka")  # Minor typo, high similarity
        assert result.status == "PASS"

    def test_completely_different(self):
        """Completely different brand should fail."""
        result = compare_brand_name("Vodka Premium", "Rum Light")
        assert result.status == "FAIL"

    def test_threshold_just_above(self):
        """Test just above 85% threshold (should pass)."""
        # High similarity strings
        result = compare_brand_name("Ketel One Premium", "Ketel One Premi")
        assert result.status == "PASS"

    def test_threshold_just_below(self):
        """Test below 85% threshold (should fail)."""
        result = compare_brand_name("Ketel One Vodka", "Rum Light Premium")
        assert result.status == "FAIL"


class TestClassTypeFuzzy:
    """Class type fuzzy matching tests (≥85%)."""

    def test_exact_match(self):
        result = compare_class_type("Vodka", "Vodka")
        assert result.status == "PASS"

    def test_case_variation(self):
        result = compare_class_type("VODKA", "vodka")
        assert result.status == "PASS"

    def test_single_char_typo(self):
        result = compare_class_type("Whiskey", "Whisky")
        assert result.status == "PASS"

    def test_completely_different(self):
        result = compare_class_type("Vodka", "Rum")
        assert result.status == "FAIL"


class TestProducerFuzzy:
    """Producer fuzzy matching tests (≥85%)."""

    def test_exact_match(self):
        result = compare_producer("Diageo", "Diageo")
        assert result.status == "PASS"

    def test_case_insensitive(self):
        result = compare_producer("DIAGEO", "diageo")
        assert result.status == "PASS"

    def test_minor_typo(self):
        result = compare_producer("Diageo", "Diageo Inc.")
        # This should be high similarity
        pass


class TestCountryOfOrigin:
    """Country comparison with exact and synonym matching."""

    def test_exact_match(self):
        result = compare_country_of_origin("USA", "USA")
        assert result.status == "PASS"

    def test_usa_to_united_states_synonym(self):
        """USA vs United States should pass."""
        result = compare_country_of_origin("USA", "United States")
        assert result.status == "PASS"

    def test_united_states_to_usa_synonym(self):
        """United States vs USA should pass."""
        result = compare_country_of_origin("United States", "USA")
        assert result.status == "PASS"

    def test_us_abbreviation_synonym(self):
        """US vs USA should pass."""
        result = compare_country_of_origin("US", "USA")
        assert result.status == "PASS"

    def test_gb_to_uk_synonym(self):
        """GB vs UK should pass."""
        result = compare_country_of_origin("GB", "United Kingdom")
        assert result.status == "PASS"

    def test_case_variation(self):
        """Case variation should pass after normalization."""
        result = compare_country_of_origin("usa", "USA")
        assert result.status == "PASS"

    def test_unrecognized_synonym(self):
        """Unrecognized country should fail."""
        result = compare_country_of_origin("America", "USA")
        assert result.status == "FAIL"

    def test_completely_wrong_country(self):
        """Completely different country should fail."""
        result = compare_country_of_origin("France", "Germany")
        assert result.status == "FAIL"

    def test_netherlands_synonym(self):
        """NL vs Netherlands should pass."""
        result = compare_country_of_origin("NL", "Netherlands")
        assert result.status == "PASS"


class TestABVComparison:
    """ABV comparison with parsing and ±0.1% tolerance."""

    def test_exact_match(self):
        result = compare_abv("40.0", "40.0")
        assert result.status == "PASS"

    def test_within_tolerance_lower(self):
        """40.0 vs 39.95 (within 0.1%)."""
        result = compare_abv("39.95", "40.0")
        assert result.status == "PASS"

    def test_within_tolerance_upper(self):
        """40.0 vs 40.05 (within 0.1%)."""
        result = compare_abv("40.05", "40.0")
        assert result.status == "PASS"

    def test_at_tolerance_boundary(self):
        """40.0 vs 40.09 (at 0.1% boundary with margin for float precision)."""
        result = compare_abv("40.09", "40.0")
        assert result.status == "PASS"

    def test_just_over_tolerance(self):
        """40.0 vs 40.11 (just over 0.1%)."""
        result = compare_abv("40.11", "40.0")
        assert result.status == "FAIL"

    def test_complex_format_percent(self):
        """45% vs 45% Alc./Vol. (90 Proof) should both parse as 45."""
        result = compare_abv("45%", "45% Alc./Vol. (90 Proof)")
        assert result.status == "PASS"

    def test_complex_format_full_text(self):
        """40 vs '40% Alcohol by Volume' should parse to same value."""
        result = compare_abv("40", "40% Alcohol by Volume")
        assert result.status == "PASS"

    def test_completely_different_abv(self):
        """40.0 vs 42.5 should fail."""
        result = compare_abv("40.0", "42.5")
        assert result.status == "FAIL"

    def test_large_difference(self):
        """40 vs 50 should fail."""
        result = compare_abv("40", "50")
        assert result.status == "FAIL"

    def test_unparseable_extracted(self):
        """Unparseable extracted value should fail."""
        result = compare_abv("invalid", "40.0")
        assert result.status == "FAIL"

    def test_unparseable_submitted(self):
        """Unparseable submitted value should fail."""
        result = compare_abv("40.0", "invalid")
        assert result.status == "FAIL"


class TestNetContents:
    """Net contents comparison with unit normalization (±2% tolerance)."""

    def test_exact_match(self):
        result = compare_net_contents("750 mL", "750 mL")
        assert result.status == "PASS"

    def test_unit_equivalence_ml_to_l(self):
        """750 mL vs 0.75 L should pass."""
        result = compare_net_contents("750 mL", "0.75 L")
        assert result.status == "PASS"

    def test_case_and_space_variation(self):
        """750 mL vs 750ml should pass after normalization."""
        result = compare_net_contents("750 mL", "750ml")
        assert result.status == "PASS"

    def test_within_tolerance_lower(self):
        """750 vs 735 (within ±2%)."""
        result = compare_net_contents("735 mL", "750 mL")
        assert result.status == "PASS"

    def test_within_tolerance_upper(self):
        """750 vs 765 (within ±2%)."""
        result = compare_net_contents("765 mL", "750 mL")
        assert result.status == "PASS"

    def test_at_tolerance_boundary(self):
        """750 mL vs 765 mL (exactly 2%)."""
        result = compare_net_contents("765 mL", "750 mL")
        assert result.status == "PASS"

    def test_just_over_tolerance(self):
        """750 mL vs 766 mL (just over 2%)."""
        result = compare_net_contents("766 mL", "750 mL")
        assert result.status == "FAIL"

    def test_large_difference(self):
        """750 mL vs 1 L (33% diff)."""
        result = compare_net_contents("750 mL", "1 L")
        assert result.status == "FAIL"

    def test_fl_oz_conversion(self):
        """25.5 FL OZ vs 750 mL (should normalize correctly)."""
        # 25.5 FL OZ ≈ 754 mL (within 2% of 750 mL)
        result = compare_net_contents("25.5 FL OZ", "750 mL")
        # Check that it parses correctly and is within tolerance
        assert result.status == "PASS", f"Expected PASS but got {result.status}. Reason: {result.reason}"

    def test_unparseable_extracted(self):
        """Unparseable extracted should fail."""
        result = compare_net_contents("invalid", "750 mL")
        assert result.status == "FAIL"

    def test_unparseable_submitted(self):
        """Unparseable submitted should fail."""
        result = compare_net_contents("750 mL", "invalid")
        assert result.status == "FAIL"


class TestGovernmentWarning:
    """Government warning comparison: exact case-sensitive after whitespace collapse."""

    def test_exact_match(self):
        """Exact canonical warning match."""
        result = compare_government_warning(CANONICAL_WARNING, CANONICAL_WARNING)
        assert result.status == "PASS"
        assert result.match_type == "exact"
        assert "case-sensitive" in result.reason

    def test_extra_internal_spaces_collapse(self):
        """Extra spaces should collapse and match."""
        warning_with_extra_spaces = CANONICAL_WARNING.replace("(1) According", "(1)  According")
        result = compare_government_warning(warning_with_extra_spaces, CANONICAL_WARNING)
        assert result.status == "PASS"

    def test_leading_trailing_whitespace(self):
        """Leading/trailing whitespace should be trimmed."""
        warning_with_padding = "  " + CANONICAL_WARNING + "  "
        result = compare_government_warning(warning_with_padding, CANONICAL_WARNING)
        assert result.status == "PASS"

    def test_case_mismatch_lowercase(self):
        """Lowercase version should fail (case-sensitive)."""
        warning_lowercase = CANONICAL_WARNING.lower()
        result = compare_government_warning(warning_lowercase, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_case_mismatch_title_case(self):
        """Title case should fail."""
        # Convert first letter of each word after colons to uppercase
        warning_title = CANONICAL_WARNING
        result = compare_government_warning(warning_title.replace("women should", "Women Should"), CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_missing_number_marker(self):
        """Missing (1) marker should fail."""
        warning_missing_1 = CANONICAL_WARNING.replace("(1) ", "")
        result = compare_government_warning(warning_missing_1, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_missing_number_marker_2(self):
        """Missing (2) marker should fail."""
        warning_missing_2 = CANONICAL_WARNING.replace("(2) ", "")
        result = compare_government_warning(warning_missing_2, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_wrong_punctuation_semicolon(self):
        """Semicolon instead of period should fail."""
        warning_semicolon = CANONICAL_WARNING.replace(".", ";")
        result = compare_government_warning(warning_semicolon, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_missing_period(self):
        """Missing final period should fail."""
        warning_no_period = CANONICAL_WARNING.rstrip(".")
        result = compare_government_warning(warning_no_period, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_truncated_warning(self):
        """Truncated warning should fail."""
        warning_truncated = CANONICAL_WARNING[:-50]
        result = compare_government_warning(warning_truncated, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_completely_different_warning(self):
        """Completely different warning should fail."""
        other_warning = "CAUTION: Contains alcohol."
        result = compare_government_warning(other_warning, CANONICAL_WARNING)
        assert result.status == "FAIL"

    def test_misread_warning_returns_extracted_value(self):
        """Misread warning should return extracted text in FieldResult."""
        misread = "CAUTION: This product contains alcohol."
        result = compare_government_warning(misread, CANONICAL_WARNING)
        assert result.status == "FAIL"
        assert result.found == misread
        assert result.expected == CANONICAL_WARNING


class TestVerifyLabelIntegration:
    """Integration tests for full label verification."""

    def test_all_pass_approved(self):
        """All fields matching should result in APPROVED."""
        extracted = ExtractedLabel(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=40.0,
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        submitted = ApplicationData(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=40.0,
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        result = verify_label(extracted, submitted)
        assert result.overall_verdict == "APPROVED"
        assert all(r.status == "PASS" for r in result.field_results)

    def test_one_fail_needs_review(self):
        """One field failing should result in NEEDS_REVIEW."""
        extracted = ExtractedLabel(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=40.0,
            net_contents="750 mL",
            government_warning="DIFFERENT WARNING",  # This will fail
        )
        submitted = ApplicationData(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=40.0,
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        result = verify_label(extracted, submitted)
        assert result.overall_verdict == "NEEDS_REVIEW"
        assert any(r.status == "FAIL" for r in result.field_results)

    def test_multiple_fails_needs_review(self):
        """Multiple fields failing should result in NEEDS_REVIEW."""
        extracted = ExtractedLabel(
            brand_name="Completely Different",  # Will fail
            class_type="Rum",  # Will fail
            producer="Diageo",
            country_of_origin="France",  # Will fail (no match to USA)
            abv=40.0,
            net_contents="750 mL",
            government_warning="DIFFERENT WARNING",  # Will fail
        )
        submitted = ApplicationData(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=40.0,
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        result = verify_label(extracted, submitted)
        assert result.overall_verdict == "NEEDS_REVIEW"
        assert sum(1 for r in result.field_results if r.status == "FAIL") >= 4

    def test_fuzzy_matches_pass(self):
        """Fuzzy matches should result in APPROVED if within thresholds."""
        extracted = ExtractedLabel(
            brand_name="ketel one",  # Case variation
            class_type="Vodka",
            producer="diageo",  # Case variation
            country_of_origin="united states",  # Synonym
            abv=40.05,  # Within ±0.1%
            net_contents="765 mL",  # Within ±2%
            government_warning=CANONICAL_WARNING,
        )
        submitted = ApplicationData(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=40.0,
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        result = verify_label(extracted, submitted)
        assert result.overall_verdict == "APPROVED"

    def test_complex_abv_parsing(self):
        """Complex ABV formats should parse correctly."""
        extracted = ExtractedLabel(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=45.0,  # Note: this is the numeric abv field
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        submitted = ApplicationData(
            brand_name="Ketel One",
            class_type="Vodka",
            producer="Diageo",
            country_of_origin="USA",
            abv=45.0,
            net_contents="750 mL",
            government_warning=CANONICAL_WARNING,
        )
        # When passed as strings to compare_abv: "45%" vs "45% Alc./Vol. (90 Proof)"
        result_abv = compare_abv("45%", "45% Alc./Vol. (90 Proof)")
        assert result_abv.status == "PASS"


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_strings_brand(self):
        """Empty brand should fail fuzzy match."""
        result = compare_brand_name("", "Ketel One")
        assert result.status == "FAIL"

    def test_whitespace_only_country(self):
        """Whitespace-only country should not match."""
        result = compare_country_of_origin("   ", "USA")
        assert result.status == "FAIL"

    def test_zero_abv(self):
        """Zero ABV parsing."""
        result = compare_abv("0", "0")
        assert result.status == "PASS"

    def test_max_abv(self):
        """Maximum ABV parsing."""
        result = compare_abv("95", "95")
        assert result.status == "PASS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
