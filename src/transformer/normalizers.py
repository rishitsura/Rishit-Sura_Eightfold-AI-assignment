"""
Normalization utilities.

Provides deterministic normalization for:
- Phone numbers → E.164
- Dates → YYYY-MM
- Country names → ISO-3166 alpha-2
- Skill names → canonical lowercase mapping
- Names → title-case, cleaned whitespace
- Emails → lowercase, validated
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import dateparser
import phonenumbers
import pycountry
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

def normalize_phone(raw: str, default_region: str = "US") -> Optional[str]:
    """
    Normalize a phone string to E.164 format.

    Returns None if the phone cannot be parsed.
    """
    if not raw or not raw.strip():
        return None

    cleaned = re.sub(r"[^\d+\-() ]", "", raw.strip())
    if not cleaned:
        return None

    try:
        parsed = phonenumbers.parse(cleaned, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
        # Try without validation for partial numbers
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.E164
        )
    except phonenumbers.NumberParseException:
        logger.debug("Could not parse phone: %s", raw)
        return None


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

def normalize_date(raw: str) -> Optional[str]:
    """
    Normalize a date string to YYYY-MM format.

    Handles various formats: "Jan 2020", "2020-01-15", "January 2020",
    "01/2020", "2020", etc.
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip()

    # Direct YYYY-MM match
    if re.match(r"^\d{4}-\d{2}$", cleaned):
        return cleaned

    # Year-only: return YYYY-01
    if re.match(r"^\d{4}$", cleaned):
        return f"{cleaned}-01"

    # Try dateparser
    try:
        parsed = dateparser.parse(
            cleaned,
            settings={
                "PREFER_DAY_OF_MONTH": "first",
                "REQUIRE_PARTS": ["year"],
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if parsed:
            return parsed.strftime("%Y-%m")
    except Exception:
        pass

    # MM/YYYY pattern
    match = re.match(r"(\d{1,2})[/\-](\d{4})", cleaned)
    if match:
        month, year = match.groups()
        return f"{year}-{int(month):02d}"

    logger.debug("Could not parse date: %s", raw)
    return None


# ---------------------------------------------------------------------------
# Country normalization
# ---------------------------------------------------------------------------

# Build a lookup of country names and common aliases
_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "india": "IN",
    "canada": "CA",
    "germany": "DE",
    "france": "FR",
    "australia": "AU",
    "japan": "JP",
    "china": "CN",
    "brazil": "BR",
    "mexico": "MX",
    "south korea": "KR",
    "singapore": "SG",
    "netherlands": "NL",
    "sweden": "SE",
    "switzerland": "CH",
    "israel": "IL",
    "ireland": "IE",
    "new zealand": "NZ",
    "spain": "ES",
    "italy": "IT",
    "poland": "PL",
    "portugal": "PT",
    "russia": "RU",
    "uae": "AE",
    "united arab emirates": "AE",
}

# Add all pycountry names
for _c in pycountry.countries:
    _COUNTRY_ALIASES[_c.name.lower()] = _c.alpha_2
    if hasattr(_c, "common_name"):
        _COUNTRY_ALIASES[_c.common_name.lower()] = _c.alpha_2


# US state abbreviations that are valid ISO alpha-2 codes for OTHER countries —
# these must be blocked from country resolution when they appear as location
# components (e.g., "San Francisco, CA" should not resolve CA → Canada).
_US_STATE_CODES: frozenset[str] = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP",
})


