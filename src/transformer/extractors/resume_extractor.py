"""
Resume extractor.

Extracts candidate data from PDF and DOCX resume files using
regex-based parsing. No ML or LLM is used — everything is deterministic.

Extraction strategy:
1. Extract raw text from the document.
2. Use regex patterns to find emails, phones, links.
3. Use section detection heuristics to identify experience, education, skills blocks.
4. Parse structured data from each section.
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

# Section header patterns (case-insensitive)
_SECTION_PATTERNS: dict[str, re.Pattern] = {
    "experience": re.compile(
        r"^(?:work\s+)?(?:experience|employment|professional\s+experience|work\s+history|career\s+history)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "education": re.compile(
        r"^(?:education|academic|qualifications|degrees)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "skills": re.compile(
        r"^(?:skills|technical\s+skills|technologies|competencies|proficiencies|tech\s+stack|core\s+competencies)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "summary": re.compile(
        r"^(?:summary|objective|profile|about|professional\s+summary|career\s+objective|overview)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "projects": re.compile(
        r"^(?:projects|personal\s+projects|key\s+projects|notable\s+projects)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "certifications": re.compile(
        r"^(?:certifications?|certificates?|licenses?|credentials?|awards?|honors?|publications?)",
        re.IGNORECASE | re.MULTILINE,
    ),
}

# Date range pattern: "Jan 2020 - Present", "2019-01 to 2021-06", etc.
_DATE_RANGE_RE = re.compile(
    r"("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s.,]*\d{4}"
    r"|"
    r"\d{4}[-/]\d{1,2}"
    r"|"
    r"\d{1,2}[-/]\d{4}"
    r"|"
    r"\d{4}"
    r")"
    r"\s*(?:[-–—]|to)\s*"
    r"("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"[\s.,]*\d{4}"
    r"|"
    r"\d{4}[-/]\d{1,2}"
    r"|"
    r"\d{1,2}[-/]\d{4}"
    r"|"
    r"\d{4}"
    r"|"
    r"[Pp]resent|[Cc]urrent|[Nn]ow|[Oo]ngoing"
    r")",
    re.IGNORECASE,
)

# Experience entry pattern: "Title at Company" or "Company - Title"
_EXP_TITLE_COMPANY_RE = re.compile(
    r"^(.+?)\s+(?:at|@)\s+(.+?)$"
    r"|"
    r"^(.+?)\s*[-–—|]\s*(.+?)$",
    re.IGNORECASE,
)

# Education degree patterns
_DEGREE_RE = re.compile(
    r"\b(?:Bachelor|Master|Ph\.?D|Doctor|Associate|B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?|B\.?Tech|M\.?Tech|B\.?E\.?|M\.?E\.?|MBA|B\.?Sc|M\.?Sc|B\.?Com|M\.?Com)\b(?:\s+(?:of|in)\s+.+?)?",
    re.IGNORECASE,
)

# Graduation year
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# City, State/Country pattern for location at top of resume
_LOCATION_RE = re.compile(
    r"(?:^|\n)\s*([A-Z][a-zA-Z\s]+),\s*([A-Z][a-zA-Z\s]+)(?:,\s*([A-Z][a-zA-Z\s]+))?\s*(?:\n|$)"
)


def _is_multi_column_page(words: list, page_width: float) -> bool:
    """
    Detect whether a PDF page uses a multi-column layout.

    Heuristic: if more than 20% of words have x0 > 50% of the page width
    AND more than 20% have x0 < 50%, the page is likely two-column.
    """
    if not words or page_width <= 0:
        return False
    midpoint = page_width / 2
    left_count = sum(1 for w in words if w.get("x0", 0) < midpoint)
    right_count = sum(1 for w in words if w.get("x0", 0) >= midpoint)
    total = left_count + right_count
    if total == 0:
        return False
    return (left_count / total > 0.2) and (right_count / total > 0.2)


def _extract_text_sorted(page) -> str:
    """
    Extract text from a pdfplumber page, re-sorting words by vertical position
    (top → bottom) to handle multi-column layouts without scrambling.

    For single-column pages this produces the same result as extract_text().
    For two-column pages it preserves reading order row by row.
    """
    try:
        words = page.extract_words()
    except Exception:
        return page.extract_text() or ""

    if not words:
        return page.extract_text() or ""

    # Sort words: primary key = top (vertical position), secondary = x0 (left→right)
    words_sorted = sorted(words, key=lambda w: (round(w.get("top", 0)), w.get("x0", 0)))

    # Group words into lines by proximity of their top coordinate (±3 pts = same line)
    lines: list[list[str]] = []
    current_line: list[str] = []
    current_top: float | None = None

    for word in words_sorted:
        top = word.get("top", 0)
        text = word.get("text", "")
        if not text:
            continue
        if current_top is None or abs(top - current_top) <= 3:
            current_line.append(text)
            current_top = top
        else:
            if current_line:
                lines.append(current_line)
            current_line = [text]
            current_top = top

    if current_line:
        lines.append(current_line)

    return "\n".join(" ".join(line) for line in lines)


def _extract_text_from_pdf(path: Path) -> str:
    """
    Extract text from a PDF file.

    Automatically detects multi-column layouts and re-sorts word bounding boxes
    top-to-bottom before joining, preventing the scrambled text that pdfplumber's
    default left-to-right extraction produces on two-column resume layouts.
    """
    try:
        import pdfplumber
        text_parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                try:
                    words = page.extract_words()
                    page_width = page.width or 0

                    if _is_multi_column_page(words, page_width):
                        logger.debug(
                            "Multi-column layout detected on page %d of %s — using sorted extraction",
                            getattr(page, "page_number", "?"),
                            path.name,
                        )
                        page_text = _extract_text_sorted(page)
                    else:
                        page_text = page.extract_text() or ""

                    if page_text:
                        text_parts.append(page_text)
                except Exception as page_err:
                    logger.debug("Page extraction error in %s: %s", path.name, page_err)
                    fallback = page.extract_text()
                    if fallback:
                        text_parts.append(fallback)

        return "\n".join(text_parts)
    except Exception as e:
        logger.warning("Failed to extract text from PDF %s: %s", path, e)
        return ""


def _extract_text_from_docx(path: Path) -> str:
    """Extract text from a DOCX file."""
    try:
        import docx
        doc = docx.Document(path)
        return "\n".join(para.text for para in doc.paragraphs)
    except Exception as e:
        logger.warning("Failed to extract text from DOCX %s: %s", path, e)
        return ""


def _extract_text_from_txt(path: Path) -> str:
    """Extract text from a plain text file."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="latin-1")
        except Exception as e:
            logger.warning("Failed to read text file %s: %s", path, e)
            return ""


