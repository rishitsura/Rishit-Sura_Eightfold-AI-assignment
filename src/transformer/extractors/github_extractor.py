"""
GitHub profile extractor.

Fetches public profile data via the GitHub REST API v3.
Extracts: name, bio (headline), email, location, repos → skills.

Input can be:
- A GitHub URL (https://github.com/username)
- A .txt file containing a GitHub URL or username
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import requests

from transformer.extractors.base import BaseExtractor
from transformer.models import (
    CandidateFragment,
    Links,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([\w\-]+)/?",
    re.IGNORECASE,
)

# GitHub API base URL
_API_BASE = "https://api.github.com"

# Request timeout
_TIMEOUT = 15


def _extract_username(input_str: str) -> str | None:
    """Extract GitHub username from a URL or plain string."""
    # Try URL pattern
    match = _GITHUB_URL_RE.search(input_str)
    if match:
        return match.group(1)

    # Plain username (alphanumeric + hyphens, no spaces)
    cleaned = input_str.strip()
    if re.match(r"^[\w\-]+$", cleaned) and len(cleaned) <= 39:
        return cleaned

    return None


class GitHubExtractor(BaseExtractor):
    """Extracts candidate data from GitHub profiles via REST API."""

    source_type = SourceType.GITHUB

    def __init__(self, token: str | None = None):
        """
        Args:
            token: Optional GitHub personal access token for higher rate limits.
        """
        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
        }
        if token:
            self._headers["Authorization"] = f"token {token}"

    def extract(self, input_path: str) -> list[CandidateFragment]:
        """
        Extract candidate data from a GitHub profile.

        Args:
            input_path: Can be:
                - A GitHub profile URL
                - A path to a .txt file containing a GitHub URL or username
        """
        username = self._resolve_username(input_path)
        if not username:
            logger.warning("Could not determine GitHub username from: %s", input_path)
            return []

        # Fetch profile data
        profile = self._fetch_profile(username)
        if not profile:
            return []

        # Fetch repository languages for skill extraction
        languages = self._fetch_repo_languages(username)

        fragment = self._build_fragment(profile, languages, input_path)
        return [fragment] if fragment else []

    def _resolve_username(self, input_path: str) -> str | None:
        """Resolve the GitHub username from various input formats."""
        # Check if it's a file
        path = Path(input_path)
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                # Try each line for a GitHub URL or username
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    username = _extract_username(line)
                    if username:
                        return username
            except Exception as e:
                logger.debug("Error reading file %s: %s", input_path, e)

        # Try as URL or username directly
        return _extract_username(input_path)

    def _fetch_profile(self, username: str) -> dict[str, Any] | None:
        """Fetch user profile from GitHub API."""
        try:
            resp = requests.get(
                f"{_API_BASE}/users/{username}",
                headers=self._headers,
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.warning("GitHub user not found: %s", username)
            elif resp.status_code == 403:
                logger.warning("GitHub API rate limit exceeded")
            else:
                logger.warning("GitHub API error %d for %s", resp.status_code, username)
        except requests.RequestException as e:
            logger.warning("GitHub API request failed: %s", e)
        return None

    def _fetch_repo_languages(self, username: str) -> list[str]:
        """Fetch languages used across user's public repos."""
        languages: set[str] = set()
        try:
            resp = requests.get(
                f"{_API_BASE}/users/{username}/repos",
                headers=self._headers,
                params={"per_page": 30, "sort": "updated"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                repos = resp.json()
                for repo in repos:
                    if isinstance(repo, dict):
                        lang = repo.get("language")
                        if lang:
                            languages.add(lang)
                        # Also check topics for additional skill signals
                        topics = repo.get("topics", [])
                        if isinstance(topics, list):
                            for topic in topics:
                                if isinstance(topic, str) and len(topic) <= 30:
                                    languages.add(topic)
        except requests.RequestException as e:
            logger.debug("Failed to fetch repos for %s: %s", username, e)

        return sorted(languages)

    def _build_fragment(
        self,
        profile: dict[str, Any],
        languages: list[str],
        source_file: str,
    ) -> CandidateFragment | None:
        """Build a CandidateFragment from GitHub API data."""
        name = profile.get("name")
        bio = profile.get("bio")
        email = profile.get("email")
        location_str = profile.get("location")
        blog = profile.get("blog")
        html_url = profile.get("html_url")

        # Build emails list
        emails = []
        if email:
            emails.append(email)

        # Build location
        location = None
        if location_str:
            parts = [p.strip() for p in location_str.split(",")]
            if len(parts) >= 2:
                location = Location(city=parts[0], country=parts[-1])
            else:
                location = Location(city=parts[0])

        # Build links
        links = Links(
            github=html_url,
            portfolio=blog if blog else None,
        )

        # Skills from repo languages
        skills = languages

        # Public repos count could inform years_experience heuristic
        public_repos = profile.get("public_repos", 0)
        created_at = profile.get("created_at", "")
        years_exp = None
        if created_at:
            try:
                from datetime import datetime
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                from datetime import timezone
                now = datetime.now(timezone.utc)
                years_exp = round((now - created).days / 365.25, 1)
            except Exception:
                pass

        return CandidateFragment(
            source_type=SourceType.GITHUB,
            source_file=source_file,
            full_name=name,
            emails=emails,
            location=location,
            links=links,
            headline=bio,
            years_experience=years_exp,
            skills=skills,
        )
