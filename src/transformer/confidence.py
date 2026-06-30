"""
Confidence scoring.

Assigns an overall confidence score to a CanonicalProfile based on:
- How many sources contributed data
- Source reliability weights
- Per-field coverage (how many fields are populated)
- Cross-source agreement (multiple sources confirming the same value)
"""

from __future__ import annotations

import logging

from transformer.models import (
    SOURCE_RELIABILITY,
    CanonicalProfile,
    Provenance,
    SourceType,
)

logger = logging.getLogger(__name__)

# Field importance weights for overall confidence calculation
_FIELD_WEIGHTS: dict[str, float] = {
    "full_name": 1.0,
    "emails": 0.9,
    "phones": 0.7,
    "location": 0.5,
    "headline": 0.4,
    "skills": 0.8,
    "experience": 0.9,
    "education": 0.6,
    "links": 0.3,
    "years_experience": 0.5,
}


def _field_populated(profile: CanonicalProfile, field: str) -> bool:
    """Check if a field on the profile has a non-null, non-empty value."""
    value = getattr(profile, field, None)
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _count_sources_for_field(
    provenance: list[Provenance], field: str
) -> tuple[int, set[str]]:
    """Count how many unique sources contributed to a field."""
    sources: set[str] = set()
    for p in provenance:
        if p.field == field:
            # Source may be comma-separated if from union
            for s in p.source.split(","):
                s = s.strip()
                if s and s != "all":
                    sources.add(s)
    return len(sources), sources


def _source_weight(source_str: str) -> float:
    """Get reliability weight for a source type string."""
    try:
        st = SourceType(source_str)
        return SOURCE_RELIABILITY.get(st, 0.5)
    except ValueError:
        return 0.5


class ConfidenceScorer:
    """Calculates confidence scores for canonical profiles."""

    def score(self, profile: CanonicalProfile) -> float:
        """
        Calculate the overall confidence for a profile.

        Returns a float in [0.0, 1.0].
        """
        if not profile.provenance:
            # No provenance at all — very low confidence
            return 0.1

        total_weight = 0.0
        weighted_score = 0.0

        for field, weight in _FIELD_WEIGHTS.items():
            if not _field_populated(profile, field):
                # Missing field contributes 0 to confidence
                total_weight += weight
                continue

            # Per-field confidence
            source_count, sources = _count_sources_for_field(
                profile.provenance, field
            )

            if source_count == 0:
                # Field is populated but no provenance (shouldn't happen, but handle it)
                field_confidence = 0.3
            else:
                # Base confidence from best source
                best_source_weight = max(
                    (_source_weight(s) for s in sources),
                    default=0.5,
                )

                # Agreement bonus: more sources = higher confidence
                agreement_bonus = min(source_count / 3.0, 1.0) * 0.2

                # Apply Conflict-Aware Confidence Scoring (CACS) penalty
                flag = next((f for f in profile.conflict_flags if f.field == field), None)
                conflict_penalty = flag.penalty if flag else 0.0

                field_confidence = min(best_source_weight + agreement_bonus, 1.0)
                field_confidence = field_confidence * (1.0 - conflict_penalty)

            weighted_score += weight * field_confidence
            total_weight += weight

        overall = weighted_score / max(total_weight, 0.01)

        # Additional boost if many fields are populated
        populated_count = sum(
            1 for f in _FIELD_WEIGHTS if _field_populated(profile, f)
        )
        coverage_ratio = populated_count / len(_FIELD_WEIGHTS)
        overall = overall * (0.7 + 0.3 * coverage_ratio)  # 70-100% of base score

        return round(min(max(overall, 0.0), 1.0), 2)

    def score_profiles(
        self, profiles: list[CanonicalProfile]
    ) -> list[CanonicalProfile]:
        """Score all profiles and update their overall_confidence field."""
        result: list[CanonicalProfile] = []
        for profile in profiles:
            confidence = self.score(profile)
            updated = profile.model_copy(update={"overall_confidence": confidence})
            result.append(updated)
            logger.debug(
                "Confidence for %s: %.2f",
                profile.full_name or profile.candidate_id,
                confidence,
            )
        return result