def _split_sections(text: str) -> dict[str, str]:
    """
    Split resume text into named sections based on header detection.

    Returns a dict with keys like 'experience', 'education', 'skills', 'summary',
    plus 'header' for content before the first section and 'remaining' for unmatched.
    """
    sections: dict[str, str] = {}
    section_positions: list[tuple[int, str]] = []

    for section_name, pattern in _SECTION_PATTERNS.items():
        for match in pattern.finditer(text):
            section_positions.append((match.start(), section_name))

    # Sort by position
    section_positions.sort(key=lambda x: x[0])

    if not section_positions:
        return {"header": text}

    # Content before first section = header (contains name, contact info)
    sections["header"] = text[: section_positions[0][0]]

    # Extract each section's content
    for i, (pos, name) in enumerate(section_positions):
        # Find end of section header line
        header_end = text.find("\n", pos)
        if header_end == -1:
            header_end = pos

        # Content goes until next section or end
        if i + 1 < len(section_positions):
            content = text[header_end:section_positions[i + 1][0]]
        else:
            content = text[header_end:]

        sections[name] = content.strip()

    return sections


def _parse_experience_section(text: str) -> list[Experience]:
    """Parse experience entries from an experience section."""
    entries: list[Experience] = []

    # Split by date ranges first, then parse each block
    lines = text.split("\n")
    current_entry: dict = {}
    current_summary_lines: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for date range
        date_match = _DATE_RANGE_RE.search(line)
        if date_match:
            # Save previous entry
            if current_entry:
                if current_summary_lines:
                    current_entry["summary"] = " ".join(current_summary_lines)
                entries.append(Experience(**current_entry))

            start = date_match.group(1)
            end_raw = date_match.group(2)
            end = None if end_raw.lower() in ("present", "current", "now", "ongoing") else end_raw

            # Try to extract title/company from same line or context
            remaining = line[:date_match.start()].strip().rstrip("|-–—,")
            title, company = _parse_title_company(remaining)

            current_entry = {
                "company": company,
                "title": title,
                "start": start,
                "end": end,
            }
            current_summary_lines = []
            continue

        # Check for title/company pattern without dates
        if not current_entry:
            title, company = _parse_title_company(line)
            if title or company:
                current_entry = {"company": company, "title": title}
                current_summary_lines = []
                continue

        # Everything else is summary/description
        if current_entry and line.startswith(("•", "-", "·", "▪", "*", "–")):
            current_summary_lines.append(line.lstrip("•-·▪*– "))
        elif current_entry:
            # Could be title/company if no title yet
            if not current_entry.get("title") or not current_entry.get("company"):
                title, company = _parse_title_company(line)
                if title and not current_entry.get("title"):
                    current_entry["title"] = title
                if company and not current_entry.get("company"):
                    current_entry["company"] = company
            else:
                current_summary_lines.append(line)

    # Save last entry
    if current_entry:
        if current_summary_lines:
            current_entry["summary"] = " ".join(current_summary_lines)
        entries.append(Experience(**current_entry))

    return entries


