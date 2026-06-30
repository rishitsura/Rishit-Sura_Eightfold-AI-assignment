from fpdf import FPDF
from fpdf.enums import XPos, YPos

class PDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 16)
        self.cell(0, 10, 'Multi-Source Candidate Data Transformer', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.set_font('helvetica', 'I', 11)
        self.cell(0, 10, 'Design One-Pager - Eightfold Engineering Intern Assignment', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

    def chapter_title(self, title):
        self.set_font('helvetica', 'B', 14)
        self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.ln(2)

    def chapter_body(self, body):
        self.set_font('helvetica', '', 11)
        self.multi_cell(0, 6, body)
        self.ln(4)

pdf = PDF()
pdf.add_page()

pdf.chapter_title('1. The Problem')
pdf.chapter_body(
    "Eightfold ingests candidate information from structured sources (Recruiter CSV, ATS JSON, GitHub API) "
    "and unstructured sources (Resumes, Recruiter Notes). Downstream systems require one clean, canonical profile "
    "per candidate with normalized formats, deduplicated entries, and detailed provenance indicating source reliability."
)

pdf.chapter_title('2. Pipeline Architecture')
pdf.chapter_body(
    "The deterministic, rule-based pipeline consists of six stages:\n\n"
    "1. Detect & Extract: Source-specific extractors parse inputs into unified CandidateFragment objects.\n"
    "2. Normalize: Phones map to E.164, locations extract city/country, degrees map to standard formats.\n"
    "3. Merge: Identities match via primary (email) and secondary (name + phone) keys. Scalar fields take the most "
    "reliable source's value. Array fields (Skills, Experience, Education) merge via fuzzy matching deduplication.\n"
    "4. Confidence Scoring: Each profile receives an overall confidence score based on source weights (ATS > CSV > Resume) "
    "and cross-source agreement on critical fields.\n"
    "5. Project: Runtime JSON configurations dictate field selection, JSON structure mapping, and missing-value policies "
    "(null vs omit vs error).\n"
    "6. Validate: The final payload conforms rigidly to the requested downstream schema."
)

pdf.chapter_title('3. Resolution Heuristics')
pdf.chapter_body(
    "- Identity Merging: Uses a multi-pass approach matching overlapping emails, then phone/name heuristics.\n"
    "- Experience/Education Dedup: Employs rapidfuzz matching (threshold > 75%) on institution and company names, "
    "along with date range intersections.\n"
    "- Unstructured Parsing: Regex-driven contextual extraction handles phrases like 'works as a PM at Flipkart' "
    "to properly anchor both title and company, minimizing hallucinations."
)

pdf.chapter_title('4. Future Enhancements (Descoped for MVP)')
pdf.chapter_body(
    "- ML-based sequence tagging (NER) for free-text sections, complementing regex patterns.\n"
    "- Parallelized I/O streaming for processing gigabyte-scale exports.\n"
    "- Direct database sync/upsert capabilities beyond JSON file generation."
)

pdf.output('STEP_1_ONE_PAGER.pdf')
print("PDF created successfully.")
