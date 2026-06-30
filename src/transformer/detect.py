"""
Source type detection.

Determines the SourceType of an input based on file extension, URL pattern,
or an explicit type hint provided by the user.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from transformer.models import SourceType


# Mapping of file extensions to source types
_EXTENSION_MAP: dict[str, SourceType] = {
    ".csv": SourceType.RECRUITER_CSV,
    ".json": SourceType.ATS_JSON,
    ".pdf": SourceType.RESUME,
    ".docx": SourceType.RESUME,
    ".doc": SourceType.RESUME,
    ".txt": SourceType.RECRUITER_NOTES,
}

# URL patterns
_GITHUB_HOSTS = {"github.com", "www.github.com"}


def detect_source_type(
    path_or_url: str,
    explicit_type: str | None = None,
) -> SourceType:
    """
    Detect the source type for a given input path or URL.

    Args:
        path_or_url: File path or URL string.
        explicit_type: If provided, overrides auto-detection.

    Returns:
        The detected SourceType.
    """
    # Honour explicit overrides
    if explicit_type:
        try:
            return SourceType(explicit_type)
        except ValueError:
            pass  # Fall through to auto-detection

    # Check if it's a URL
    parsed = urlparse(path_or_url)
    if parsed.scheme in ("http", "https"):
        host = parsed.hostname or ""
        if host in _GITHUB_HOSTS:
            return SourceType.GITHUB
        # Could add LinkedIn, etc. in the future
        return SourceType.UNKNOWN

    # File-based detection
    ext = Path(path_or_url).suffix.lower()
    if ext in _EXTENSION_MAP:
        # Disambiguate .txt: check filename for hints
        if ext == ".txt":
            basename = os.path.basename(path_or_url).lower()
            if "github" in basename:
                return SourceType.GITHUB  # e.g. "github_profile.txt"
            return SourceType.RECRUITER_NOTES
        return _EXTENSION_MAP[ext]

    return SourceType.UNKNOWN
