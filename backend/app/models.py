"""
Phase 1: Pydantic models for TTB label verification.
Pure data structures with no logic.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ApplicationData(BaseModel):
    """User-submitted ground truth for TTB label."""
    brand_name: str = Field(..., min_length=1, description="Brand name (e.g., Ketel One)")
    class_type: str = Field(..., min_length=1, description="Spirit class (e.g., Vodka, Whiskey)")
    producer: str = Field(..., min_length=1, description="Producer/distillery name")
    country_of_origin: str = Field(..., min_length=1, description="Country (e.g., USA, United States, NL)")
    abv: float = Field(..., ge=0, le=100, description="Alcohol by volume (0-100)")
    net_contents: str = Field(..., min_length=1, description="Bottle size (e.g., '750 mL', '1.75L')")
    government_warning: str = Field(..., min_length=1, description="Exact TTB government warning text")


class ExtractedLabel(BaseModel):
    """Vision model output. Fields may be null if missing/unreadable."""
    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    producer: Optional[str] = None
    country_of_origin: Optional[str] = None
    abv: Optional[float] = Field(default=None, ge=0, le=100)
    net_contents: Optional[str] = None
    government_warning: Optional[str] = None


class FieldResult(BaseModel):
    """Result of comparing one field."""
    field_name: str
    status: Literal["PASS", "FAIL"]
    extracted_value: str
    submitted_value: str
    reason: str


class VerificationResult(BaseModel):
    """Final aggregated verification result."""
    overall_verdict: Literal["APPROVED", "NEEDS_REVIEW"]
    field_results: list[FieldResult]
    timestamp: datetime


class BatchItemResult(BaseModel):
    """Result for one item in a batch request."""
    index: int
    filename: str
    verification: VerificationResult | None = None
    match: Literal["passed", "needs-review", "error"]
    confidence: float | None = None
    errors: Optional[list[str]] = None
    duration_ms: float


class BatchResponse(BaseModel):
    total: int
    passed: int
    needs_review: int
    errors: int
    results: list[BatchItemResult]
