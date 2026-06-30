"""
Pipeline orchestrator.

Runs the full transformation pipeline:
Detect → Parse/Extract → Normalize → Merge → Confidence → Project → Validate

This is the main entry point for programmatic usage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from transformer.confidence import ConfidenceScorer
from transformer.detect import detect_source_type
from transformer.extractors.base import BaseExtractor
from transformer.extractors.csv_extractor import CSVExtractor
from transformer.extractors.github_extractor import GitHubExtractor
from transformer.extractors.json_extractor import JSONExtractor
from transformer.extractors.notes_extractor import NotesExtractor
from transformer.extractors.resume_extractor import ResumeExtractor
from transformer.merger import CandidateMerger
from transformer.models import (
    CandidateFragment,
    CanonicalProfile,
    OutputConfig,
    PipelineResult,
    SourceType,
)
from transformer.projector import Projector
from transformer.validator import Validator

logger = logging.getLogger(__name__)

# Registry: source type → extractor class
_EXTRACTOR_REGISTRY: dict[SourceType, type[BaseExtractor]] = {
    SourceType.RECRUITER_CSV: CSVExtractor,
    SourceType.ATS_JSON: JSONExtractor,
    SourceType.GITHUB: GitHubExtractor,
    SourceType.RESUME: ResumeExtractor,
    SourceType.RECRUITER_NOTES: NotesExtractor,
}


def _load_config(config_path: str | None) -> OutputConfig | None:
    """Load output config from a JSON file."""
    if not config_path:
        return None

    path = Path(config_path)
    if not path.exists():
        logger.warning("Config file not found: %s", config_path)
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OutputConfig.model_validate(data)
    except Exception as e:
        logger.error("Failed to load config %s: %s", config_path, e)
        return None


class Pipeline:
    """
    Orchestrates the full candidate transformation pipeline.

    Usage:
        pipeline = Pipeline()
        results = pipeline.run(
            input_paths=["recruiter.csv", "ats.json", "resume.pdf"],
            config_path="custom_config.json",
        )
    """

    def __init__(self, github_token: str | None = None):
        self._github_token = github_token
        self._merger = CandidateMerger()
        self._scorer = ConfidenceScorer()
        self._projector = Projector()
        self._validator = Validator()

    def run(
        self,
        input_paths: list[str],
        config_path: str | None = None,
        source_types: dict[str, str] | None = None,
    ) -> list[PipelineResult]:
        """
        Run the full pipeline on the given inputs.

        Args:
            input_paths: List of file paths or URLs to process.
            config_path: Optional path to an output config JSON file.
            source_types: Optional explicit type overrides {path: type_string}.

        Returns:
            A list of PipelineResult objects (one per merged candidate).
        """
        source_types = source_types or {}
        warnings: list[str] = []

        # ── Step 1: Detect source types ──
        logger.info("Step 1: Detecting source types for %d inputs", len(input_paths))
        detected: list[tuple[str, SourceType]] = []
        for path in input_paths:
            explicit = source_types.get(path)
            st = detect_source_type(path, explicit)
            detected.append((path, st))
            logger.info("  %s → %s", path, st.value)

            if st == SourceType.UNKNOWN:
                warnings.append(f"Unknown source type for: {path}")

        # ── Step 2+3: Extract fragments ──
        logger.info("Step 2-3: Extracting candidate fragments")
        all_fragments: list[CandidateFragment] = []

        for path, source_type in detected:
            extractor_cls = _EXTRACTOR_REGISTRY.get(source_type)
            if not extractor_cls:
                warnings.append(f"No extractor for source type: {source_type.value}")
                continue

            # Instantiate extractor (special case for GitHub with token)
            if source_type == SourceType.GITHUB:
                extractor = GitHubExtractor(token=self._github_token)
            else:
                extractor = extractor_cls()

            fragments = extractor.safe_extract(path)
            all_fragments.extend(fragments)

        if not all_fragments:
            logger.warning("No fragments extracted from any source")
            return []

        logger.info("Extracted %d total fragments", len(all_fragments))

        # ── Step 4+5: Merge fragments ──
        logger.info("Step 4-5: Merging and normalizing")
        profiles = self._merger.merge_all(all_fragments)
        logger.info("Merged into %d unique profiles", len(profiles))

        # ── Step 6: Confidence scoring ──
        logger.info("Step 6: Scoring confidence")
        profiles = self._scorer.score_profiles(profiles)

        # ── Step 7+8: Project and validate ──
        logger.info("Step 7-8: Projecting and validating output")
        config = _load_config(config_path)

        results: list[PipelineResult] = []
        for profile in profiles:
            result = self._project_and_validate(profile, config, warnings)
            results.append(result)

        logger.info("Pipeline complete: %d result(s)", len(results))
        return results

    def _project_and_validate(
        self,
        profile: CanonicalProfile,
        config: OutputConfig | None,
        warnings: list[str],
    ) -> PipelineResult:
        """Project a profile and validate the output."""
        if config:
            projected = self._projector.project(profile, config)
            validation = self._validator.validate(projected, config)
        else:
            # Default: full projection
            default_config = OutputConfig()
            projected = self._projector.project(profile, default_config)
            validation = self._validator.validate_default(projected)

        return PipelineResult(
            canonical=profile,
            projected=projected,
            validation=validation,
            warnings=list(warnings),
        )

    def run_and_serialize(
        self,
        input_paths: list[str],
        config_path: str | None = None,
        source_types: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Run the pipeline and return serializable dicts.
        Convenience method for CLI / JSON output.
        """
        results = self.run(input_paths, config_path, source_types)
        output: list[dict[str, Any]] = []

        for result in results:
            entry: dict[str, Any] = {
                "profile": result.projected,
                "validation": result.validation.model_dump(),
            }
            if result.warnings:
                entry["warnings"] = result.warnings
            output.append(entry)

        return output
