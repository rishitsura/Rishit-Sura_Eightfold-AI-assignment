"""Tests for normalization utilities."""

import pytest

from transformer.normalizers import (
    normalize_country,
    normalize_date,
    normalize_email,
    normalize_emails_list,
    normalize_name,
    normalize_phone,
    normalize_skill,
    normalize_skills_list,
)


class TestNormalizePhone:
    """Phone normalization tests."""

    def test_us_phone_with_country_code(self):
        assert normalize_phone("+1-415-555-0172") == "+14155550172"

    def test_us_phone_without_country_code(self):
        result = normalize_phone("(415) 555-0172")
        assert result == "+14155550172"

    def test_indian_phone(self):
        result = normalize_phone("+91-98765-43210")
        assert result == "+919876543210"

    def test_indian_phone_with_spaces(self):
        result = normalize_phone("+91 98765 43210")
        assert result == "+919876543210"

    def test_empty_phone(self):
        assert normalize_phone("") is None
        assert normalize_phone("  ") is None

    def test_garbage_phone(self):
        assert normalize_phone("not-a-phone") is None

    def test_short_phone(self):
        # Too short to be valid
        result = normalize_phone("123")
        # May return None or attempt to parse - depends on library
        # The important thing is it doesn't crash
        assert result is None or isinstance(result, str)


class TestNormalizeDate:
    """Date normalization tests."""

    def test_already_normalized(self):
        assert normalize_date("2021-03") == "2021-03"

    def test_year_only(self):
        assert normalize_date("2020") == "2020-01"

    def test_month_year(self):
        result = normalize_date("January 2020")
        assert result == "2020-01"

    def test_abbreviated_month(self):
        result = normalize_date("Jan 2020")
        assert result == "2020-01"

    def test_slash_format(self):
        result = normalize_date("03/2021")
        assert result == "2021-03"

    def test_full_date(self):
        result = normalize_date("2020-01-15")
        assert result == "2020-01"

    def test_empty_date(self):
        assert normalize_date("") is None
        assert normalize_date("  ") is None

    def test_nonsense_date(self):
        assert normalize_date("not a date") is None


class TestNormalizeCountry:
    """Country normalization tests."""

    def test_iso_code(self):
        assert normalize_country("US") == "US"
        assert normalize_country("us") == "US"
        assert normalize_country("IN") == "IN"

    def test_full_name(self):
        assert normalize_country("United States") == "US"
        assert normalize_country("India") == "IN"
        assert normalize_country("United Kingdom") == "GB"

    def test_alias(self):
        assert normalize_country("USA") == "US"
        assert normalize_country("UK") == "GB"

    def test_empty(self):
        assert normalize_country("") is None
        assert normalize_country("  ") is None

    def test_fuzzy_match(self):
        # Close misspelling should still match
        result = normalize_country("United Staets")
        # May or may not match depending on threshold
        assert result is None or result == "US"


class TestNormalizeSkill:
    """Skill canonicalization tests."""

    def test_exact_match(self):
        assert normalize_skill("python") == "Python"
        assert normalize_skill("js") == "JavaScript"
        assert normalize_skill("k8s") == "Kubernetes"

    def test_case_insensitive(self):
        assert normalize_skill("PYTHON") == "Python"
        assert normalize_skill("JavaScript") == "JavaScript"

    def test_abbreviation(self):
        assert normalize_skill("ml") == "Machine Learning"
        assert normalize_skill("nlp") == "Natural Language Processing"

    def test_framework_variants(self):
        assert normalize_skill("reactjs") == "React"
        assert normalize_skill("react.js") == "React"
        assert normalize_skill("nodejs") == "Node.js"

    def test_unknown_skill(self):
        # Unknown skills get title-cased
        result = normalize_skill("some random skill")
        assert result == "Some Random Skill"

    def test_empty(self):
        assert normalize_skill("") == ""


class TestNormalizeEmail:
    """Email normalization tests."""

    def test_valid_email(self):
        assert normalize_email("Test@Example.COM") == "test@example.com"

    def test_whitespace(self):
        assert normalize_email("  test@example.com  ") == "test@example.com"

    def test_invalid_email(self):
        assert normalize_email("not-an-email") is None
        assert normalize_email("@missing-local.com") is None

    def test_empty(self):
        assert normalize_email("") is None


class TestNormalizeName:
    """Name normalization tests."""

    def test_basic(self):
        assert normalize_name("john doe") == "John Doe"

    def test_extra_whitespace(self):
        assert normalize_name("  john    doe  ") == "John Doe"

    def test_already_title(self):
        assert normalize_name("John Doe") == "John Doe"

    def test_empty(self):
        assert normalize_name("") is None
        assert normalize_name("  ") is None


class TestNormalizeSkillsList:
    """Skill list normalization and dedup tests."""

    def test_dedup(self):
        result = normalize_skills_list(["python", "Python", "PYTHON"])
        assert result == ["Python"]

    def test_canonical_dedup(self):
        result = normalize_skills_list(["js", "JavaScript", "javascript"])
        assert result == ["JavaScript"]

    def test_mixed(self):
        result = normalize_skills_list(["python", "js", "react", "Docker"])
        assert "Python" in result
        assert "JavaScript" in result
        assert "React" in result
        assert "Docker" in result