def normalize_country(raw: str) -> Optional[str]:
    """
    Normalize a country name or code to ISO-3166 alpha-2.

    Returns None if the country cannot be identified.

    Note: US state abbreviations (CA, TX, NY, GA …) are explicitly blocked
    from resolving to their ISO country-code homonyms (Canada, etc.).
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip()
    lower = cleaned.lower()

    # Check aliases first (catches UK→GB, USA→US, etc.)
    if lower in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[lower]

    # Block US state abbreviations BEFORE the 2-letter ISO check.
    # Without this, "CA" resolves to Canada, "GA" to Georgia (country), etc.
    if cleaned.upper() in _US_STATE_CODES:
        logger.debug(
            "'%s' looks like a US state abbreviation — not resolving to a country code",
            cleaned,
        )
        return None

    # Already a valid 2-letter ISO code?
    if len(cleaned) == 2 and cleaned.upper().isalpha():
        result = pycountry.countries.get(alpha_2=cleaned.upper())
        if result is not None:
            return cleaned.upper()

    # Fuzzy match against known country names
    match = process.extractOne(
        lower,
        list(_COUNTRY_ALIASES.keys()),
        scorer=fuzz.ratio,
        score_cutoff=80,
    )
    if match:
        return _COUNTRY_ALIASES[match[0]]

    logger.debug("Could not normalize country: %s", raw)
    return None


# ---------------------------------------------------------------------------
# Skill normalization
# ---------------------------------------------------------------------------

# Canonical skill name mappings (common abbreviations / variations)
_SKILL_CANONICAL: dict[str, str] = {
    # Programming languages
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "py": "Python",
    "python": "Python",
    "python3": "Python",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "golang": "Go",
    "go": "Go",
    "rb": "Ruby",
    "ruby": "Ruby",
    "rs": "Rust",
    "rust": "Rust",
    "java": "Java",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "scala": "Scala",
    "r": "R",
    "php": "PHP",
    "sql": "SQL",
    "html": "HTML",
    "css": "CSS",
    "shell": "Shell",
    "bash": "Shell",
    "powershell": "PowerShell",
    "perl": "Perl",
    "lua": "Lua",
    "dart": "Dart",
    "elixir": "Elixir",
    "haskell": "Haskell",
    "clojure": "Clojure",
    "objective-c": "Objective-C",
    "objc": "Objective-C",

    # Frameworks & libraries
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "angular": "Angular",
    "angularjs": "Angular",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "express": "Express.js",
    "expressjs": "Express.js",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    "rails": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "svelte": "Svelte",
    "tensorflow": "TensorFlow",
    "tf": "TensorFlow",
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scipy": "SciPy",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",

    # Databases
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "es": "Elasticsearch",
    "dynamodb": "DynamoDB",
    "cassandra": "Cassandra",
    "sqlite": "SQLite",
    "neo4j": "Neo4j",

    # Cloud & DevOps
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud Platform",
    "google cloud": "Google Cloud Platform",
    "azure": "Microsoft Azure",
    "microsoft azure": "Microsoft Azure",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "github actions": "GitHub Actions",
    "circleci": "CircleCI",
    "travis ci": "Travis CI",

    # Data & ML
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "dl": "Deep Learning",
    "deep learning": "Deep Learning",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "nlp": "Natural Language Processing",
    "natural language processing": "Natural Language Processing",
    "cv": "Computer Vision",
    "computer vision": "Computer Vision",
    "data science": "Data Science",
    "data engineering": "Data Engineering",
    "data analysis": "Data Analysis",
    "etl": "ETL",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "hadoop": "Hadoop",
    "kafka": "Apache Kafka",
    "apache kafka": "Apache Kafka",
    "airflow": "Apache Airflow",
    "apache airflow": "Apache Airflow",
    "bigquery": "BigQuery",

    # Other
    "git": "Git",
    "linux": "Linux",
    "agile": "Agile",
    "scrum": "Scrum",
    "rest": "REST APIs",
    "rest api": "REST APIs",
    "rest apis": "REST APIs",
    "graphql": "GraphQL",
    "grpc": "gRPC",
    "microservices": "Microservices",
    "api design": "API Design",
    "system design": "System Design",
    "oop": "Object-Oriented Programming",
    "object-oriented programming": "Object-Oriented Programming",
    "functional programming": "Functional Programming",
    "fp": "Functional Programming",
    "tdd": "Test-Driven Development",
    "test-driven development": "Test-Driven Development",
}


def normalize_skill(raw: str) -> str:
    """
    Normalize a skill name to its canonical form.

    Returns the canonical name if found in the mapping, otherwise
    returns the title-cased version of the input.
    """
    if not raw or not raw.strip():
        return raw

    cleaned = raw.strip()
    lower = cleaned.lower()

    # Direct lookup
    if lower in _SKILL_CANONICAL:
        return _SKILL_CANONICAL[lower]

    # Fuzzy match for close variants (high threshold to avoid false positives)
    match = process.extractOne(
        lower,
        list(_SKILL_CANONICAL.keys()),
        scorer=fuzz.ratio,
        score_cutoff=90,
    )
    if match:
        return _SKILL_CANONICAL[match[0]]

    # Default: title-case
    return cleaned.title()


def normalize_skills_list(raw_skills: list[str]) -> list[str]:
    """Normalize and deduplicate a list of skill names."""
    seen: set[str] = set()
    result: list[str] = []
    for skill in raw_skills:
        canonical = normalize_skill(skill)
        if canonical and canonical.lower() not in seen:
            seen.add(canonical.lower())
            result.append(canonical)
    return result


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def normalize_name(raw: str) -> Optional[str]:
    """
    Normalize a person's name: title-case, clean whitespace.
    """
    if not raw or not raw.strip():
        return None
    # Remove extra whitespace
    cleaned = " ".join(raw.split())
    # Title-case each word
    return cleaned.title()


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------

_EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def normalize_email(raw: str) -> Optional[str]:
    """
    Normalize an email: lowercase, validate format.

    Returns None if the email is invalid.
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip().lower()
    if _EMAIL_REGEX.match(cleaned):
        return cleaned

    logger.debug("Invalid email: %s", raw)
    return None


def normalize_emails_list(raw_emails: list[str]) -> list[str]:
    """Normalize and deduplicate a list of emails."""
    seen: set[str] = set()
    result: list[str] = []
    for email in raw_emails:
        normalized = normalize_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


# ---------------------------------------------------------------------------
# URL / link normalization
# ---------------------------------------------------------------------------

def normalize_url(raw: str) -> Optional[str]:
    """Basic URL normalization: strip whitespace, ensure scheme."""
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned


# ---------------------------------------------------------------------------
# Regex patterns for extraction from unstructured text
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?"  # optional country code
    r"(?:\(?\d{2,4}\)?[-.\s]?)"  # area code
    r"(?:\d{2,4}[-.\s]?){1,3}"  # local number
    r"\d{1,4}"                  # last group
)

LINKEDIN_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+/?",
    re.IGNORECASE,
)

GITHUB_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+/?",
    re.IGNORECASE,
)

# Common skills that might appear in text
SKILL_KEYWORDS: list[str] = list(_SKILL_CANONICAL.keys())
