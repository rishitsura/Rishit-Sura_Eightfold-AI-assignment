# docs/

This folder contains technical documentation for the **Multi-Source Candidate Data Transformer** project.

## Contents

| File | Description |
|---|---|
| [architecture.md](./architecture.md) | Full system architecture with Mermaid diagrams: pipeline flow, data models, identity matching logic, and source priority weights |

## How to View the Diagrams

The `.md` files use **Mermaid** diagram syntax. You can render them in any of the following ways:

- **GitHub** — renders Mermaid automatically in any `.md` file when viewed on github.com
- **VS Code** — install the [Markdown Preview Mermaid Support](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) extension, then open the file and press `Cmd+Shift+V`
- **Mermaid Live Editor** — paste any diagram block into [mermaid.live](https://mermaid.live) for interactive editing
- **CLI** — use `mmdc` from the `@mermaid-js/mermaid-cli` npm package to export to PNG/SVG

## Diagrams at a Glance

### 1. [Full System Architecture](./architecture.md#1-full-system-architecture)
End-to-end flow across all 8 pipeline stages: detect → extract → normalize → merge → confidence → project → validate.

### 2. [Data Model Relationships](./architecture.md#2-data-model-relationships)
Class diagram of all Pydantic models: `CandidateFragment`, `CanonicalProfile`, `Skill`, `Provenance`, `OutputConfig`, `PipelineResult`.

### 3. [Identity Matching & Merge Decision Tree](./architecture.md#3-identity-matching--merge-decision-tree)
Flowchart showing how fragments are grouped by email / name+phone, and how field conflicts are resolved per field type.

### 4. [Source Priority & Reliability](./architecture.md#4-source-priority--reliability-weights)
Quadrant chart placing all 5 sources by merge priority and confidence reliability weight.
