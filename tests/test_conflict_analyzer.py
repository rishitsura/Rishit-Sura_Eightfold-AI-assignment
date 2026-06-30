"""
Tests for Conflict-Aware Confidence Scoring (CACS) and temporal skill stratification.
"""

from transformer.conflict_analyzer import ConflictAnalyzer
from transformer.models import (
    CandidateFragment,
    ConflictSeverity,
    Experience,
    SkillStatus,
    SourceType,
)

def test_scalar_conflict_detection():
    analyzer = ConflictAnalyzer()

    # Complete disagreement (Google vs Microsoft)
    frag1 = CandidateFragment(
        source_type=SourceType.ATS_JSON,
        experience=[Experience(company="Google", title="Engineer")],
    )
    frag2 = CandidateFragment(
        source_type=SourceType.RESUME,
        experience=[Experience(company="Microsoft", title="Engineer")],
    )

    report = analyzer.analyze([frag1, frag2])

    # Should flag a HIGH conflict on experience[0].company
    flag = next((f for f in report.flags if f.field == "experience[0].company"), None)
    assert flag is not None
    assert flag.severity == ConflictSeverity.HIGH
    assert flag.penalty > 0.6  # Penalized by max reliability (ATS = 0.90)
    
    # Should log the merge decision (lineage)
    decision = next((d for d in report.merge_decisions if d.field == "experience[0].company"), None)
    assert decision is not None
    assert decision.winner["value"] == "Google"
    assert len(decision.losers) == 1
    assert decision.losers[0]["value"] == "Microsoft"

def test_low_conflict_omitted():
    analyzer = ConflictAnalyzer()

    # Minor spelling difference (divergence < 0.3)
    frag1 = CandidateFragment(
        source_type=SourceType.ATS_JSON,
        full_name="Jonathan Smith",
    )
    frag2 = CandidateFragment(
        source_type=SourceType.RESUME,
        full_name="Jonathon Smith",
    )

    report = analyzer.analyze([frag1, frag2])

    # Should NOT emit a ConflictFlag for LOW severity
    assert len(report.flags) == 0

    # BUT should still log the lineage decision
    decision = next((d for d in report.merge_decisions if d.field == "full_name"), None)
    assert decision is not None
    assert decision.winner["value"] == "Jonathan Smith"

def test_temporal_skill_stratification():
    analyzer = ConflictAnalyzer()

    frag_ats = CandidateFragment(
        source_type=SourceType.ATS_JSON,
        skills=["Java", "COBOL", "Spring"],
    )
    frag_resume = CandidateFragment(
        source_type=SourceType.RESUME,
        skills=["Python", "Go", "Kubernetes", "Spring"],
    )

    report = analyzer.analyze([frag_ats, frag_resume])

    skills_dict = {s.name: s for s in report.skill_list}

    # Spring is in both -> CONFIRMED
    assert skills_dict["Spring"].status == SkillStatus.CONFIRMED
    assert skills_dict["Spring"].confidence == 1.0

    # Python is in resume only -> CURRENT
    assert skills_dict["Python"].status == SkillStatus.CURRENT
    assert skills_dict["Python"].confidence == 0.85

    # Java is in ATS only -> HISTORICAL
    assert skills_dict["Java"].status == SkillStatus.HISTORICAL
    assert skills_dict["Java"].confidence == 0.45

    # Should flag a conflict due to low Jaccard overlap
    flag = next((f for f in report.flags if f.field == "skills"), None)
    assert flag is not None
    assert flag.severity in (ConflictSeverity.MEDIUM, ConflictSeverity.HIGH)
    assert "temporal drift" in flag.detail
