# Multi-Source Candidate Data Transformer

**Eightfold Engineering Intern Assignment** — A pipeline that ingests candidate data from multiple structured and unstructured sources, merges them into a single canonical profile, and projects the output through a configurable schema.

## Usage

You can run the pipeline either via the Command Line Interface (CLI) or through the minimal Web UI.

### Option A: Web UI (Recommended for Demo)

A simple web interface built with Streamlit to easily upload files and view the projected JSON results.

```bash
# Start the web UI
streamlit run app.py
```
This will open `http://localhost:8501` in your browser. Upload your files (e.g. from `sample_inputs/`) and optionally a custom config to view the results instantly.

### Option B: Command Line Interface (CLI)

Transform candidate data from multiple sources (CSV, JSON, GitHub, resumes, recruiter notes) into a single canonical profile.

## Features

- **5 Source Types**: Recruiter CSV, ATS JSON, GitHub API, Resume (PDF/DOCX/TXT), Recruiter Notes
- **Deterministic**: Same inputs always produce the same output — no randomness, no LLMs
- **Explainable**: Every field is traceable via provenance records (source + method)
- **Configurable Output**: Runtime JSON config for field selection, remapping, normalization, and missing-value policy
- **Robust**: Missing or malformed sources degrade gracefully without crashing
- **Tested**: Unit tests, integration tests, and edge-case coverage

## Architecture

```
┌─────────┐   ┌─────────┐   ┌───────────┐   ┌───────────┐   ┌──────────┐   ┌───────┐   ┌───────────┐   ┌─────────┐   ┌──────────┐
│ Detect  │──▸│  Parse  │──▸│  Extract  │──▸│ Normalize │──▸│ Conflict │──▸│ Merge │──▸│ Confidence│──▸│ Project │──▸│ Validate │
└─────────┘   └─────────┘   └───────────┘   └───────────┘   └──────────┘   └───────┘   └───────────┘   └─────────┘   └──────────┘
```

1. **Detect** — identify source type from file extension / URL / explicit flag
2. **Parse/Extract** — source-specific extractors produce `CandidateFragment` objects
3. **Normalize** — phones → E.164, dates → YYYY-MM, countries → ISO-3166, skills → canonical names
4. **Conflict Analysis (CACS)** — detects contradictory data across sources (e.g., ATS vs Resume experience discrepancy), flags them for confidence penalties, and generates a fully traceable Lineage IR.
5. **Merge** — group by identity (email → name+phone fallback), resolve conflicts by source priority
6. **Confidence** — score each profile based on source reliability, cross-source agreement, field coverage, and apply Conflict penalties
7. **Project** — apply runtime output config (field selection, remapping, normalization)
8. **Validate** — check projected output against declared types and required fields

## Quick Start

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd eightfold-transformer

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Pipeline

#### Default output (full canonical schema):

```bash
python -m transformer.cli \
  --input sample_inputs/recruiter_export.csv \
  --input sample_inputs/ats_candidates.json \
  --input sample_inputs/resume_sample.txt \
  --input sample_inputs/recruiter_notes.txt \
  --source-type sample_inputs/resume_sample.txt resume \
  --output sample_outputs/default_output.json \
  --verbose
```

#### Custom config output:

```bash
python -m transformer.cli \
  --input sample_inputs/recruiter_export.csv \
  --input sample_inputs/ats_candidates.json \
  --config configs/custom_config.json \
  --output sample_outputs/custom_output.json \
  --verbose
```

#### Single source:

```bash
python -m transformer.cli \
  --input sample_inputs/recruiter_export.csv \
  --output result.json
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--input, -i` | Input file path(s). Multiple allowed. **Required.** |
| `--config, -c` | Output config JSON. Default: full canonical schema. |
| `--output, -o` | Output file path. Default: print to stdout. |
| `--github-token` | GitHub token for API calls (or set `GITHUB_TOKEN` env var). |
| `--source-type, -t` | Override source type: `--source-type file.txt resume` |
| `--verbose, -v` | Enable debug logging. |
| `--pretty` | Pretty-print JSON output (default: true). |

### Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_normalizers.py -v

# With coverage
python -m pytest tests/ -v --tb=short
```

## Project Structure

```
├── src/transformer/
│   ├── cli.py                  # CLI entrypoint (Click)
│   ├── pipeline.py             # Orchestrator
│   ├── models.py               # Pydantic data models
│   ├── detect.py               # Source type detection
│   ├── extractors/
│   │   ├── base.py             # Abstract base extractor
│   │   ├── csv_extractor.py    # Recruiter CSV
│   │   ├── json_extractor.py   # ATS JSON blob
│   │   ├── github_extractor.py # GitHub REST API
│   │   ├── resume_extractor.py # PDF / DOCX / TXT resume
│   │   └── notes_extractor.py  # Recruiter notes
│   ├── normalizers.py          # Phone, date, country, skill normalization
│   ├── merger.py               # Cross-source merge + conflict resolution
│   ├── confidence.py           # Confidence scoring
│   ├── projector.py            # Configurable output projection
│   └── validator.py            # Output schema validation
├── configs/
│   ├── default_schema.json     # Default output config
│   └── custom_config.json      # Example custom config
├── sample_inputs/              # Sample data for testing
├── sample_outputs/             # Generated outputs
├── tests/                      # pytest test suite
├── requirements.txt
└── setup.py
```

## Custom Output Configuration

The pipeline accepts a runtime JSON config that reshapes the output without code changes:

```json
{
  "fields": [
    { "path": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string", "required": true },
    { "path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164" },
    { "path": "city", "from": "location.city", "type": "string" },
    { "path": "skills", "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

### Config Options

| Key | Type | Description |
|-----|------|-------------|
| `fields[].path` | string | Output field name |
| `fields[].from` | string | Canonical source path (supports dot notation, array indexing) |
| `fields[].type` | string | Expected type: `string`, `number`, `string[]`, `boolean` |
| `fields[].required` | bool | Whether the field must be present |
| `fields[].normalize` | string | Normalization: `E164`, `canonical`, `lowercase`, `titlecase` |
| `include_confidence` | bool | Include `overall_confidence` in output |
| `include_provenance` | bool | Include `provenance` array in output |
| `on_missing` | string | Missing value policy: `null`, `omit`, `error` |

### Path Expressions

| Expression | Resolves To |
|------------|-------------|
| `full_name` | Direct field access |
| `location.city` | Nested field |
| `emails[0]` | First element of array |
| `skills[].name` | Map over array, extract `name` from each |

## Merge & Conflict Resolution

- **Identity matching**: email (primary), then name+phone (secondary)
- **Scalar fields**: highest-priority source wins (ATS > CSV > Resume > GitHub > Notes); ties broken by completeness
- **Array fields**: union with dedup (fuzzy for skills, exact for emails/phones)
- **Experience/Education**: dedup by key fields, merge missing details
- **Location**: most-complete record wins
- **Skills**: canonicalized names, per-skill confidence from multi-source agreement

## Confidence Scoring

- Source reliability weights: ATS (0.90), CSV (0.85), Resume (0.80), GitHub (0.75), Notes (0.60)
- Per-field score: best source weight + cross-source agreement bonus
- Overall: weighted average across fields × coverage ratio
- Score range: [0.0, 1.0]

## Assumptions & Descoped Items

### Assumptions
- Email is the primary identity key for cross-source matching
- Source reliability is static (could be learned from data in a production system)
- Skill canonicalization uses a predefined mapping + fuzzy matching (no ML)
- GitHub API is used without authentication by default (60 req/hr rate limit)

### Descoped (under time pressure)
- LinkedIn scraping (requires auth, ToS considerations)
- PDF resume parsing with complex layouts (tables, multi-column)
- ML-based entity extraction from unstructured text
- Batch processing with parallel I/O (currently sequential)
- Persistent storage / database integration
- Web UI (CLI is the primary interface)
