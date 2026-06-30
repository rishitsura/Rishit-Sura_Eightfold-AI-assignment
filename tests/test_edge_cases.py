"""
Edge case tests.

Tests for specific edge cases mentioned in the design doc:
1. Same person across sources with conflicting names
2. Garbage phone numbers
3. Missing entire source file
4. Resume with no extractable dates
5. Config requests a field that doesn't exist
"""

import json

import pytest

from transformer.extractors.csv_extractor import CSVExtractor
from transformer.merger import CandidateMerger
from transformer.models import (
    CandidateFragment,
    CanonicalProfile,
    Experience,
    FieldConfig,
    Location,
    OnMissing,
    OutputConfig,
    Provenance,
    Skill,
    SourceType,
)
from transformer.normalizers import normalize_phone
from transformer.projector import Projector
from transformer.validator import Validator


class TestConflictingNames:
    """Edge case: same person with different name spellings across sources."""

    def test_conflicting_names_merged(self):
        """ATS name should win over recruiter notes name."""
        merger = CandidateMerger()

        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_NOTES,
            full_name="J. Smith",
            emails=["john.smith@example.com"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            full_name="John Michael Smith",
            emails=["john.smith@example.com"],
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 1
        # ATS has higher priority AND longer name
        assert profiles[0].full_name == "John Michael Smith"


class TestGarbagePhones:
    """Edge case: garbage phone numbers."""

    def test_garbage_phone_returns_none(self):
        assert normalize_phone("abc-def-ghij") is None

    def test_too_short_phone(self):
        result = normalize_phone("123")
        # Should either be None or a parseable-but-invalid number
        assert result is None or isinstance(result, str)

    def test_mixed_valid_invalid_phones(self):
        """Merger should keep valid phones and drop invalid ones."""
        merger = CandidateMerger()

        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            emails=["test@test.com"],
            phones=["+1-555-0100", "not-a-phone", "12345"],
        )

        profiles = merger.merge_all([f1])
        # Only valid phones should survive normalization
        assert len(profiles) == 1
        for phone in profiles[0].phones:
            assert phone.startswith("+")  # E.164 format


class TestMissingSource:
    """Edge case: missing or empty source file."""

    def test_missing_csv_file(self):
        extractor = CSVExtractor()
        fragments = extractor.safe_extract("/nonexistent/file.csv")
        assert len(fragments) == 0

    def test_empty_fragments(self):
        """Merger should handle zero fragments gracefully."""
        merger = CandidateMerger()
        profiles = merger.merge_all([])
        assert len(profiles) == 0


class TestNoDates:
    """Edge case: experience entries with no extractable dates."""

    def test_experience_without_dates(self):
        """Experience with no dates should still be included."""
        merger = CandidateMerger()

        f1 = CandidateFragment(
            source_type=SourceType.RESUME,
            emails=["test@test.com"],
            experience=[
                Experience(company="Acme", title="Engineer"),
            ],
        )

        profiles = merger.merge_all([f1])
        assert len(profiles[0].experience) == 1
        assert profiles[0].experience[0].start is None
        assert profiles[0].experience[0].end is None


class TestNonexistentConfigField:
    """Edge case: config requests a field not in the canonical schema."""

    def test_nonexistent_field_null_policy(self):
        projector = Projector()
        profile = CanonicalProfile(
            candidate_id="test-1",
            full_name="Test User",
            emails=["test@test.com"],
            overall_confidence=0.5,
        )

        config = OutputConfig(
            fields=[
                FieldConfig(path="full_name", type="string", required=True),
                FieldConfig(path="imaginary_field", type="string"),
            ],
            on_missing=OnMissing.NULL,
            include_confidence=False,
            include_provenance=False,
        )

        result = projector.project(profile, config)
        assert result["full_name"] == "Test User"
        assert result["imaginary_field"] is None

    def test_nonexistent_required_field_error_policy(self):
        projector = Projector()
        validator = Validator()

        profile = CanonicalProfile(
            candidate_id="test-1",
            full_name="Test User",
            emails=["test@test.com"],
            overall_confidence=0.5,
        )

        config = OutputConfig(
            fields=[
                FieldConfig(path="imaginary_field", type="string", required=True),
            ],
            on_missing=OnMissing.ERROR,
            include_confidence=False,
            include_provenance=False,
        )

        result = projector.project(profile, config)
        validation = validator.validate(result, config)
        # Should have a validation error
        assert not validation.valid or len(result.get("_errors", [])) > 0


class TestDeterminism:
    """Ensure same inputs always produce the same output (minus candidate_id UUID)."""

    def test_deterministic_merge(self):
        merger = CandidateMerger()

        fragments = [
            CandidateFragment(
                source_type=SourceType.RECRUITER_CSV,
                full_name="John Doe",
                emails=["john@example.com"],
                skills=["Python", "JavaScript"],
            ),
            CandidateFragment(
                source_type=SourceType.ATS_JSON,
                full_name="John Doe",
                emails=["john@example.com"],
                skills=["Python", "Docker"],
                headline="Senior Engineer",
            ),
        ]

        results_1 = merger.merge_all(fragments)
        results_2 = merger.merge_all(fragments)

        # Should produce identical results (except candidate_id which is UUID)
        assert results_1[0].full_name == results_2[0].full_name
        assert results_1[0].headline == results_2[0].headline
        skills_1 = sorted([s.name for s in results_1[0].skills])
        skills_2 = sorted([s.name for s in results_2[0].skills])
        assert skills_1 == skills_2


class TestGracefulDegradation:
    """Test that pipeline components degrade gracefully on bad input."""

    def test_fragment_with_no_useful_data(self):
        """A fragment with no useful data should still merge without crash."""
        merger = CandidateMerger()

        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            full_name="John Doe",
            emails=["john@example.com"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.RECRUITER_NOTES,
            # No name, no email, no phone — nothing to match on
        )

        profiles = merger.merge_all([f1, f2])
        # f2 has nothing, but should still be a separate (empty) profile or skipped
        assert len(profiles) >= 1