def _parse_title_company(text: str) -> tuple[Optional[str], Optional[str]]:
    """Parse title and company from a line like 'Title at Company' or 'Company - Title'."""
    if not text:
        return None, None

    match = _EXP_TITLE_COMPANY_RE.match(text)
    if match:
        # "Title at Company" pattern
        if match.group(1) and match.group(2):
            return match.group(1).strip(), match.group(2).strip()
        # "Company - Title" pattern
        if match.group(3) and match.group(4):
            return match.group(4).strip(), match.group(3).strip()

    return text.strip() if text.strip() else None, None


def _parse_education_section(text: str) -> list[Education]:
    """Parse education entries from an education section."""
    entries: list[Education] = []
    lines = text.split("\n")
    current: dict = {}

    for line in lines:
        line = line.strip()
        if not line:
            if current:
                entries.append(Education(**current))
                current = {}
            continue

        # Check for degree
        degree_match = _DEGREE_RE.search(line)
        if degree_match:
            if current and current.get("degree"):
                entries.append(Education(**current))
                current = {}

            current["degree"] = degree_match.group(0).strip()

            # Check for field of study after degree
            after_degree = line[degree_match.end():].strip()
            if after_degree:
                # Remove common separators
                field = re.sub(r"^[\s,\-–—in]+", "", after_degree).strip()
                if field:
                    current["field"] = field

        # Check for year
        year_match = _YEAR_RE.search(line)
        if year_match:
            try:
                current["end_year"] = int(year_match.group(0))
            except ValueError:
                pass

        # Check for institution (line without degree keywords, often comes first)
        if not degree_match and not current.get("institution"):
            # Heuristic: institution names are typically capitalized and contain
            # words like "University", "College", "Institute", "School"
            if any(
                kw in line.lower()
                for kw in ("university", "college", "institute", "school", "academy", "iit", "mit", "stanford")
            ):
                current["institution"] = line.split(",")[0].strip().rstrip("-–—|")
            elif not current and len(line) > 3 and line[0].isupper():
                # First line might be institution name
                current["institution"] = line.split(",")[0].strip().rstrip("-–—|")

    # Save last entry
    if current:
        entries.append(Education(**current))

    return entries


def _parse_skills_section(text: str) -> list[str]:
    """Parse skill names from a skills section."""
    skills: list[str] = []

    # Common patterns:
    # - Comma or pipe separated: "Python, Java, C++"
    # - Bullet list: "• Python\n• Java"
    # - Category-prefixed: "Languages: Python, Java"

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Remove category prefix (e.g., "Languages: ", "Tools: ")
        if ":" in line:
            line = line.split(":", 1)[1].strip()

        # Remove bullets
        line = re.sub(r"^[•\-·▪*–]\s*", "", line)

        # Split by common delimiters (not / since it appears in skill names like CI/CD)
        for skill in re.split(r"[,;|•·]", line):
            skill = skill.strip().strip("•-·▪*–() ")
            if skill and len(skill) > 1 and len(skill) < 50:
                skills.append(skill)

    return skills


