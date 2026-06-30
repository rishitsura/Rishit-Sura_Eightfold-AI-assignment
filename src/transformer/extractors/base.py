"""
Base extractor abstract class.

All source-specific extractors inherit from BaseExtractor and implement
the `extract` method to produce a CandidateFragment.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from transformer.models import CandidateFragment, SourceType

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Abstract base for all source extractors."""

    source_type: SourceType = SourceType.UNKNOWN

    @abstractmethod
    def extract(self, input_path: str) -> list[CandidateFragment]:
        """
        Extract candidate fragments from the given input.

        Args:
            input_path: Path to the source file or URL.

        Returns:
            A list of CandidateFragment objects (one per candidate found).
            May return an empty list if the source is empty or malformed.
        """
        ...

    def safe_extract(self, input_path: str) -> list[CandidateFragment]:
        """
        Wrapper that catches exceptions and returns an empty list on failure.
        Ensures a single bad source never crashes the pipeline.
        """
        try:
            fragments = self.extract(input_path)
            logger.info(
                "Extracted %d fragment(s) from %s [%s]",
                len(fragments),
                input_path,
                self.source_type.value,
            )
            return fragments
        except Exception as exc:
            logger.warning(
                "Failed to extract from %s [%s]: %s",
                input_path,
                self.source_type.value,
                exc,
            )
            return []
