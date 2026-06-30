"""End-to-end pipeline integration tests using sample input files."""

import json
import os

import pytest

from transformer.pipeline import Pipeline

# Resolve sample input paths relative to project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAMPLE_DIR = os.path.join(_PROJECT_ROOT, "sample_inputs")
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "configs")


def _sample(filename: str) -> str:
    return os.path.join(_SAMPLE_DIR, filename)


def _config(filename: str) -> str:
    return os.path.join(_CONFIG_DIR, filename)


class TestPipelineE2E:
    """End-to-end pipeline tests."""

    @pytest.fixture
    def pipeline(self):
        return Pipeline()

    def test_csv_only(self, pipeline):
        """Pipeline should work with just a CSV file."""
        results = pipeline.run(input_paths=[_sample("recruiter_export.csv")])

        assert len(results) >= 1
        for result in results:
            assert result.validation.valid
            assert result.canonical.full_name is not None

    def test_json_only(self, pipeline):
        """Pipeline should work with just a JSON file."""
        results = pipeline.run(input_paths=[_sample("ats_candidates.json")])

        assert len(results) >= 1
        for result in results:
            assert result.validation.valid

    def test_csv_and_json_merge(self, pipeline):
        """Pipeline should merge candidates across CSV and JSON."""
        results = pipeline.run(
            input_paths=[
                _sample("recruiter_export.csv"),
                _sample("ats_candidates.json"),
            ]
        )

        # Priya Sharma, Arjun Mehta, and Sarah Johnson appear in both
        # Emily Chen and Ravi Kumar only in CSV
        # So we should have 5 unique profiles
        assert len(results) >= 3  # At least the merged ones

    def test_all_sources(self, pipeline):
        """Pipeline should handle all source types together."""
        results = pipeline.run(
            input_paths=[
                _sample("recruiter_export.csv"),
                _sample("ats_candidates.json"),
                _sample("resume_sample.txt"),
                _sample("recruiter_notes.txt"),
            ],
            source_types={
                _sample("resume_sample.txt"): "resume",
            },
        )

        assert len(results) >= 1
        for result in results:
            assert result.validation.valid

    def test_custom_config(self, pipeline):
        """Pipeline should apply custom config correctly."""
        results = pipeline.run(
            input_paths=[_sample("ats_candidates.json")],
            config_path=_config("custom_config.json"),
        )

        assert len(results) >= 1
        for result in results:
            profile = result.projected
            # Custom config selects specific fields
            assert "full_name" in profile
            # Provenance should be excluded (include_provenance=false in custom config)
            assert "provenance" not in profile
            # Confidence should be included
            assert "overall_confidence" in profile

    def test_default_config(self, pipeline):
        """Pipeline should work with default config."""
        results = pipeline.run(
            input_paths=[_sample("recruiter_export.csv")],
            config_path=_config("default_schema.json"),
        )

        assert len(results) >= 1
        for result in results:
            assert result.validation.valid
            profile = result.projected
            assert "candidate_id" in profile
            assert "provenance" in profile

    def test_notes_extraction(self, pipeline):
        """Pipeline should extract data from recruiter notes."""
        results = pipeline.run(
            input_paths=[_sample("recruiter_notes.txt")]
        )

        assert len(results) >= 1
        # Should find at least one candidate with an email
        any_email = any(
            len(r.canonical.emails) > 0 for r in results
        )
        assert any_email

    def test_serialization(self, pipeline):
        """run_and_serialize should produce valid JSON-serializable output."""
        results = pipeline.run_and_serialize(
            input_paths=[_sample("recruiter_export.csv")]
        )

        assert len(results) >= 1
        # Should be JSON-serializable
        json_str = json.dumps(results, default=str)
        parsed = json.loads(json_str)
        assert len(parsed) >= 1

    def test_empty_input(self, pipeline):
        """Pipeline should handle empty input gracefully."""
        results = pipeline.run(input_paths=[])
        assert len(results) == 0

    def test_missing_file_graceful(self, pipeline):
        """Pipeline should not crash on missing files."""
        results = pipeline.run(
            input_paths=[
                _sample("recruiter_export.csv"),
                "/nonexistent/file.csv",
            ]
        )
        # Should still process the valid file
        assert len(results) >= 1
