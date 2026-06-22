"""
Phase 1: Pydantic models for TTB label verification.
Pure data structures with no logic.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApplicationData(BaseModel):
    """User-submitted ground truth for TTB label."""
    brand_name: str = Field(..., description="Brand name (e.g., Ketel One)")
    class_type: str = Field(..., description="Spirit class (e.g., Vodka, Whiskey)")
    producer: str = Field(..., description="Producer/distillery name")
    country_of_origin: str = Field(..., description="Country (e.g., USA, United States, NL)")
    abv: float = Field(..., ge=0, le=100, description="Alcohol by volume (0-100)")
    net_contents: str = Field(..., description="Bottle size (e.g., '750 mL', '1.75L')")
    government_warning: str = Field(..., description="Exact TTB government warning text")


class ExtractedLabel(BaseModel):
    """Vision model output (same structure as ApplicationData)."""
    brand_name: str
    class_type: str
    producer: str
    country_of_origin: str
    abv: float = Field(ge=0, le=100)
    net_contents: str
    government_warning: str


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
