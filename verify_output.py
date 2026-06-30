"""Quick script to verify the output."""
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total profiles: {len(data)}")
print()
for i, entry in enumerate(data):
    p = entry["profile"]
    v = entry["validation"]
    print(f"--- Profile {i+1} ---")
    print(f"  Name: {p.get('full_name', 'N/A')}")
    print(f"  Emails: {p.get('emails', [])}")
    print(f"  Phones: {p.get('phones', [])}")
    print(f"  Location: {p.get('location', 'N/A')}")
    print(f"  Headline: {p.get('headline', 'N/A')}")
    print(f"  Years Exp: {p.get('years_experience', 'N/A')}")
    skills = p.get("skills", [])
    if isinstance(skills, list) and skills and isinstance(skills[0], dict):
        skill_names = [s["name"] for s in skills]
    elif isinstance(skills, list):
        skill_names = skills
    else:
        skill_names = []
    print(f"  Skills ({len(skill_names)}): {', '.join(skill_names[:10])}")
    exp = p.get("experience", [])
    print(f"  Experience ({len(exp)} entries)")
    for e in exp:
        if isinstance(e, dict):
            print(f"    - {e.get('title', '?')} at {e.get('company', '?')} ({e.get('start', '?')} - {e.get('end', 'Present')})")
    edu = p.get("education", [])
    print(f"  Education ({len(edu)} entries)")
    for e in edu:
        if isinstance(e, dict):
            print(f"    - {e.get('degree', '?')} at {e.get('institution', '?')} ({e.get('end_year', '?')})")
    print(f"  Confidence: {p.get('overall_confidence', 'N/A')}")
    prov = p.get("provenance", [])
    print(f"  Provenance entries: {len(prov)}")
    print(f"  Validation: {'VALID' if v.get('valid') else 'INVALID'}")
    print()
