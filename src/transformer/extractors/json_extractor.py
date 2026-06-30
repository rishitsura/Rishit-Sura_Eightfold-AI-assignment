"""
ATS JSON blob extractor.

Handles semi-structured JSON with non-standard field names.
Uses flexible field mapping with fallback heuristics.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from transformer.extractors.base import BaseExtractor
from transformer.models import (
    CandidateFragment,
    Education,
    Experience,
    Links,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

# ATS systems use wildly different field names — map them all
_FIELD_MAP: dict[str, list[str]] = {
    "name": [
        "full_name", "fullName", "name", "candidate_name", "candidateName",
        "display_name", "displayName", "applicant_name", "applicantName",
    ],
    "first_name": [
        "first_name", "firstName", "fname", "given_name", "givenName",
    ],
    "last_name": [
        "last_name", "lastName", "lname", "surname", "family_name", "familyName",
    ],
    "email": [
        "email", "email_address", "emailAddress", "primary_email", "primaryEmail",
        "contact_email", "contactEmail",
    ],
    "emails": [
        "emails", "email_addresses", "emailAddresses",
    ],
    "phone": [
        "phone", "phone_number", "phoneNumber", "mobile", "telephone",
        "contact_phone", "contactPhone", "cell",
    ],
    "phones": [
        "phones", "phone_numbers", "phoneNumbers",
    ],
    "title": [
        "title", "job_title", "jobTitle", "current_title", "currentTitle",
        "position", "role", "designation",
    ],
    "company": [
        "company", "current_company", "currentCompany", "organization",
        "employer", "company_name", "companyName",
    ],
    "headline": [
        "headline", "summary", "bio", "about", "profile_summary", "profileSummary",
        "professional_summary", "professionalSummary",
    ],
    "location": [
        "location", "address", "city", "current_location", "currentLocation",
    ],
    "skills": [
        "skills", "skill_list", "skillList", "technologies", "tech_stack",
        "techStack", "competencies",
    ],
    "experience": [
        "experience", "work_experience", "workExperience", "employment_history",
        "employmentHistory", "positions", "jobs", "work_history", "workHistory",
    ],
    "education": [
        "education", "educations", "education_history", "educationHistory",
        "academic_history", "academicHistory", "degrees",
    ],
    "linkedin": [
        "linkedin", "linkedin_url", "linkedinUrl", "linkedin_profile",
        "linkedinProfile",
    ],
    "github": [
        "github", "github_url", "githubUrl", "github_profile", "githubProfile",
    ],
    "portfolio": [
        "portfolio", "website", "personal_website", "personalWebsite",
        "portfolio_url", "portfolioUrl",
    ],
    "years_experience": [
        "years_experience", "yearsExperience", "yoe", "experience_years",
        "experienceYears", "total_experience", "totalExperience",
    ],
}


def _find_value(data: dict, field: str) -> Any:
    """Find a value in the dict using the field mapping."""
    aliases = _FIELD_MAP.get(field, [field])
    for alias in aliases:
        if alias in data:
            return data[alias]
    return None


def _parse_experience_entry(entry: dict) -> Experience:
    """Parse a single experience entry from various ATS formats."""
    return Experience(
        company=_find_value(entry, "company") or entry.get("org") or entry.get("organization"),
        title=_find_value(entry, "title") or entry.get("role") or entry.get("position"),
        start=entry.get("start") or entry.get("start_date") or entry.get("startDate") or entry.get("from"),
        end=entry.get("end") or entry.get("end_date") or entry.get("endDate") or entry.get("to"),
        summary=entry.get("summary") or entry.get("description") or entry.get("responsibilities"),
    )


def _parse_education_entry(entry: dict) -> Education:
    """Parse a single education entry from various ATS formats."""
    end_year = None
    for key in ("end_year", "endYear", "graduation_year", "graduationYear", "year", "end"):
        val = entry.get(key)
        if val is not None:
            try:
                end_year = int(str(val)[:4])
                break
            except (ValueError, TypeError):
                continue

    return Education(
        institution=entry.get("institution") or entry.get("school") or entry.get("university") or entry.get("college"),
        degree=entry.get("degree") or entry.get("qualification") or entry.get("level"),
        field=entry.get("field") or entry.get("major") or entry.get("field_of_study") or entry.get("fieldOfStudy") or entry.get("specialization"),
        end_year=end_year,
    )


def _parse_location(loc_data: Any) -> Location | None:
    """Parse location from string or dict."""
    if isinstance(loc_data, str):
        parts = [p.strip() for p in loc_data.split(",")]
        if len(parts) >= 3:
            return Location(city=parts[0], region=parts[1], country=parts[2])
        elif len(parts) == 2:
            return Location(city=parts[0], country=parts[1])
        elif len(parts) == 1:
            return Location(city=parts[0])
    elif isinstance(loc_data, dict):
        return Location(
            city=loc_data.get("city"),
            region=loc_data.get("region") or loc_data.get("state") or loc_data.get("province"),
            country=loc_data.get("country") or loc_data.get("country_code") or loc_data.get("countryCode"),
        )
    return None


class JSONExtractor(BaseExtractor):
    """Extracts candidate data from ATS JSON blobs."""

    source_type = SourceType.ATS_JSON

    def extract(self, input_path: str) -> list[CandidateFragment]:
        path = Path(input_path)
        if not path.exists():
            logger.warning("JSON file not found: %s", input_path)
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Malformed JSON in %s (line %d col %d): %s — skipping file",
                input_path, exc.lineno, exc.colno, exc.msg,
            )
            return []
        except OSError as exc:
            logger.warning("Could not read JSON file %s: %s", input_path, exc)
            return []

        # Handle both single object and array of candidates
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            # Check for common wrapper keys
            for wrapper_key in ("candidates", "applicants", "data", "results", "records"):
                if wrapper_key in data and isinstance(data[wrapper_key], list):
                    candidates = data[wrapper_key]
                    break
            else:
                # Treat as single candidate
                candidates = [data]
        else:
            logger.warning("Unexpected JSON structure in %s", input_path)
            return []

        fragments: list[CandidateFragment] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            fragment = self._parse_candidate(candidate, input_path)
            if fragment:
                fragments.append(fragment)

        return fragments

    def _parse_candidate(
        self, data: dict, source_file: str
    ) -> CandidateFragment | None:
        """Parse a single candidate dict into a fragment."""

        # Name
        name = _find_value(data, "name")
        if not name:
            first = _find_value(data, "first_name") or ""
            last = _find_value(data, "last_name") or ""
            name = f"{first} {last}".strip() or None

        # Emails
        emails = []
        email_val = _find_value(data, "email")
        if isinstance(email_val, str):
            emails = [email_val]
        elif isinstance(email_val, list):
            emails = email_val
        emails_val = _find_value(data, "emails")
        if isinstance(emails_val, list):
            emails.extend(emails_val)

        # Phones
        phones = []
        phone_val = _find_value(data, "phone")
        if isinstance(phone_val, str):
            phones = [phone_val]
        elif isinstance(phone_val, list):
            phones = phone_val
        phones_val = _find_value(data, "phones")
        if isinstance(phones_val, list):
            phones.extend(phones_val)

        # Location
        location = _parse_location(_find_value(data, "location"))

        # Links
        links = Links(
            linkedin=_find_value(data, "linkedin"),
            github=_find_value(data, "github"),
            portfolio=_find_value(data, "portfolio"),
        )

        # Headline
        headline = _find_value(data, "headline")

        # Skills
        skills = []
        skills_val = _find_value(data, "skills")
        if isinstance(skills_val, list):
            for s in skills_val:
                if isinstance(s, str):
                    skills.append(s)
                elif isinstance(s, dict):
                    skill_name = s.get("name") or s.get("skill") or s.get("label")
                    if skill_name:
                        skills.append(str(skill_name))
        elif isinstance(skills_val, str):
            skills = [s.strip() for s in skills_val.split(",") if s.strip()]

        # Experience
        experience = []
        exp_val = _find_value(data, "experience")
        if isinstance(exp_val, list):
            for entry in exp_val:
                if isinstance(entry, dict):
                    experience.append(_parse_experience_entry(entry))

        # Education
        education = []
        edu_val = _find_value(data, "education")
        if isinstance(edu_val, list):
            for entry in edu_val:
                if isinstance(entry, dict):
                    education.append(_parse_education_entry(entry))

        # Title as headline fallback
        title = _find_value(data, "title")
        if not headline and title:
            headline = title

        # Years of experience
        years_exp = None
        yoe_val = _find_value(data, "years_experience")
        if yoe_val is not None:
            try:
                years_exp = float(yoe_val)
            except (ValueError, TypeError):
                pass

        # Skip empty records
        if not any([name, emails, phones]):
            return None

        return CandidateFragment(
            source_type=SourceType.ATS_JSON,
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