class ResumeExtractor(BaseExtractor):
    """Extracts candidate data from resume files (PDF, DOCX, TXT)."""

    source_type = SourceType.RESUME

    def extract(self, input_path: str) -> list[CandidateFragment]:
        path = Path(input_path)
        if not path.exists():
            logger.warning("Resume file not found: %s", input_path)
            return []

        # Extract raw text based on file type
        ext = path.suffix.lower()
        if ext == ".pdf":
            text = _extract_text_from_pdf(path)
        elif ext in (".docx", ".doc"):
            text = _extract_text_from_docx(path)
        elif ext == ".txt":
            text = _extract_text_from_txt(path)
        else:
            logger.warning("Unsupported resume format: %s", ext)
            return []

        if not text.strip():
            logger.warning("Empty resume: %s", input_path)
            return []

        fragment = self._parse_resume(text, input_path)
        return [fragment] if fragment else []

    def _parse_resume(self, text: str, source_file: str) -> CandidateFragment | None:
        """Parse resume text into a CandidateFragment."""

        # Split into sections
        sections = _split_sections(text)
        header = sections.get("header", "")

        # Extract contact info from header (top of resume)
        emails = EMAIL_PATTERN.findall(text)  # Search entire text for emails
        phones = PHONE_PATTERN.findall(header)
        linkedin_urls = LINKEDIN_PATTERN.findall(text)
        github_urls = GITHUB_PATTERN.findall(text)

        # Clean phone matches (PHONE_PATTERN can be noisy)
        cleaned_phones: list[str] = []
        for phone in phones:
            phone_str = phone if isinstance(phone, str) else phone[0] if phone else ""
            phone_str = phone_str.strip()
            # Basic validation: must have at least 7 digits
            digits = re.sub(r"\D", "", phone_str)
            if len(digits) >= 7:
                cleaned_phones.append(phone_str)

        # Extract name (usually first line of header)
        name = self._extract_name(header)

        # Build links
        links = Links(
            linkedin=linkedin_urls[0] if linkedin_urls else None,
            github=github_urls[0] if github_urls else None,
        )

        # Extract headline/summary
        headline = None
        summary_section = sections.get("summary", "")
        if summary_section:
            # Take first 200 chars as headline
            headline = summary_section[:200].strip()
            if len(summary_section) > 200:
                headline += "..."

        # Location from header
        location = self._extract_location(header)

        # Parse structured sections
        experience = []
        if "experience" in sections:
            experience = _parse_experience_section(sections["experience"])

        education = []
        if "education" in sections:
            education = _parse_education_section(sections["education"])

        skills = []
        if "skills" in sections:
            skills = _parse_skills_section(sections["skills"])

        # Calculate years of experience from experience dates
        years_exp = self._calc_years_experience(experience)

        return CandidateFragment(
            source_type=SourceType.RESUME,
            source_file=source_file,
            full_name=name,
            emails=emails,
            phones=cleaned_phones,
            location=location,
            links=links,
            headline=headline,
            years_experience=years_exp,
            skills=skills,
            experience=experience,
            education=education,
        )

    def _extract_name(self, header: str) -> Optional[str]:
        """Extract candidate name from the resume header."""
        lines = [l.strip() for l in header.split("\n") if l.strip()]
        if not lines:
            return None

        # Name is typically the first non-empty line that:
        # - Doesn't look like an email, phone, URL
        # - Is relatively short (< 50 chars)
        # - Contains mostly alphabetic characters
        for line in lines[:3]:  # Check first 3 lines
            if "@" in line or "http" in line.lower():
                continue
            if re.match(r"^\+?\d[\d\s\-()]+$", line):  # Phone number
                continue
            # Check if it looks like a name (mostly letters and spaces)
            alpha_ratio = sum(c.isalpha() or c.isspace() for c in line) / max(len(line), 1)
            if alpha_ratio > 0.7 and len(line) < 50:
                return line
        return None

    def _extract_location(self, header: str) -> Optional[Location]:
        """Extract location from resume header."""
        match = _LOCATION_RE.search(header)
        if match:
            city = match.group(1).strip()
            region_or_country = match.group(2).strip()
            country = match.group(3).strip() if match.group(3) else None
            if country:
                return Location(city=city, region=region_or_country, country=country)
            return Location(city=city, country=region_or_country)
        return None

    def _calc_years_experience(self, experiences: list[Experience]) -> Optional[float]:
        """Estimate total years of experience from experience entries."""
        if not experiences:
            return None

        from transformer.normalizers import normalize_date
        from datetime import datetime

        total_months = 0
        for exp in experiences:
            start = normalize_date(exp.start) if exp.start else None
            end = normalize_date(exp.end) if exp.end else None

            if start:
                try:
                    start_dt = datetime.strptime(start, "%Y-%m")
                    if end:
                        end_dt = datetime.strptime(end, "%Y-%m")
                    else:
                        end_dt = datetime.now()
                    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
                    total_months += max(0, months)
                except ValueError:
                    continue

        return round(total_months / 12, 1) if total_months > 0 else None
