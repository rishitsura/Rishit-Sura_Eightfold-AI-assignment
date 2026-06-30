"""
Recruiter notes extractor.

Parses free-text recruiter notes (.txt) to extract candidate information
using regex patterns and keyword-based heuristics.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from transformer.extractors.base import BaseExtractor
from transformer.models import (
    CandidateFragment,
    Education,
    Experience,
    Links,
    Location,
    SourceType,
)
from transformer.normalizers import (
    EMAIL_PATTERN,
    GITHUB_PATTERN,
    LINKEDIN_PATTERN,
    PHONE_PATTERN,
)

logger = logging.getLogger(__name__)

# Patterns for extracting structured data from free text
_NAME_PATTERN = re.compile(
    r"(?i:candidate|name|applicant|interviewed|spoke\s+(?:with|to)|met)"
    r"[^\S\n]*[:=]?[^\S\n]*"
    r"([A-Z][a-z]+(?:[^\S\n]+[A-Z][a-z]+){1,4})",
)

_COMPANY_PATTERN = re.compile(
    r"(?:currently at|works at|working at|employed at|employed by|company|current employer)\s*[:=]?\s*([A-Z][\w\s&.]+?)(?:\s*[,.\n]|\s+as\s+|\s+since\s+|\s+for\s+)",
    re.IGNORECASE,
)

_TITLE_PATTERN = re.compile(
    r"(?:\btitle\b|\bposition\b|\brole\b|\bdesignation\b|currently\s+(?:works?\s+as|serving\s+as)|works?\s+as|working\s+as)\s*[:=]?\s*([\w\s/]+?)(?:\s*[,.\n]|\s+at\s+|\s+in\s+)",
    re.IGNORECASE,
)

_YEARS_EXP_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?|yr)[\s.]*(?:of\s+)?(?:experience|exp|in)",
    re.IGNORECASE,
)

_LOCATION_PATTERN = re.compile(
    r"(?:based in|located in|lives in|from|location|residing in)\s*[:=]?\s*([A-Z][a-zA-Z\s,]+?)(?:\s*[.\n])",
    re.IGNORECASE,
)

_SKILL_CONTEXT_PATTERN = re.compile(
    r"(?:skilled in|proficient in|experienced with|experienced in|knows|expertise in|strong in|familiar with|background in|works with|using|knowledge of)\s*[:=]?\s*(.+?)(?:\s*[.\n])",
    re.IGNORECASE,
)

_EDUCATION_PATTERN = re.compile(
    r"(?:graduated from|studied at|degree from|alumni of|attended)\s*[:=]?\s*(.+?)(?:\s+with\s+|\s+in\s+|\n|$)",
    re.IGNORECASE,
)

_DEGREE_PATTERN = re.compile(
    r"(?:has|holds|earned|completed|with)\s+(?:a\s+)?(?:an?\s+)?\b((?:Bachelor|Master|Ph\.?D|MBA|B\.?S\.?|M\.?S\.?|B\.?Tech|M\.?Tech|B\.?E\.?|M\.?E\.?)(?:\s+(?:in|of)\s+[\w\s]+)?)\b",
    re.IGNORECASE,
)


class NotesExtractor(BaseExtractor):
    """Extracts candidate data from free-text recruiter notes."""

    source_type = SourceType.RECRUITER_NOTES

    def extract(self, input_path: str) -> list[CandidateFragment]:
        path = Path(input_path)
        if not path.exists():
            logger.warning("Notes file not found: %s", input_path)
            return []

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="latin-1")
            except Exception:
                logger.warning("Could not read notes file: %s", input_path)
                return []

        if not text.strip():
            return []

        # Check if the file contains multiple candidate blocks
        # (separated by horizontal rules, "---", or "Candidate:" headers)
        blocks = self._split_candidate_blocks(text)

        fragments: list[CandidateFragment] = []
        for block in blocks:
            fragment = self._parse_block(block, input_path)
            if fragment:
                fragments.append(fragment)

        return fragments

    def _split_candidate_blocks(self, text: str) -> list[str]:
        """Split text into per-candidate blocks."""
        # Try splitting by common separators
        parts = re.split(
            r"\n\s*(?:---+|===+|___+|\*\*\*+)\s*\n"
            r"|"
            r"\n\s*(?:Candidate|Applicant|Profile)\s*(?:\d+|#\d+)?\s*[:=]?\s*\n",
            text,
            flags=re.IGNORECASE,
        )

        # If no splits found, treat entire text as one block
        blocks = [b.strip() for b in parts if b and b.strip()]
        return blocks if blocks else [text]

    def _parse_block(self, text: str, source_file: str) -> Optional[CandidateFragment]:
        """Parse a single candidate block from recruiter notes."""

        # Extract contact info
        emails = EMAIL_PATTERN.findall(text)
        phone_matches = PHONE_PATTERN.findall(text)
        linkedin_urls = LINKEDIN_PATTERN.findall(text)
        github_urls = GITHUB_PATTERN.findall(text)

        # Clean phones — filter out date-like strings
        _date_like = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
        phones: list[str] = []
        for pm in phone_matches:
            phone_str = pm if isinstance(pm, str) else pm[0] if pm else ""
            phone_str = phone_str.strip()
            # Skip date-like strings (e.g., 2024-12-15)
            if _date_like.search(phone_str):
                continue
            digits = re.sub(r"\D", "", phone_str)
            if len(digits) >= 7:
                phones.append(phone_str)

        # Extract name
        name = None
        name_match = _NAME_PATTERN.search(text)
        if name_match:
            name = name_match.group(1).strip()

        # Extract company and title for experience
        experience: list[Experience] = []
        company = None
        title = None

        # Try combo sentences first (e.g., "works as a Title at Company" or "at Company as a Title")
        combo_pattern = re.compile(
            r"(?:currently\s+(?:works?\s+as|at)|works?\s+as|working\s+as|working\s+at)\s+(?:a\s+|an\s+)?([\w\s/]+?)\s+(at|as(?: a| an)?)\s+([A-Z][\w\s\.\-]+?)(?:\s+in\s+|\.\s|[,;\n]|$)",
            re.IGNORECASE,
        )
        combo_match = combo_pattern.search(text)
        if combo_match:
            first, prep, second = combo_match.groups()
            prep = prep.lower().strip()
            if prep == 'at':
                title, company = first.strip(), second.strip()
            else: # 'as' or 'as a'
                company, title = first.strip(), second.strip()
        else:
            # Fallback to individual patterns
            company_match = _COMPANY_PATTERN.search(text)
            if company_match:
                company = company_match.group(1).strip()

            title_match = _TITLE_PATTERN.search(text)
            if title_match:
                title = title_match.group(1).strip()
                # Strip article prefixes
                title = re.sub(r"^(?:a|an)\s+", "", title, flags=re.IGNORECASE)

        if company or title:
            experience.append(Experience(company=company, title=title))

        # Years of experience
        years_exp = None
        yoe_match = _YEARS_EXP_PATTERN.search(text)
        if yoe_match:
            try:
                years_exp = float(yoe_match.group(1))
            except ValueError:
                pass

        # Location
        location = None
        loc_match = _LOCATION_PATTERN.search(text)
        if loc_match:
            loc_str = loc_match.group(1).strip()
            parts = [p.strip() for p in loc_str.split(",")]
            if len(parts) >= 2:
                location = Location(city=parts[0], country=parts[-1])
            else:
                location = Location(city=parts[0])

        # Skills
        skills: list[str] = []
        for skill_match in _SKILL_CONTEXT_PATTERN.finditer(text):
            skill_text = skill_match.group(1).strip()
            # Split by common delimiters
            for skill in re.split(r"[,;/]|\s+and\s+", skill_text):
                skill = skill.strip()
                if skill and len(skill) > 1 and len(skill) < 50:
                    skills.append(skill)

        # Education
        education: list[Education] = []
        edu_match = _EDUCATION_PATTERN.search(text)
        degree_match = _DEGREE_PATTERN.search(text)

        if edu_match or degree_match:
            institution = edu_match.group(1).strip() if edu_match else None
            degree = degree_match.group(1).strip() if degree_match else None
            education.append(Education(institution=institution, degree=degree))

        # Links
        links = Links(
            linkedin=linkedin_urls[0] if linkedin_urls else None,
            github=github_urls[0] if github_urls else None,
        )

        # Headline from context
        headline = title  # Use extracted title as headline

        # Skip if we got nothing useful
        if not any([name, emails, phones, company, title, skills]):
            return None

        return CandidateFragment(
            source_type=SourceType.RECRUITER_NOTES,
            source_file=source_file,
            full_name=name,
            emails=emails,
            phones=phones,
            location=location,
            links=links,
            headline=headline,
            years_experience=years_exp,
            skills=skills,
            experience=experience,
            education=education,
        )
