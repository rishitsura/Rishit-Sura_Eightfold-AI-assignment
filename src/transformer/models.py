"""
Pydantic models for the candidate data transformer.

Defines all data structures used throughout the pipeline:
- CandidateFragment: partial data extracted from a single source
- CanonicalProfile: the merged, complete profile
- OutputConfig: runtime configuration for output projection
- ValidationResult: structured validation feedback
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """Recognized source types."""
    RECRUITER_CSV = "recruiter_csv"
    ATS_JSON = "ats_json"
    GITHUB = "github"
    RESUME = "resume"
    RECRUITER_NOTES = "recruiter_notes"
    UNKNOWN = "unknown"


class OnMissing(str, Enum):
    """Policy when a required value is absent from the canonical record."""
    NULL = "null"
    OMIT = "omit"
    ERROR = "error"


class NormalizeType(str, Enum):
    """Supported per-field normalization types."""
    E164 = "E164"
    CANONICAL = "canonical"
    ISO_DATE = "iso_date"
    ISO_COUNTRY = "iso_country"
    LOWERCASE = "lowercase"
    TITLECASE = "titlecase"


# ---------------------------------------------------------------------------
# Source reliability weights (used in merge & confidence scoring)
# ---------------------------------------------------------------------------

SOURCE_RELIABILITY: dict[SourceType, float] = {
    SourceType.ATS_JSON: 0.90,
    SourceType.RECRUITER_CSV: 0.85,
    SourceType.RESUME: 0.80,
    SourceType.GITHUB: 0.75,
    SourceType.RECRUITER_NOTES: 0.60,
    SourceType.UNKNOWN: 0.30,
}

# Priority ordering for scalar conflict resolution (highest priority first)
SOURCE_PRIORITY: list[SourceType] = [
    SourceType.ATS_JSON,
    SourceType.RECRUITER_CSV,
    SourceType.RESUME,
    SourceType.GITHUB,
    SourceType.RECRUITER_NOTES,
]


# ---------------------------------------------------------------------------
# Sub-models (shared between Fragment and Canonical)
# ---------------------------------------------------------------------------

class Location(BaseModel):
    """Geographic location."""
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2 after normalization


class Links(BaseModel):
    """Profile links."""
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    """A skill with confidence and provenance."""
    name: str
    confidence: float = 0.0
    sources: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    """Work experience entry."""
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None  # YYYY-MM
    end: Optional[str] = None    # YYYY-MM or null for current
    summary: Optional[str] = None


class Education(BaseModel):
    """Education entry."""
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


class Provenance(BaseModel):
    """Tracks where a field value came from."""
    field: str
    source: str  # SourceType value or filename
    method: str  # e.g. "direct_mapping", "regex_extraction", "api_fetch", "fuzzy_merge"


# ---------------------------------------------------------------------------
# CandidateFragment — partial data from a single source
# ---------------------------------------------------------------------------

class CandidateFragment(BaseModel):
    """
    A partial candidate record extracted from a single source.
    All fields are optional since any source may only provide a subset.
    """
    source_type: SourceType
    source_file: str = ""  # filename or URL

    full_name: Optional[str] = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list[str] = Field(default_factory=list)  # raw skill names before normalization
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)

    # Any extra data the extractor captured but doesn't fit the schema
    raw_extras: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# CanonicalProfile — the merged, fully-normalized output
# ---------------------------------------------------------------------------

class CanonicalProfile(BaseModel):
    """
    The single, canonical candidate profile produced by merging all fragments.
    This is the internal representation; the Projector transforms it into
    the requested output shape.
    """
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    full_name: Optional[str] = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list[Skill] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    overall_confidence: float = 0.0


# ---------------------------------------------------------------------------
# Output configuration models
# ---------------------------------------------------------------------------

class FieldConfig(BaseModel):
    """Configuration for a single output field."""
    path: str                                    # output field name
    from_path: Optional[str] = Field(None, alias="from")  # canonical source path
    type: str = "string"                         # expected type
    required: bool = False
    normalize: Optional[str] = None              # normalization to apply

    model_config = {"populate_by_name": True}


class OutputConfig(BaseModel):
    """Runtime output configuration."""
    fields: list[FieldConfig] = Field(default_factory=list)
    include_confidence: bool = True
    include_provenance: bool = True
    on_missing: OnMissing = OnMissing.NULL


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationError(BaseModel):
    """A single validation issue."""
    field: str
    message: str
    severity: str = "error"  # "error" or "warning"


class ValidationResult(BaseModel):
    """Result of validating the projected output."""
    valid: bool
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[ValidationError] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline result wrapper
# ---------------------------------------------------------------------------

class PipelineResult(BaseModel):
    """Complete result of a pipeline run."""
    canonical: CanonicalProfile
    projected: dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult = Field(
        default_factory=lambda: ValidationResult(valid=True)
    )
    warnings: list[str] = Field(default_factory=list)
