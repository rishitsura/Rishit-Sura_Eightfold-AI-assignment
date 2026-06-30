"""Tests for source extractors."""

import json
import os
import tempfile

import pytest

from transformer.extractors.csv_extractor import CSVExtractor
from transformer.extractors.json_extractor import JSONExtractor
from transformer.extractors.notes_extractor import NotesExtractor
from transformer.extractors.resume_extractor import ResumeExtractor
from transformer.models import SourceType


class TestCSVExtractor:
    """CSV extractor tests."""

    def test_basic_extraction(self, tmp_path):
        csv_content = "name,email,phone,current_company,title\n" \
                      "John Doe,john@example.com,+1-555-0100,Acme Inc,Engineer\n"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        extractor = CSVExtractor()
        fragments = extractor.extract(str(csv_file))

        assert len(fragments) == 1
        assert fragments[0].full_name == "John Doe"
        assert "john@example.com" in fragments[0].emails
        assert fragments[0].source_type == SourceType.RECRUITER_CSV

    def test_alternate_column_names(self, tmp_path):
        csv_content = "full_name,email_address,telephone,company,position\n" \
                      "Jane Smith,jane@test.com,555-0200,BigCo,Manager\n"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        extractor = CSVExtractor()
        fragments = extractor.extract(str(csv_file))

        assert len(fragments) == 1
        assert fragments[0].full_name == "Jane Smith"
        assert "jane@test.com" in fragments[0].emails

    def test_empty_csv(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("name,email\n")

        extractor = CSVExtractor()
        fragments = extractor.extract(str(csv_file))

        assert len(fragments) == 0

    def test_missing_file(self):
        extractor = CSVExtractor()
        fragments = extractor.extract("/nonexistent/file.csv")
        assert len(fragments) == 0

    def test_multiple_rows(self, tmp_path):
        csv_content = "name,email,phone,current_company,title\n" \
                      "Person One,one@test.com,555-0001,Co1,Dev\n" \
                      "Person Two,two@test.com,555-0002,Co2,PM\n" \
                      "Person Three,three@test.com,555-0003,Co3,Designer\n"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        extractor = CSVExtractor()
        fragments = extractor.extract(str(csv_file))

        assert len(fragments) == 3

    def test_skills_column(self, tmp_path):
        csv_content = "name,email,skills\n" \
                      "Dev Person,dev@test.com,\"Python, JavaScript, Docker\"\n"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        extractor = CSVExtractor()
        fragments = extractor.extract(str(csv_file))

        assert len(fragments) == 1
        assert "Python" in fragments[0].skills
        assert "JavaScript" in fragments[0].skills

    def test_first_last_name(self, tmp_path):
        csv_content = "first_name,last_name,email\n" \
                      "John,Doe,john@test.com\n"
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        extractor = CSVExtractor()
        fragments = extractor.extract(str(csv_file))

        assert len(fragments) == 1
        assert fragments[0].full_name == "John Doe"


class TestJSONExtractor:
    """ATS JSON extractor tests."""

    def test_basic_extraction(self, tmp_path):
        data = {
            "candidates": [
                {
                    "candidateName": "John Doe",
                    "emailAddress": "john@example.com",
                    "currentTitle": "Engineer",
                }
            ]
        }
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        extractor = JSONExtractor()
        fragments = extractor.extract(str(json_file))

        assert len(fragments) == 1
        assert fragments[0].full_name == "John Doe"
        assert fragments[0].source_type == SourceType.ATS_JSON

    def test_single_object(self, tmp_path):
        data = {
            "full_name": "Solo Candidate",
            "email": "solo@test.com",
        }
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        extractor = JSONExtractor()
        fragments = extractor.extract(str(json_file))

        assert len(fragments) == 1
        assert fragments[0].full_name == "Solo Candidate"

    def test_array_of_candidates(self, tmp_path):
        data = [
            {"name": "Person A", "email": "a@test.com"},
            {"name": "Person B", "email": "b@test.com"},
        ]
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        extractor = JSONExtractor()
        fragments = extractor.extract(str(json_file))

        assert len(fragments) == 2

    def test_nested_experience(self, tmp_path):
        data = {
            "candidates": [{
                "name": "Exp Person",
                "email": "exp@test.com",
                "workExperience": [
                    {
                        "org": "Company A",
                        "role": "Engineer",
                        "startDate": "2020-01",
                        "endDate": "2022-06",
                    }
                ]
            }]
        }
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        extractor = JSONExtractor()
        fragments = extractor.extract(str(json_file))

        assert len(fragments) == 1
        assert len(fragments[0].experience) == 1
        assert fragments[0].experience[0].company == "Company A"

    def test_skills_as_objects(self, tmp_path):
        data = {
            "name": "Skill Person",
            "email": "skill@test.com",
            "skills": [
                {"name": "Python", "level": "expert"},
                {"name": "Java", "level": "intermediate"},
            ],
        }
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(data))

        extractor = JSONExtractor()
        fragments = extractor.extract(str(json_file))

        assert len(fragments) == 1
        assert "Python" in fragments[0].skills
        assert "Java" in fragments[0].skills

    def test_missing_file(self):
        extractor = JSONExtractor()
        fragments = extractor.extract("/nonexistent/file.json")
        assert len(fragments) == 0


