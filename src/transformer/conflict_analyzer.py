"""
Conflict Analyzer.

Analyzes disagreement between CandidateFragments belonging to the same
person BEFORE the merger resolves any conflicts.

Key outputs:
  - ConflictFlag per field where sources meaningfully disagree
  - MergeDecision log recording every alternative value (lineage)
  - Temporal skill stratification: CONFIRMED / CURRENT / HISTORICAL

Design rationale
----------------
The standard confidence model rewards multi-source coverage but never asks
whether the sources *agree*. Two fragments where ATS says "Python, Go" and
Resume says "Java, COBOL" both contribute to a high confidence score even
though they fundamentally contradict each other.

This module runs a read-only pre-merge pass and produces:
  1. A ConflictReport with per-field ConflictFlags and their penalty values.
  2. A MergeDecision entry per field so no alternative value is ever silently
     discarded — full provenance from raw extraction to final output.

The ConflictReport is attached to the CanonicalProfile by the merger and
consumed by the ConfidenceScorer to apply field-level confidence penalties.

Severity thresholds
-------------------
  divergence < 0.30  → LOW    (minor wording diff, effectively same)
  divergence < 0.60  → MEDIUM (meaningful difference, worth flagging)
  divergence ≥ 0.60  → HIGH   (fundamental contradiction)

Skill temporal stratification
------------------------------
Resume is treated as the candidate's *intentional current pitch*. Skills
the candidate has omitted from their resume may indicate they have moved on,
even if an older ATS record lists them.

  in Resume + ≥1 other  → CONFIRMED  (confidence: 1.0)
  in Resume only         → CURRENT    (confidence: 0.85)
  not in Resume          → HISTORICAL (confidence: 0.45)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from rapidfuzz import fuzz

from transformer.models import (
    SOURCE_RELIABILITY,
    CandidateFragment,
    ConflictFlag,
    ConflictReport,
    ConflictSeverity,
    MergeDecision,
    Skill,
    SkillStatus,
    SourceType,
)
from transformer.normalizers import normalize_skill

logger = logging.getLogger(__name__)

# Confidence weights applied to skills by temporal status
_SKILL_STATUS_CONFIDENCE: dict[SkillStatus, float] = {
    SkillStatus.CONFIRMED:  1.00,
    SkillStatus.CURRENT:    0.85,
    SkillStatus.HISTORICAL: 0.45,
}

# Divergence thresholds that determine ConflictSeverity
_LOW_THRESHOLD    = 0.30
_MEDIUM_THRESHOLD = 0.60


def _severity(divergence: float) -> ConflictSeverity:
    """Map a divergence score [0, 1] to a ConflictSeverity level."""
    if divergence < _LOW_THRESHOLD:
        return ConflictSeverity.LOW
    if divergence < _MEDIUM_THRESHOLD:
        return ConflictSeverity.MEDIUM
    return ConflictSeverity.HIGH


def _source_reliability(source_type: SourceType) -> float:
    """Return the reliability weight for a source type."""
    return SOURCE_RELIABILITY.get(source_type, 0.30)


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """
    Jaccard similarity between two sets of strings.
    Returns 1.0 if both sets are empty (no information = no divergence).
    """
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


class ConflictAnalyzer:
    """
    Read-only pre-merge analysis of disagreement across CandidateFragments.

    Usage::

        report = ConflictAnalyzer().analyze(fragments)
        # report.flags          → list[ConflictFlag]
        # report.merge_decisions → list[MergeDecision]
        # report.skill_list      → list[Skill] with temporal status
    """

    def analyze(self, fragments: list[CandidateFragment]) -> ConflictReport:
        """
        Analyze a group of fragments that belong to the same candidate.

        Args:
            fragments: All CandidateFragments for one candidate (already grouped
                       by identity in the merger).

        Returns:
            A ConflictReport containing ConflictFlags (for confidence scoring)
            and MergeDecisions (for lineage logging).
        """
        if len(fragments) <= 1:
            # Single source — no comparison possible.
            # Still build skill list with CURRENT status for single-source candidates.
            report = ConflictReport()
            if fragments:
                report.skill_list = self._classify_skills(fragments)
            else:
                report.skill_list = []
            return report

        flags: list[ConflictFlag] = []
        decisions: list[MergeDecision] = []

        # ── Scalar field analysis ──────────────────────────────────────────
        flags += self._analyze_scalar(fragments, "full_name",
                                      lambda f: f.full_name, decisions)
        flags += self._analyze_scalar(fragments, "years_experience",
                                      lambda f: str(f.years_experience)
                                      if f.years_experience is not None else None,
                                      decisions)
        flags += self._analyze_location(fragments, decisions)

        # ── Experience company / title ─────────────────────────────────────
        flags += self._analyze_experience(fragments, decisions)

        # ── Skills (set-based Jaccard) ─────────────────────────────────────
        skill_flag, skill_list = self._analyze_skills(fragments)
        if skill_flag:
            flags.append(skill_flag)

        report = ConflictReport(flags=flags, merge_decisions=decisions)
        report.skill_list = skill_list  # type: ignore[attr-defined]  # dynamic field
        return report

    # ------------------------------------------------------------------
    # Scalar field analysis
    # ------------------------------------------------------------------

    def _analyze_scalar(
        self,
        fragments: list[CandidateFragment],
        field: str,
        getter,
        decisions: list[MergeDecision],
    ) -> list[ConflictFlag]:
        """
        Analyze a single scalar field across all fragments.

        Uses fuzzy string ratio to measure divergence between each pair
        of source values. Only fragments that actually provide a value are
        considered (None is treated as absent, not conflicting).
        """
        valued: list[tuple[str, SourceType, float]] = []  # (value, source, reliability)
        for frag in fragments:
            val = getter(frag)
            if val and str(val).strip():
                valued.append((
                    str(val).strip(),
                    frag.source_type,
                    _source_reliability(frag.source_type),
                ))

        if len(valued) < 2:
            return []

        # Find maximum divergence across all pairs
        max_divergence = 0.0
        diverging_pair: tuple | None = None

        for i in range(len(valued)):
            for j in range(i + 1, len(valued)):
                val_a, src_a, _ = valued[i]
                val_b, src_b, _ = valued[j]
                ratio = fuzz.ratio(val_a.lower(), val_b.lower())
                divergence = 1.0 - (ratio / 100.0)
                if divergence > max_divergence:
                    max_divergence = divergence
                    diverging_pair = (valued[i], valued[j])

        severity = _severity(max_divergence)

        # Identify the winner (highest priority = first in valued list after
        # sorting by reliability descending — mirrors merger's priority logic)
        valued_sorted = sorted(valued, key=lambda x: x[2], reverse=True)
        winner_val, winner_src, winner_rel = valued_sorted[0]
        losers = [
            {"value": v, "source": s.value, "reliability": r}
            for v, s, r in valued_sorted[1:]
        ]

        # Always log the merge decision (lineage), even for LOW conflicts
        decisions.append(MergeDecision(
            field=field,
            winner={"value": winner_val, "source": winner_src.value, "reliability": winner_rel},
            losers=losers,
            conflict_penalty=max_divergence * max(r for _, _, r in valued),
        ))

        if severity == ConflictSeverity.LOW:
            # Log but don't emit a ConflictFlag for low-severity (minor wording diffs)
            logger.debug(
                "Low-severity conflict on '%s': divergence=%.2f (sources: %s)",
                field, max_divergence, [s.value for _, s, _ in valued],
            )
            return []

        assert diverging_pair is not None
        (va, sa, _), (vb, sb, _) = diverging_pair
        penalty = max_divergence * max(r for _, _, r in valued)

        flag = ConflictFlag(
            field=field,
            severity=severity,
            sources=[sa.value, sb.value],
            values=[va, vb],
            detail=(
                f"{severity.value.upper()} conflict on '{field}': "
                f"{sa.value}={va!r} vs {sb.value}={vb!r} "
                f"(divergence={max_divergence:.0%}, penalty={penalty:.2f})"
            ),
            penalty=round(penalty, 3),
        )
        logger.info("Conflict detected: %s", flag.detail)
        return [flag]

    # ------------------------------------------------------------------
    # Location analysis (struct comparison)
    # ------------------------------------------------------------------

    def _analyze_location(
        self,
        fragments: list[CandidateFragment],
        decisions: list[MergeDecision],
    ) -> list[ConflictFlag]:
        """Analyze location as a compound scalar (city + country concatenated)."""
        valued: list[tuple[str, SourceType, float]] = []
        for frag in fragments:
            if frag.location:
                parts = [frag.location.city, frag.location.country]
                loc_str = ", ".join(p for p in parts if p)
                if loc_str:
                    valued.append((loc_str, frag.source_type,
                                   _source_reliability(frag.source_type)))

        if len(valued) < 2:
            return []

        # Reuse scalar logic by building a fake single-field structure
        class _FakeFragment:
            def __init__(self, val, src, rel):
                self._val = val
                self.source_type = src

        fake_fragments = [_FakeFragment(v, s, r) for v, s, r in valued]
        return self._analyze_scalar(
            fake_fragments, "location",  # type: ignore[arg-type]
            lambda f: f._val,
            decisions,
        )

    # ------------------------------------------------------------------
    # Experience analysis
    # ------------------------------------------------------------------

    def _analyze_experience(
        self,
        fragments: list[CandidateFragment],
        decisions: list[MergeDecision],
    ) -> list[ConflictFlag]:
        """
        Analyze experience[0].company and experience[0].title across sources.

        Only compares the first (most recent) experience entry since that's the
        most likely to be provided by all sources and the most sensitive to
        data quality issues.
        """
        flags: list[ConflictFlag] = []

        class _FakeFragment:
            def __init__(self, val, src):
                self._val = val
                self.source_type = src

        for sub_field in ("company", "title"):
            valued_frags = []
            for frag in fragments:
                if frag.experience:
                    val = getattr(frag.experience[0], sub_field, None)
                    if val:
                        valued_frags.append(_FakeFragment(val, frag.source_type))

            if len(valued_frags) >= 2:
                flags += self._analyze_scalar(
                    valued_frags,  # type: ignore[arg-type]
                    f"experience[0].{sub_field}",
                    lambda f: f._val,
                    decisions,
                )

        return flags

    # ------------------------------------------------------------------
    # Skill analysis (set-based + temporal stratification)
    # ------------------------------------------------------------------

    def _analyze_skills(
        self,
        fragments: list[CandidateFragment],
    ) -> tuple[ConflictFlag | None, list[Skill]]:
        """
        Analyze skills using Jaccard similarity and classify each skill
        by temporal status (CONFIRMED / CURRENT / HISTORICAL).

        Returns a tuple of:
          - ConflictFlag (or None if severity is LOW or there's no conflict)
          - list[Skill] with status and initial confidence already set
        """
        # Collect per-source canonical skill sets
        source_skills: dict[SourceType, set[str]] = {}
        for frag in fragments:
            if frag.skills:
                canonical = {normalize_skill(s) for s in frag.skills if s.strip()}
                if canonical:
                    source_skills[frag.source_type] = canonical

        if not source_skills:
            return None, []

        # ── Jaccard conflict analysis across all source pairs ──────────
        max_divergence = 0.0
        diverging_sources: list[tuple[SourceType, SourceType]] = []

        source_list = list(source_skills.items())
        for i in range(len(source_list)):
            for j in range(i + 1, len(source_list)):
                src_a, skills_a = source_list[i]
                src_b, skills_b = source_list[j]
                overlap = _jaccard(skills_a, skills_b)
                divergence = 1.0 - overlap
                if divergence > max_divergence:
                    max_divergence = divergence
                    diverging_sources = [(src_a, src_b)]

        severity = _severity(max_divergence)

        # ── Temporal stratification ────────────────────────────────────
        skill_list = self._classify_skills(fragments, source_skills)

        # ── Build ConflictFlag if severity is MEDIUM or HIGH ───────────
        flag: ConflictFlag | None = None
        if severity in (ConflictSeverity.MEDIUM, ConflictSeverity.HIGH) and diverging_sources:
            src_a, src_b = diverging_sources[0]
            skills_a = source_skills[src_a]
            skills_b = source_skills[src_b]
            overlap_pct = int((1.0 - max_divergence) * 100)

            penalty = max_divergence * max(
                _source_reliability(s) for s in source_skills
            )

            # Distinguish temporal drift from true conflict
            has_resume = SourceType.RESUME in source_skills
            if has_resume and len(source_skills) > 1:
                detail_suffix = (
                    "likely temporal drift — candidate may have moved on from some skills"
                )
            else:
                detail_suffix = "possible identity mismatch or stale data"

            flag = ConflictFlag(
                field="skills",
                severity=severity,
                sources=[src_a.value, src_b.value],
                values=[
                    ", ".join(sorted(skills_a)),
                    ", ".join(sorted(skills_b)),
                ],
                detail=(
                    f"{severity.value.upper()} conflict on 'skills': "
                    f"{overlap_pct}% overlap between {src_a.value} and {src_b.value} — "
                    f"{detail_suffix} "
                    f"(divergence={max_divergence:.0%}, penalty={penalty:.2f})"
                ),
                penalty=round(penalty, 3),
            )
            logger.info("Skill conflict: %s", flag.detail)

        return flag, skill_list

    def _classify_skills(
        self,
        fragments: list[CandidateFragment],
        source_skills: dict[SourceType, set[str]] | None = None,
    ) -> list[Skill]:
        """
        Build the final list[Skill] with temporal status and initial confidence.

        Classification rules:
          CONFIRMED  — skill appears in Resume AND ≥1 other source
          CURRENT    — skill appears in Resume only
          HISTORICAL — skill does NOT appear in Resume (older sources only)

        If no Resume fragment is present, all skills are treated as CURRENT
        since there's no intentional omission signal.
        """
        if source_skills is None:
            source_skills = {}
            for frag in fragments:
                if frag.skills:
                    canonical = {normalize_skill(s) for s in frag.skills if s.strip()}
                    if canonical:
                        source_skills[frag.source_type] = canonical

        if not source_skills:
            return []

        resume_skills = source_skills.get(SourceType.RESUME, set())
        has_resume = bool(resume_skills)

        # Build union with per-skill source tracking
        all_skills: dict[str, list[SourceType]] = defaultdict(list)
        for src, skills in source_skills.items():
            for skill in skills:
                all_skills[skill].append(src)

        result: list[Skill] = []
        for skill_name, contributing_sources in sorted(all_skills.items()):
            in_resume = skill_name in resume_skills
            source_count = len(contributing_sources)

            if not has_resume:
                # No resume available — treat everything as current
                status = SkillStatus.CURRENT
            elif in_resume and source_count > 1:
                status = SkillStatus.CONFIRMED
            elif in_resume:
                status = SkillStatus.CURRENT
            else:
                status = SkillStatus.HISTORICAL

            base_confidence = _SKILL_STATUS_CONFIDENCE[status]

            result.append(Skill(
                name=skill_name,
                confidence=round(base_confidence, 2),
                sources=[s.value for s in contributing_sources],
                status=status,
            ))

        return result
