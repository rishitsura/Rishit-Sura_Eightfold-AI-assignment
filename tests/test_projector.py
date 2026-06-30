"""Tests for the output projector."""

import pytest

from transformer.models import (
    CanonicalProfile,
    FieldConfig,
    Links,
    Location,
    OnMissing,
    OutputConfig,
    Provenance,
    Skill,
)
from transformer.projector import Projector


@pytest.fixture
def projector():
    return Projector()


@pytest.fixture
def sample_profile():
    return CanonicalProfile(
        candidate_id="test-123",
        full_name="John Doe",
        emails=["john@example.com", "jdoe@work.com"],
        phones=["+15550100", "+15550200"],
        location=Location(city="San Francisco", region="CA", country="US"),
        links=Links(
            linkedin="https://linkedin.com/in/johndoe",
            github="https://github.com/johndoe",
        ),
        headline="Senior Software Engineer",
        years_experience=5.0,
        skills=[
            Skill(name="Python", confidence=0.9, sources=["ats_json", "resume"]),
            Skill(name="JavaScript", confidence=0.7, sources=["resume"]),
            Skill(name="Docker", confidence=0.5, sources=["recruiter_csv"]),
        ],
        provenance=[
            Provenance(field="full_name", source="ats_json", method="priority_merge"),
        ],
        overall_confidence=0.85,
    )


class TestFieldSelection:
    """Tests for field selection and remapping."""

    def test_select_subset(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="full_name", type="string"),
                FieldConfig(path="headline", type="string"),
            ],
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)

        assert "full_name" in result
        assert "headline" in result
        assert "emails" not in result
        assert "overall_confidence" not in result

    def test_field_remapping(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="primary_email", type="string", **{"from": "emails[0]"}),
            ],
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)

        assert result["primary_email"] == "john@example.com"

    def test_dot_path(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="city", type="string", **{"from": "location.city"}),
                FieldConfig(path="country", type="string", **{"from": "location.country"}),
            ],
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)

        assert result["city"] == "San Francisco"
        assert result["country"] == "US"

    def test_array_iteration(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="skill_names", type="string[]", **{"from": "skills[].name"}),
            ],
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)

        assert result["skill_names"] == ["Python", "JavaScript", "Docker"]


class TestMissingValues:
    """Tests for missing value policies."""

    def test_on_missing_null(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="nonexistent_field", type="string"),
            ],
            on_missing=OnMissing.NULL,
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)
        assert result["nonexistent_field"] is None

    def test_on_missing_omit(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="nonexistent_field", type="string"),
            ],
            on_missing=OnMissing.OMIT,
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)
        assert "nonexistent_field" not in result

    def test_on_missing_error(self, projector, sample_profile):
        config = OutputConfig(
            fields=[
                FieldConfig(path="nonexistent_field", type="string", required=True),
            ],
            on_missing=OnMissing.ERROR,
            include_confidence=False,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)
        assert "_errors" in result


class TestConfidenceProvenance:
    """Tests for confidence and provenance toggles."""

    def test_include_confidence(self, projector, sample_profile):
        config = OutputConfig(
            fields=[FieldConfig(path="full_name", type="string")],
            include_confidence=True,
            include_provenance=False,
        )
        result = projector.project(sample_profile, config)
        assert "overall_confidence" in result
        assert "provenance" not in result

    def test_include_provenance(self, projector, sample_profile):
        config = OutputConfig(
            fields=[FieldConfig(path="full_name", type="string")],
            include_confidence=False,
            include_provenance=True,
        )
        result = projector.project(sample_profile, config)
        assert "provenance" in result
        assert "overall_confidence" not in result


class TestFullProjection:
    """Tests for default full projection (no field config)."""

    def test_full_projection(self, projector, sample_profile):
        config = OutputConfig()
        result = projector.project(sample_profile, config)

        assert result["candidate_id"] == "test-123"
        assert result["full_name"] == "John Doe"
        assert len(result["emails"]) == 2
        assert result["overall_confidence"] == 0.85
        assert "provenance" in result