class TestNotesExtractor:
    """Recruiter notes extractor tests."""

    def test_basic_extraction(self, tmp_path):
        notes = """Candidate: John Smith

Spoke with John on 2024-01-15. He is currently at TechCo as a Senior Developer.
Based in New York, USA. Has 5 years of experience in software development.

Skilled in Python, JavaScript, and React. Very strong communicator.

john.smith@email.com
Phone: +1-555-0100
"""
        notes_file = tmp_path / "notes.txt"
        notes_file.write_text(notes)

        extractor = NotesExtractor()
        fragments = extractor.extract(str(notes_file))

        assert len(fragments) >= 1
        frag = fragments[0]
        assert frag.source_type == SourceType.RECRUITER_NOTES
        assert "john.smith@email.com" in frag.emails

    def test_multiple_candidates(self, tmp_path):
        notes = """Candidate: Person A
person.a@test.com
Currently at Company A as a Developer.

---

Candidate: Person B
person.b@test.com
Works at Company B as a Designer.
"""
        notes_file = tmp_path / "notes.txt"
        notes_file.write_text(notes)

        extractor = NotesExtractor()
        fragments = extractor.extract(str(notes_file))

        assert len(fragments) == 2

    def test_empty_notes(self, tmp_path):
        notes_file = tmp_path / "empty.txt"
        notes_file.write_text("")

        extractor = NotesExtractor()
        fragments = extractor.extract(str(notes_file))

        assert len(fragments) == 0


class TestResumeExtractor:
    """Resume extractor tests (text-based)."""

    def test_text_resume(self, tmp_path):
        resume = """JOHN DOE
john.doe@email.com | +1-555-0100
San Francisco, CA, USA
LinkedIn: https://linkedin.com/in/johndoe

SUMMARY
Experienced software engineer with 5 years of experience.

EXPERIENCE

Senior Engineer at TechCorp
January 2020 - Present
• Led team of 5 engineers
• Built scalable microservices

EDUCATION

Stanford University
Bachelor of Science in Computer Science
2015

SKILLS
Python, JavaScript, React, AWS, Docker
"""
        resume_file = tmp_path / "resume.txt"
        resume_file.write_text(resume)

        extractor = ResumeExtractor()
        fragments = extractor.extract(str(resume_file))

        assert len(fragments) == 1
        frag = fragments[0]
        assert frag.source_type == SourceType.RESUME
        assert "john.doe@email.com" in frag.emails
        assert frag.full_name is not None

    def test_missing_file(self):
        extractor = ResumeExtractor()
        fragments = extractor.extract("/nonexistent/resume.pdf")
        assert len(fragments) == 0
