"""Tests for the cross-source merger."""

import pytest

from transformer.merger import CandidateMerger
from transformer.models import (
    CandidateFragment,
    Education,
    Experience,
    Links,
    Location,
    SourceType,
)


@pytest.fixture
def merger():
    return CandidateMerger()


class TestFragmentGrouping:
    """Tests for identity matching and grouping."""

    def test_same_email_merges(self, merger):
        """Two fragments with the same email should merge into one profile."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            full_name="John Doe",
            emails=["john@example.com"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            full_name="John Doe",
            emails=["john@example.com"],
            headline="Senior Engineer",
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 1
        assert profiles[0].full_name == "John Doe"

    def test_different_emails_separate(self, merger):
        """Fragments with different emails and names should stay separate."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            full_name="John Doe",
            emails=["john@example.com"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            full_name="Jane Smith",
            emails=["jane@example.com"],
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 2

    def test_name_phone_match(self, merger):
        """Fragments matching on name+phone should merge."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            full_name="John Doe",
            phones=["+15550100"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.RESUME,
            full_name="John Doe",
            phones=["+15550100"],
            headline="Engineer",
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 1


class TestScalarMerge:
    """Tests for scalar field conflict resolution."""

    def test_priority_ordering(self, merger):
        """Higher-priority source should win for scalar fields."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_NOTES,
            full_name="J. Doe",
            emails=["john@example.com"],
            headline="Developer",
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            full_name="John Doe",
            emails=["john@example.com"],
            headline="Senior Software Engineer",
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 1
        # ATS has higher priority, and its headline is longer
        assert profiles[0].headline == "Senior Software Engineer"


class TestArrayMerge:
    """Tests for array field merging."""

    def test_email_union(self, merger):
        """Emails from all sources should be unioned and deduped."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            full_name="John Doe",
            emails=["john@example.com", "john.doe@work.com"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            full_name="John Doe",
            emails=["john@example.com", "jdoe@personal.com"],
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 1
        assert len(profiles[0].emails) == 3  # deduped union

    def test_skill_merge_with_canonical(self, merger):
        """Skills should be canonicalized and deduped across sources."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            emails=["test@test.com"],
            skills=["python", "JS", "react"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.RESUME,
            emails=["test@test.com"],
            skills=["Python", "JavaScript", "Docker"],
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles) == 1
        skill_names = [s.name for s in profiles[0].skills]
        assert "Python" in skill_names
        assert "JavaScript" in skill_names
        assert "React" in skill_names
        assert "Docker" in skill_names

    def test_skill_confidence(self, merger):
        """Skills from multiple sources should have higher confidence."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            emails=["test@test.com"],
            skills=["Python"],
        )
        f2 = CandidateFragment(
            source_type=SourceType.RESUME,
            emails=["test@test.com"],
            skills=["Python"],
        )

        profiles = merger.merge_all([f1, f2])
        python_skill = next(s for s in profiles[0].skills if s.name == "Python")
        assert python_skill.confidence > 0.5  # Multi-source = higher confidence


class TestExperienceMerge:
    """Tests for experience merging."""

    def test_dedup_same_entry(self, merger):
        """Duplicate experience entries should be deduped."""
        exp = Experience(company="Acme", title="Engineer", start="2020-01")
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            emails=["test@test.com"],
            experience=[exp],
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            emails=["test@test.com"],
            experience=[exp],
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles[0].experience) == 1

    def test_different_entries_kept(self, merger):
        """Different experience entries should all be kept."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            emails=["test@test.com"],
            experience=[Experience(company="Acme", title="Engineer")],
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            emails=["test@test.com"],
            experience=[Experience(company="BigCo", title="Senior Engineer")],
        )

        profiles = merger.merge_all([f1, f2])
        assert len(profiles[0].experience) == 2


class TestLocationMerge:
    """Tests for location merging."""

    def test_most_complete_wins(self, merger):
        """The most complete location should be selected."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            emails=["test@test.com"],
            location=Location(city="NYC"),
        )
        f2 = CandidateFragment(
            source_type=SourceType.ATS_JSON,
            emails=["test@test.com"],
            location=Location(city="New York", region="NY", country="US"),
        )

        profiles = merger.merge_all([f1, f2])
        loc = profiles[0].location
        assert loc is not None
        assert loc.city == "New York"
        assert loc.region == "NY"
        assert loc.country == "US"


class TestProvenance:
    """Tests for provenance tracking."""

    def test_provenance_recorded(self, merger):
        """Every merged field should have provenance."""
        f1 = CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            full_name="John Doe",
            emails=["john@example.com"],
            skills=["Python"],
        )

        profiles = merger.merge_all([f1])
        assert len(profiles[0].provenance) > 0

        prov_fields = {p.field for p in profiles[0].provenance}
        assert "full_name" in prov_fields
        assert "emails" in prov_fields
