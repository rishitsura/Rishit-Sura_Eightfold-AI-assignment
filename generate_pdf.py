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
    "The deterministic, rule-based pipeline consists of advanced stages to guarantee data integrity:\n\n"
    "1. Detect & Extract: Source-specific extractors parse inputs (CSV, JSON, GitHub, Resumes, Notes) into CandidateFragment objects.\n"
    "2. Normalize: Phones map to E.164, locations extract city/country, degrees map to standard formats.\n"
    "3. Conflict Analysis (CACS): A pre-merge analytical pass detects contradictory data across sources. It flags discrepancies for confidence penalties, stratifies skills by recency (Confirmed, Current, Historical), and generates a fully traceable Lineage IR.\n"
    "4. Merge: Identities match via primary keys. Scalar fields take the most reliable source's value. Array fields merge via rapidfuzz deduplication.\n"
    "5. Confidence Scoring: Profiles receive a score based on source weights and cross-source agreement, adjusted by CACS penalties.\n"
    "6. Project & Validate: Runtime JSON configurations dictate the final structure and missing-value policies before rigid schema validation."
)

pdf.chapter_title('3. Resolution Heuristics')
pdf.chapter_body(
    "- Identity Merging: Uses a multi-pass approach matching overlapping emails, then phone/name heuristics.\n"
    "- Experience/Education Dedup: Employs rapidfuzz matching (threshold > 75%) on institution and company names, "
    "along with date range intersections.\n"
    "- Unstructured Parsing: Regex-driven contextual extraction handles phrases like 'works as a PM at Flipkart' "
    "to properly anchor both title and company, minimizing hallucinations."
)

pdf.chapter_title('4. User Interfaces')
pdf.chapter_body(
    "- Command Line Interface (CLI): The primary robust engine for batch processing profiles.\n"
    "- Web UI (Streamlit): An interactive dashboard for evaluators to upload candidate files and view the resulting canonical JSON instantaneously."
)

pdf.output('Eightfold_Candidate_Transformer_Design.pdf')
print("PDF created successfully.")
