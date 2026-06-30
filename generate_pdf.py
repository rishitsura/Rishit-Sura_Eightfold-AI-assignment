from fpdf import FPDF
from fpdf.enums import XPos, YPos

class PDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 16)
        self.cell(0, 10, 'System Architecture & Design Document', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.set_font('helvetica', 'I', 11)
        self.cell(0, 10, 'Multi-Source Candidate Data Transformer Pipeline', new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
        self.ln(5)

    def chapter_title(self, title):
        self.set_font('helvetica', 'B', 14)
        self.cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
        self.ln(2)

    def chapter_body(self, body):
        self.set_font('helvetica', '', 11)
        self.multi_cell(0, 6, body)
        self.ln(4)
        
    def draw_architecture_diagram(self):
        self.ln(2)
        stages = ["Detect", "Extract", "Normalize", "CACS", "Merge", "Score", "Project", "Validate"]
        
        box_w = 21
        box_h = 10
        gap = 3
        
        total_w = (box_w * len(stages)) + (gap * (len(stages) - 1))
        start_x = (210 - total_w) / 2 # A4 width is 210mm
        
        current_x = start_x
        current_y = self.get_y()
        
        self.set_font('helvetica', 'B', 8)
        self.set_draw_color(50, 50, 50)
        self.set_fill_color(240, 240, 240)
        
        for i, stage in enumerate(stages):
            self.set_xy(current_x, current_y)
            self.cell(box_w, box_h, stage, border=1, align='C', fill=True)
            
            if i < len(stages) - 1:
                arrow_x = current_x + box_w
                arrow_y = current_y + (box_h / 2)
                self.line(arrow_x, arrow_y, arrow_x + gap, arrow_y)
                self.line(arrow_x + gap - 1, arrow_y - 1, arrow_x + gap, arrow_y)
                self.line(arrow_x + gap - 1, arrow_y + 1, arrow_x + gap, arrow_y)
                
            current_x += box_w + gap
            
        self.set_y(current_y + box_h + 8)

pdf = PDF()
pdf.add_page()

pdf.chapter_title('1. Problem Statement & Objective')
pdf.chapter_body(
    "The candidate data ingestion pipeline aggregates records from disparate structured (ATS, CSV, GitHub) and unstructured (Resumes, Notes) origins. The primary objective is to design a deterministic ETL (Extract, Transform, Load) pipeline that standardizes schema variability, resolves conflicting data points across overlapping sources, and emits a single canonical profile. Downstream consumers require high data fidelity, explicit provenance tracking, and configurable payload projections."
)

pdf.chapter_title('2. System Architecture')
pdf.draw_architecture_diagram()
pdf.chapter_body(
    "The pipeline operates as a stateless, multi-stage DAG to ensure idempotency and determinism:\n\n"
    "1. Ingestion & Extraction: Parsers ingest payloads and map them to a unified internal representation (CandidateFragment).\n"
    "2. Normalization: Applies global formatting standards (E.164 for telephony, ISO-3166 for locales, canonical mappings for tech stacks).\n"
    "3. Conflict Analysis (CACS): A pre-merge analytical heuristic that detects data divergence, applies temporal recency stratification to skills, and generates an auditable Lineage IR.\n"
    "4. Merge & Deduplication: Resolves identity collisions via primary key matching. Array fields are deduplicated using Levenshtein distance metrics (rapidfuzz).\n"
    "5. Confidence Scoring: Aggregates source-level reliability weights and cross-validation bonuses to assign a confidence index [0.0 - 1.0].\n"
    "6. Projection: Hydrates the final canonical payload according to dynamic downstream JSON schemas."
)

pdf.chapter_title('3. Core Resolution Heuristics')
pdf.chapter_body(
    "- Identity Resolution: Evaluates overlapping candidate entities using primary keys (email) and secondary fallback permutations (normalized name + phone).\n"
    "- Array Deduplication: Employs fuzzy string matching (threshold > 75%) coupled with date range intersections to merge overlapping experience and education records.\n"
    "- Unstructured Contextual Parsing: Utilizes strict regex boundaries and contextual anchors rather than stochastic LLMs, drastically reducing hallucination risk when parsing free-text roles and institutions."
)

pdf.chapter_title('4. Interfaces & Extensibility')
pdf.chapter_body(
    "- Command Line Interface (CLI): Engineered for batch processing, CI/CD integration, and high-throughput execution.\n"
    "- Web UI (Streamlit): Provides an interactive dashboard for QA and product evaluators to visually validate merging heuristics and projected schemas in real-time."
)

pdf.output('Eightfold_Candidate_Transformer_Design.pdf')
print("PDF created successfully.")
