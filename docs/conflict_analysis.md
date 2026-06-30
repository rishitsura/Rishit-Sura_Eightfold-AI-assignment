# Conflict-Aware Confidence Scoring (CACS) & Lineage Audit Log

## The Problem: Silent Conflict Masking

Traditional data unification systems often merge disparate fields by prioritizing one source over another (e.g., Resume > LinkedIn). While effective, this creates a blind spot: **Silent Conflict Masking**.

If an ATS JSON file says a candidate has 10 years of experience, but their newly uploaded resume says they have 2 years of experience, a naive merge simply overwrites the 10 with the 2, assuming the resume is more accurate. But to a recruiter, a massive discrepancy in experience (10 vs 2) is a massive red flag that requires human review. By silently resolving the conflict, the system masks the candidate's unreliability.

## The Solution: CACS & Lineage IR

To solve this, we implemented two architectural patterns:

1. **Conflict-Aware Confidence Scoring (CACS)**: Before any merging happens, we measure the mathematical divergence between values from different sources. If the divergence crosses a severity threshold (e.g., highly divergent job titles or years of experience), we attach a `ConflictFlag` to the profile. This flag **penalizes the final confidence score** of that specific field. This alerts the downstream ATS UI that the field is "low confidence" not because we lack data, but because the candidate provided conflicting data.

2. **Merger-Level Lineage IR (Intermediate Representation)**: Rather than silently discarding the "loser" data in a merge conflict, we log it. The `ConflictAnalyzer` produces `MergeDecision` objects. Each decision records the field name, the "winner" value and its source, and an array of all "loser" values and their sources. This provides a fully deterministic, mathematically traceable audit log (Lineage) that recruiters can use to see exactly *why* a decision was made.

## Temporal Skill Stratification

The CACS system also applies to skills. By comparing the sets of skills from different sources using Jaccard Similarity, we can detect **Temporal Drift** (where older profiles have totally different skills than newer profiles). 

Furthermore, we stratify skills into three statuses:
- **`CONFIRMED`**: The skill appears in multiple independent sources (Highest Confidence).
- **`CURRENT`**: The skill appears only in the most recent source (e.g., Resume) (Medium Confidence).
- **`HISTORICAL`**: The skill appears only in older sources (e.g., ATS JSON) and is missing from the resume (Lowest Confidence).

This granular stratification provides recruiters with a much more nuanced view of a candidate's actual capabilities, distinguishing between skills they are actively using versus skills they haven't touched in years.
