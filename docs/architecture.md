# Architecture Documentation

**Project:** Multi-Source Candidate Data Transformer  
**Author:** Rishit Sura  
**Last Updated:** 2026-06-30

---

## Overview

This document captures the complete system architecture of the candidate data transformer pipeline. The pipeline ingests candidate data from up to 5 different source types, merges them into a single canonical profile, and projects the output through a configurable runtime schema — all deterministically, without any LLM or ML inference.

### Design Philosophy

- **Deterministic**: Same inputs always produce the same output. No randomness, no LLMs.
- **Explainable**: Every field in the output is traceable back to a specific source and extraction method via `provenance` records.
- **Conflict-Aware**: Applies robust conflict analysis before merging to avoid silent conflict masking. Read more in the [Conflict Analysis & Lineage Architecture](./conflict_analysis.md).
- **Robust**: A missing, empty, or malformed source degrades gracefully — the pipeline never crashes due to a bad input.
- **Configurable**: A runtime JSON `OutputConfig` reshapes the output without any code changes.

---

## Table of Contents

1. [Full System Architecture](#1-full-system-architecture)
2. [Data Model Relationships](#2-data-model-relationships)
3. [Identity Matching & Merge Decision Tree](#3-identity-matching--merge-decision-tree)
4. [Source Priority & Reliability Weights](#4-source-priority--reliability-weights)

---

## 1. Full System Architecture

This diagram shows the end-to-end flow from raw input files through all 8 pipeline stages to the final JSON output.

**Key stages:**
- **Stages 1**: `detect.py` — classify each input file by source type
- **Stages 2–3**: `extractors/` — parse raw text/data into `CandidateFragment` objects
- **Stages 4–5**: `merger.py` + `normalizers.py` — group, normalize, and merge fragments into a `CanonicalProfile`
- **Stage 6**: `confidence.py` — assign a reliability score `[0.0, 1.0]` to each profile
- **Stage 7**: `projector.py` — reshape the canonical profile per the output `OutputConfig`
- **Stage 8**: `validator.py` — type-check the projected output and report errors/warnings

> ⚠️ **Known Issue** — The `GitHubExtractor` sets `years_experience` to the number of years since the GitHub account was created. This is not a proxy for real work experience and should be treated as metadata only.

```mermaid
flowchart TD
    subgraph INPUTS["📥 Input Sources"]
        direction TB
        CSV["📄 Recruiter CSV\n.csv · column alias matching\nutf-8 / latin-1 encoding fallback"]
        ATS["🗃️ ATS JSON Blob\ncamelCase + snake_case _FIELD_MAP\nsingle object, array, or wrapped"]
        GH["🐙 GitHub Profile\nURL / username / .txt file\n2 REST calls: /users + /repos"]
        RES["📋 Resume\n.pdf via pdfplumber · .docx via python-docx · .txt\nregex section-header detection"]
        NOTES["📝 Recruiter Notes\n.txt · trigger-phrase NLP\nmulti-block splitting on --- or Candidate:"]
    end

    subgraph DETECT["🔍 Stage 1 · detect.py\nSource Type Detection"]
        DET["detect_source_type\nfile extension lookup\nexplicit --source-type CLI override"]
    end

    subgraph EXTRACT["⚙️ Stages 2–3 · extractors/\nParse & Extract → CandidateFragment"]
        CSVE["CSVExtractor\n_COLUMN_ALIASES dict\nmulti-value cells split on comma/semicolon"]
        ATSE["JSONExtractor\n_FIELD_MAP dict\nwrapper key detection candidates applicants data\nexp + edu arrays fully parsed"]
        GHE["GitHubExtractor ⚠️\nyears_exp = account age not real experience\nrepo languages → skills list\nblog → portfolio link"]
        RESE["ResumeExtractor\n_split_sections by regex section headers\ndate-anchored experience parsing\ndegree regex education parsing\ncategory-prefix skill stripping"]
        NOTESE["NotesExtractor\ncombo pattern: works as Title at Company\nfallback: _COMPANY_PATTERN + _TITLE_PATTERN\nmulti-block file support"]
        FRAG["CandidateFragment\nraw · unnormalized · partial\nsource_type · source_file\nfull_name · emails · phones\nlocation · links · headline\nyears_experience · skills\nexperience · education"]
    end

    subgraph MERGE["🔄 Stage 4-6 · normalizers.py, conflict_analyzer.py, merger.py"]
        direction LR
        N["normalizers.py\nphones → E.164 via phonenumbers\ndates → YYYY-MM via dateparser\ncountries → ISO-3166 alpha-2 via pycountry\nskills → canonical via 120-entry dict + fuzzy score_cutoff=90\nemails → lowercase + regex validation\nnames → title-case + whitespace clean"]
        G["Identity Grouping\nPrimary: exact email\nSecondary: fuzzy name + phone digits"]
        C["Conflict Analyzer\nScalar Divergence & Skill Jaccard\nGenerates Lineage IR & Conflict Flags"]
        R["Conflict-Aware Field Merge\nScalars: Priority based\nArrays: Union dedup\nExperience: Fuzzy merge\nSkills: Temporal Stratification"]
        CANON["CanonicalProfile\ncandidate_id UUID\nfull_name · emails · phones\nlocation · links · headline\nyears_experience\nskills: Skill name + confidence + sources\nexperience · education\nprovenance: field + source + method\noverall_confidence 0.0–1.0"]
    end

    subgraph CONFIDENCE["📊 Stage 6 · confidence.py\nConfidence Scoring"]
        CS["ConfidenceScorer.score\nPer-field: best_source_weight + agreement_bonus\nField weights: full_name 1.0 · emails 0.9 · experience 0.9\nskills 0.8 · phones 0.7 · education 0.6 · location 0.5\nyears_experience 0.5 · headline 0.4 · links 0.3\nCoverage ratio multiplier: 0.7 + 0.3 × filled/total\nSource reliability: ATS 0.90 · CSV 0.85 · Resume 0.80\nGitHub 0.75 · Notes 0.60"]
    end

    subgraph PROJECT["🎛️ Stage 7 · projector.py\nConfigurable Output Projection"]
        P["Projector.project\nPath expressions:\n  field → direct access\n  location.city → nested\n  emails[0] → array index\n  skills[].name → array map\nPer-field normalize: E164 canonical lowercase titlecase\nMissing policy: null · omit · error\nToggles: include_confidence · include_provenance"]
        CFG["OutputConfig JSON\nfields: FieldConfig path from type required normalize\non_missing: null omit error\ninclude_confidence bool\ninclude_provenance bool"]
    end

    subgraph VALIDATE["✅ Stage 8 · validator.py\nOutput Validation"]
        V["Validator\nType checking: string · number · string[] · boolean\nRequired field presence check\nDefault schema full validation\nValidationResult: valid bool · errors · warnings"]
    end

    subgraph OUTPUT["📤 Output Surface"]
        CLI["cli.py · Click-based CLI\n--input -i multiple files\n--config -c output config JSON\n--output -o file or stdout\n--github-token env GITHUB_TOKEN\n--source-type override\n--verbose --pretty"]
        JOUT["PipelineResult\ncanonical: CanonicalProfile\nprojected: dict JSON-ready\nvalidation: ValidationResult\nwarnings: list of str"]
    end

    CSV & ATS & GH & RES & NOTES --> DETECT
    DETECT --> DET
    DET --> CSVE & ATSE & GHE & RESE & NOTESE
    CSVE & ATSE & GHE & RESE & NOTESE --> FRAG
    FRAG --> G
    N --> R
    G --> R
    R --> CANON
    CANON --> CS
    CS --> P
    CFG --> P
    P --> V
    V --> JOUT
    JOUT --> CLI
```

---

## 2. Data Model Relationships

This class diagram shows the Pydantic data models used throughout the pipeline and how they relate to each other.

**Key model types:**
- `CandidateFragment` — raw, partial, unnormalized data from a single source
- `CanonicalProfile` — the fully merged and normalized internal representation
- `OutputConfig` / `FieldConfig` — runtime configuration that reshapes the output
- `PipelineResult` — the final wrapper returned by the pipeline

```mermaid
classDiagram
    direction LR

    class CandidateFragment {
        +SourceType source_type
        +str source_file
        +Optional~str~ full_name
        +list~str~ emails
        +list~str~ phones
        +Optional~Location~ location
        +Optional~Links~ links
        +Optional~str~ headline
        +Optional~float~ years_experience
        +list~str~ skills
        +list~Experience~ experience
        +list~Education~ education
        +dict raw_extras
    }

    class CanonicalProfile {
        +str candidate_id
        +Optional~str~ full_name
        +list~str~ emails
        +list~str~ phones
        +Optional~Location~ location
        +Optional~Links~ links
        +Optional~str~ headline
        +Optional~float~ years_experience
        +list~Skill~ skills
        +list~Experience~ experience
        +list~Education~ education
        +list~Provenance~ provenance
        +float overall_confidence
    }

    class Skill {
        +str name
        +float confidence
        +list~str~ sources
    }

    class Experience {
        +Optional~str~ company
        +Optional~str~ title
        +Optional~str~ start
        +Optional~str~ end
        +Optional~str~ summary
    }

    class Education {
        +Optional~str~ institution
        +Optional~str~ degree
        +Optional~str~ field
        +Optional~int~ end_year
    }

    class Location {
        +Optional~str~ city
        +Optional~str~ region
        +Optional~str~ country
    }

    class Links {
        +Optional~str~ linkedin
        +Optional~str~ github
        +Optional~str~ portfolio
        +list~str~ other
    }

    class Provenance {
        +str field
        +str source
        +str method
    }

    class OutputConfig {
        +list~FieldConfig~ fields
        +bool include_confidence
        +bool include_provenance
        +OnMissing on_missing
    }

    class FieldConfig {
        +str path
        +Optional~str~ from_path
        +str type
        +bool required
        +Optional~str~ normalize
    }

    class PipelineResult {
        +CanonicalProfile canonical
        +dict projected
        +ValidationResult validation
        +list~str~ warnings
    }

    class ValidationResult {
        +bool valid
        +list~ValidationError~ errors
        +list~ValidationError~ warnings
    }

    CandidateFragment --> Location
    CandidateFragment --> Links
    CandidateFragment --> Experience
    CandidateFragment --> Education

    CanonicalProfile --> Location
    CanonicalProfile --> Links
    CanonicalProfile --> Skill
    CanonicalProfile --> Experience
    CanonicalProfile --> Education
    CanonicalProfile --> Provenance

    OutputConfig --> FieldConfig
    PipelineResult --> CanonicalProfile
    PipelineResult --> ValidationResult

    CandidateFragment ..> CanonicalProfile : merged into by CandidateMerger
    CanonicalProfile ..> PipelineResult : projected + validated into
    OutputConfig ..> PipelineResult : shapes output
```

---

## 3. Identity Matching & Merge Decision Tree

This diagram shows the exact logic used by `merger.py` to decide whether two `CandidateFragment` objects belong to the same person, and how conflicts are resolved once they are grouped.

**Identity matching rules (in priority order):**
1. **Primary** — two fragments share at least one email address (exact, lowercased match)
2. **Secondary** — names are fuzzy-match ≥80% AND their phone digit-strings overlap (last 10 digits)

**Conflict resolution** applies after grouping, per field type:
- Scalar fields (`full_name`, `headline`, etc.) → highest-priority source wins
- Array fields (`emails`, `phones`) → union with exact deduplication
- Skills → canonical union, per-skill source list tracked for confidence
- Experience / Education → fuzzy dedup by company/institution name ≥75% + overlapping date ranges
- Location → most-complete record (most non-null fields) wins

```mermaid
flowchart TD
    A["All CandidateFragments"] --> B["Take next unassigned fragment"]
    B --> C{"Does any existing group\nshare at least one email?"}
    C -- Yes --> D["Assign to that group\n✅ Primary key match"]
    C -- No --> E{"Name fuzzy ratio ≥ 80%\nAND phone digit-string overlap?"}
    E -- Yes --> F["Assign to that group\n✅ Secondary key match"]
    E -- No --> G["Create a new group\n🆕 New unique identity"]
    D --> H["_merge_group"]
    F --> H
    G --> H

    H --> I{"Field type?"}

    I -- Scalar --> J["Pick highest-priority source\nATS › CSV › Resume › GitHub › Notes"]
    I -- Array emails phones --> K["Union + exact deduplication\nlowercase normalization"]
    I -- Skills --> L["Canonical union\ntrack sources per skill\nfor per-skill confidence"]
    I -- Experience / Education --> M["Fuzzy dedup: company/institution ≥75%\nmerge overlapping date ranges"]
    I -- Location --> N["Most-complete record wins\ncounts non-null fields"]

    J & K & L & M & N --> O["Write Provenance record\nfield + source + method"]
    O --> P["CanonicalProfile assembled"]
    P --> Q["ConfidenceScorer.score\nbest_source_weight + agreement_bonus\n× coverage_ratio multiplier"]
```

---

## 4. Source Priority & Reliability Weights

This quadrant chart visualizes each source by its **merge priority** (x-axis: used for conflict resolution) and its **reliability weight** (y-axis: used in confidence scoring).

**Source reliability weights** (from `models.py`):

| Source | Priority Rank | Reliability Weight | Rationale |
|---|:---:|:---:|---|
| ATS JSON | 1 (highest) | 0.90 | Deliberately structured; highest data quality |
| Recruiter CSV | 2 | 0.85 | Structured export; slightly less authoritative |
| Resume | 3 | 0.80 | Candidate-authored; good coverage |
| GitHub Profile | 4 | 0.75 | Public signal; limited to public data |
| Recruiter Notes | 5 (lowest) | 0.60 | Free-text; most ambiguous to parse |

```mermaid
quadrantChart
    title Source Priority vs Reliability Weight
    x-axis Low Priority --> High Priority
    y-axis Low Reliability --> High Reliability
    quadrant-1 Gold Standard
    quadrant-2 Low Merge Weight
    quadrant-3 Least Trusted
    quadrant-4 Verify Against Others
    ATS JSON: [0.95, 0.90]
    Recruiter CSV: [0.80, 0.85]
    Resume: [0.65, 0.80]
    GitHub Profile: [0.50, 0.75]
    Recruiter Notes: [0.20, 0.60]
```

