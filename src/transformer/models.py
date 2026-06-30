"""
Pydantic models for the candidate data transformer.

Defines all data structures used throughout the pipeline:
- CandidateFragment: partial data extracted from a single source
- CanonicalProfile: the merged, complete profile
- ConflictFlag / MergeDecision: conflict detection and lineage audit log
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


class SkillStatus(str, Enum):
    """
    Temporal classification of a skill based on which sources mention it.

    CONFIRMED  — present in Resume AND at least one other source.
                 Highest confidence: candidate claims it and external data agrees.
    CURRENT    — present in Resume only.
                 Candidate is actively pitching this skill right now.
    HISTORICAL — present in non-resume sources only (e.g. ATS from a past application).
                 Candidate has omitted it from their current resume — may have moved on.
    """
    CONFIRMED  = "confirmed"
    CURRENT    = "current"
    HISTORICAL = "historical"


class ConflictSeverity(str, Enum):
    """
    How serious a cross-source disagreement is on a given field.

    Severity is determined by the divergence score between source values:
      NONE   — only one source provided a value (no comparison possible)
      LOW    — sources differ but are close (divergence < 0.30)
      MEDIUM — sources differ meaningfully  (divergence 0.30–0.60)
      HIGH   — sources fundamentally contradict each other (divergence ≥ 0.60)
    """
    NONE   = "none"
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


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
    """
    A normalized skill with confidence, provenance, and temporal status.

    The `status` field classifies the skill by how current it is based on
    which sources mention it (see SkillStatus for full semantics).
    The `confidence` field starts from source reliability and is adjusted
    downward for HISTORICAL skills and by conflict penalties.
    """
    name: str
    confidence: float = 0.0
    sources: list[str] = Field(default_factory=list)
    status: SkillStatus = SkillStatus.CURRENT  # temporal classification


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


class ConflictFlag(BaseModel):
    """
    Records a detected disagreement between two or more sources on a single field.

    Generated by ConflictAnalyzer before merging. The `penalty` value (0.0–1.0)
    is fed into ConfidenceScorer to reduce the overall_confidence of the profile
    proportionally to how much reliable sources contradict each other.

    Example:
      ATS says skills=["Java", "COBOL"], Resume says skills=["Python", "Go"].
      Jaccard overlap = 0.0 → divergence = 1.0 → severity = HIGH → penalty = 0.90.
    """
    field:    str                 # canonical field name, e.g. "skills" or "experience[0].company"
    severity: ConflictSeverity
    sources:  list[str]          # which SourceType values disagree
    values:   list[str]          # what each source said (parallel list with sources)
    detail:   str                # human-readable explanation
    penalty:  float              # confidence reduction: 0.0 = no penalty, 1.0 = zero confidence


class MergeDecision(BaseModel):
    """
    Audit log entry for a single field merge decision.

    Records which source value was chosen (winner) and what all other
    sources said (losers). This is the lineage record that makes the
    merge fully auditable — no information is silently discarded.

    Example:
      field = "full_name"
      winner = {"value": "John Smith", "source": "ats_json", "reliability": 0.90}
      losers = [{"value": "Jon Smith", "source": "resume", "reliability": 0.80}]
    """
    field:            str
    winner:           dict[str, Any]   # {"value", "source", "reliability"}
    losers:           list[dict[str, Any]]  # same structure, one per discarded source
    conflict_penalty: float = 0.0


class ConflictReport(BaseModel):
    """
    Output of a single ConflictAnalyzer.analyze() call for one candidate group.

    Contains all conflict flags (for confidence scoring) and all merge decisions
    (for the lineage audit log). Both are attached to CanonicalProfile after merging.
    """
    flags:           list[ConflictFlag]   = Field(default_factory=list)
    merge_decisions: list[MergeDecision] = Field(default_factory=list)
    skill_list:      list[Skill]          = Field(default_factory=list)


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

    New fields (CACS + Lineage):
      conflict_flags   — list of field-level conflicts detected pre-merge;
                         fed into ConfidenceScorer to penalize disagreeing sources.
      merge_decisions  — full audit log of every field merge decision;
                         records the winner value AND all discarded alternatives.
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
    # Conflict-Aware Confidence Scoring — populated by ConflictAnalyzer + merger
    conflict_flags:   list[ConflictFlag]   = Field(default_factory=list)
    merge_decisions:  list[MergeDecision]  = Field(default_factory=list)


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
