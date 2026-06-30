"""
Recruiter CSV extractor.

Handles CSV files with columns: name, email, phone, current_company, title.
Column names are matched case-insensitively with common variations.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from transformer.extractors.base import BaseExtractor
from transformer.models import (
    CandidateFragment,
    Experience,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

# Map of canonical field name → possible CSV column headers (lowercase)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["name", "full_name", "fullname", "candidate_name", "candidate name", "first_last"],
    "first_name": ["first_name", "firstname", "first name", "fname"],
    "last_name": ["last_name", "lastname", "last name", "lname", "surname"],
    "email": ["email", "email_address", "emailaddress", "e-mail", "email address", "contact_email"],
    "phone": ["phone", "phone_number", "phonenumber", "telephone", "mobile", "cell", "phone number", "contact_phone"],
    "company": ["current_company", "company", "current company", "organization", "employer", "company_name"],
    "title": ["title", "job_title", "jobtitle", "position", "role", "job title", "designation"],
    "location": ["location", "city", "address", "place"],
    "linkedin": ["linkedin", "linkedin_url", "linkedin url", "linkedin_profile"],
    "github": ["github", "github_url", "github url", "github_profile"],
    "skills": ["skills", "skill", "technologies", "tech_stack", "tech stack"],
    "experience_years": ["years_experience", "experience_years", "yoe", "years of experience", "experience"],
}


def _find_column(headers: list[str], field: str) -> str | None:
    """Find the actual column name that matches a canonical field."""
    aliases = _COLUMN_ALIASES.get(field, [field])
    header_lower = {h.lower().strip(): h for h in headers}
    for alias in aliases:
        if alias in header_lower:
            return header_lower[alias]
    return None


class CSVExtractor(BaseExtractor):
    """Extracts candidate data from recruiter CSV exports."""

    source_type = SourceType.RECRUITER_CSV

    def extract(self, input_path: str) -> list[CandidateFragment]:
        path = Path(input_path)
        if not path.exists():
            logger.warning("CSV file not found: %s", input_path)
            return []

        fragments: list[CandidateFragment] = []

        # Try different encodings
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(path, "r", encoding=encoding, newline="") as f:
                    reader = csv.DictReader(f)
                    if reader.fieldnames is None:
                        continue
                    headers = list(reader.fieldnames)

                    for row in reader:
                        fragment = self._row_to_fragment(row, headers, input_path)
                        if fragment:
                            fragments.append(fragment)
                break  # Success, no need to try other encodings
            except UnicodeDecodeError:
                continue

        return fragments

    def _row_to_fragment(
        self, row: dict, headers: list[str], source_file: str
    ) -> CandidateFragment | None:
        """Convert a single CSV row to a CandidateFragment."""

        def get(field: str) -> str | None:
            col = _find_column(headers, field)
            if col and col in row:
                val = row[col].strip() if row[col] else None
                return val if val else None
            return None

        # Build name
        name = get("name")
        if not name:
            first = get("first_name") or ""
            last = get("last_name") or ""
            name = f"{first} {last}".strip() or None

        # Build emails
        emails = []
        email = get("email")
        if email:
            # Handle multiple emails separated by ; or ,
            for e in email.replace(";", ",").split(","):
                e = e.strip()
                if e:
                    emails.append(e)

        # Build phones
        phones = []
        phone = get("phone")
        if phone:
            for p in phone.replace(";", ",").split(","):
                p = p.strip()
                if p:
                    phones.append(p)

        # Build experience from company + title
        experience = []
        company = get("company")
        title = get("title")
        if company or title:
            experience.append(Experience(company=company, title=title))

        # Location
        location = None
        loc_str = get("location")
        if loc_str:
            parts = [p.strip() for p in loc_str.split(",")]
            if len(parts) >= 3:
                location = Location(city=parts[0], region=parts[1], country=parts[2])
            elif len(parts) == 2:
                location = Location(city=parts[0], country=parts[1])
            elif len(parts) == 1:
                location = Location(city=parts[0])

        # Skills
        skills = []
        skills_str = get("skills")
        if skills_str:
            skills = [s.strip() for s in skills_str.replace(";", ",").split(",") if s.strip()]

        # Years of experience
        years_exp = None
        yoe_str = get("experience_years")
        if yoe_str:
            try:
                years_exp = float(yoe_str)
            except ValueError:
                pass

        # Skip completely empty rows
        if not any([name, emails, phones, company, title]):
            return None

        return CandidateFragment(
            source_type=SourceType.RECRUITER_CSV,
            source_file=source_file,
            full_name=name,
            emails=emails,
            phones=phones,
            location=location,
            headline=title,
            years_experience=years_exp,
            skills=skills,
            experience=experience,
        )
