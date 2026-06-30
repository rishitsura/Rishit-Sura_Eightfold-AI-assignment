"""
Cross-source merger.

Merges multiple CandidateFragments into a single CanonicalProfile.

Merge strategy:
- Match candidates across sources using email as primary key,
  then (name + phone) as fallback.
- Scalar fields: pick from highest-priority source.
- Array fields: union with dedup.
- Object fields: merge details from multiple sources.
- Track provenance for every merged value.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from rapidfuzz import fuzz

from transformer.models import (
    SOURCE_PRIORITY,
    CandidateFragment,
    CanonicalProfile,
    Education,
    Experience,
    Links,
    Location,
    Provenance,
    Skill,
    SourceType,
)
from transformer.normalizers import (
    normalize_date,
    normalize_email,
    normalize_emails_list,
    normalize_name,
    normalize_phone,
    normalize_skill,
    normalize_skills_list,
    normalize_country,
    normalize_url,
)

logger = logging.getLogger(__name__)


def _source_priority_rank(source_type: SourceType) -> int:
    """Lower number = higher priority."""
    try:
        return SOURCE_PRIORITY.index(source_type)
    except ValueError:
        return len(SOURCE_PRIORITY)


def _names_match(a: str | None, b: str | None, threshold: int = 80) -> bool:
    """Check if two names match using fuzzy comparison."""
    if not a or not b:
        return False
    return fuzz.ratio(a.lower().strip(), b.lower().strip()) >= threshold


def _emails_overlap(a: list[str], b: list[str]) -> bool:
    """Check if two email lists share at least one email."""
    set_a = {e.lower().strip() for e in a if e}
    set_b = {e.lower().strip() for e in b if e}
    return bool(set_a & set_b)


def _phones_overlap(a: list[str], b: list[str]) -> bool:
    """Check if two phone lists share a common number (by digits only)."""
    def digits(p: str) -> str:
        return "".join(c for c in p if c.isdigit())[-10:]  # Last 10 digits

    set_a = {digits(p) for p in a if p and len(digits(p)) >= 7}
    set_b = {digits(p) for p in b if p and len(digits(p)) >= 7}
    return bool(set_a & set_b)


class CandidateMerger:
    """Merges fragments from multiple sources into canonical profiles."""

    def merge_all(
        self, fragments: list[CandidateFragment]
    ) -> list[CanonicalProfile]:
        """
        Merge all fragments into canonical profiles.

        Fragments are first grouped by identity (matching emails or name+phone),
        then each group is merged into a single profile.

        Returns a list of CanonicalProfile objects (one per unique candidate).
        """
        if not fragments:
            return []

        groups = self._group_fragments(fragments)
        profiles: list[CanonicalProfile] = []

        for group in groups:
            profile = self._merge_group(group)
            profiles.append(profile)

        logger.info(
            "Merged %d fragments into %d profiles",
            len(fragments),
            len(profiles),
        )
        return profiles

    def _group_fragments(
        self, fragments: list[CandidateFragment]
    ) -> list[list[CandidateFragment]]:
        """
        Group fragments that belong to the same person.

        Primary match: shared email address.
        Secondary match: matching name AND shared phone number.
        """
        groups: list[list[CandidateFragment]] = []

        for fragment in fragments:
            matched_group_idx = None

            for idx, group in enumerate(groups):
                if self._fragments_match(fragment, group):
                    matched_group_idx = idx
                    break

            if matched_group_idx is not None:
                groups[matched_group_idx].append(fragment)
            else:
                groups.append([fragment])

        return groups

    def _fragments_match(
        self, fragment: CandidateFragment, group: list[CandidateFragment]
    ) -> bool:
        """Check if a fragment matches any fragment in the group."""
        for existing in group:
            # Primary: email overlap
            if _emails_overlap(fragment.emails, existing.emails):
                return True

            # Secondary: name match AND phone overlap
            if (
                _names_match(fragment.full_name, existing.full_name)
                and _phones_overlap(fragment.phones, existing.phones)
            ):
                return True

            # Tertiary: exact name match when both have name but no other match keys
            if (
                fragment.full_name
                and existing.full_name
                and _names_match(fragment.full_name, existing.full_name, threshold=95)
                and not fragment.emails
                and not existing.emails
            ):
                return True

        return False

    def _merge_group(
        self, fragments: list[CandidateFragment]
    ) -> CanonicalProfile:
        """Merge a group of fragments into a single CanonicalProfile."""

        # Sort by source priority (highest priority first)
        sorted_fragments = sorted(
            fragments,
            key=lambda f: _source_priority_rank(f.source_type),
        )

        provenance: list[Provenance] = []

        # --- Merge scalars (pick highest-priority non-null) ---
        full_name = self._merge_scalar(
            sorted_fragments, "full_name", provenance
        )
        if full_name:
            full_name = normalize_name(full_name)

        headline = self._merge_scalar(
            sorted_fragments, "headline", provenance
        )

        years_experience = self._merge_scalar(
            sorted_fragments, "years_experience", provenance
        )

        # --- Merge array fields (union + dedup) ---
        emails = self._merge_emails(sorted_fragments, provenance)
        phones = self._merge_phones(sorted_fragments, provenance)
        skills = self._merge_skills(sorted_fragments, provenance)
        experience = self._merge_experience(sorted_fragments, provenance)
        education = self._merge_education(sorted_fragments, provenance)

        # --- Merge compound objects ---
        location = self._merge_location(sorted_fragments, provenance)
        links = self._merge_links(sorted_fragments, provenance)

        profile = CanonicalProfile(
            full_name=full_name,
            emails=emails,
            phones=phones,
            location=location,
            links=links,
            headline=headline,
            years_experience=years_experience,
            skills=skills,
            experience=experience,
            education=education,
            provenance=provenance,
        )

        return profile

    # --- Scalar merge ---

    def _merge_scalar(
        self,
        fragments: list[CandidateFragment],
        field: str,
        provenance: list[Provenance],
    ) -> Optional[any]:
        """
        Merge a scalar field: pick the first non-null value
        from priority-sorted fragments. On ties, prefer the longer value.
        """
        best_value = None
        best_source = None

        for frag in fragments:
            value = getattr(frag, field, None)
            if value is not None:
                if best_value is None:
                    best_value = value
                    best_source = frag
                elif isinstance(value, str) and isinstance(best_value, str):
                    # Same priority level — prefer longer (more complete)
                    if len(value) > len(best_value):
                        best_value = value
                        best_source = frag

        if best_value is not None and best_source is not None:
            provenance.append(Provenance(
                field=field,
                source=best_source.source_type.value,
                method="priority_merge",
            ))

        return best_value

    # --- Email merge ---

    def _merge_emails(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> list[str]:
        """Union and deduplicate emails across all fragments."""
        all_emails: list[str] = []
        sources: list[str] = []

        for frag in fragments:
            for email in frag.emails:
                all_emails.append(email)
                sources.append(frag.source_type.value)

        normalized = normalize_emails_list(all_emails)

        if normalized:
            # Record provenance for each unique email
            source_set = set(sources)
            provenance.append(Provenance(
                field="emails",
                source=", ".join(sorted(source_set)),
                method="union_dedup",
            ))

        return normalized

    # --- Phone merge ---

    def _merge_phones(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> list[str]:
        """Union and deduplicate phones, normalizing to E.164."""
        seen_digits: set[str] = set()
        result: list[str] = []
        sources: set[str] = set()

        for frag in fragments:
            for phone in frag.phones:
                normalized = normalize_phone(phone)
                if normalized and normalized not in seen_digits:
                    seen_digits.add(normalized)
                    result.append(normalized)
                    sources.add(frag.source_type.value)

        if result:
            provenance.append(Provenance(
                field="phones",
                source=", ".join(sorted(sources)),
                method="union_dedup_e164",
            ))

        return result

    # --- Skills merge ---

    def _merge_skills(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> list[Skill]:
        """
        Merge skills: union across sources, normalize names,
        track per-skill source count for confidence.
        """
        skill_sources: dict[str, list[str]] = defaultdict(list)

        for frag in fragments:
            normalized = normalize_skills_list(frag.skills)
            for skill_name in normalized:
                canonical = skill_name.lower()
                if frag.source_type.value not in skill_sources[canonical]:
                    skill_sources[canonical].append(frag.source_type.value)

        total_sources = len(set(f.source_type for f in fragments))
        skills: list[Skill] = []

        for canonical_lower, sources in sorted(skill_sources.items()):
            # Re-normalize to get proper casing
            display_name = normalize_skill(canonical_lower)
            confidence = len(sources) / max(total_sources, 1)
            skills.append(Skill(
                name=display_name,
                confidence=round(confidence, 2),
                sources=sources,
            ))

        if skills:
            provenance.append(Provenance(
                field="skills",
                source="all",
                method="union_canonical_merge",
            ))

        return skills

    # --- Experience merge ---

    def _merge_experience(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> list[Experience]:
        """
        Merge experience: deduplicate by fuzzy (company + title) matching,
        normalize dates, prefer more complete entries.
        """
        entries: list[Experience] = []
        sources: set[str] = set()

        for frag in fragments:
            for exp in frag.experience:
                # Skip entries with no company and no title
                if not exp.company and not exp.title:
                    continue

                # Normalize dates
                start = normalize_date(exp.start) if exp.start else None
                end = normalize_date(exp.end) if exp.end else None

                normalized = Experience(
                    company=exp.company.strip() if exp.company else None,
                    title=exp.title.strip() if exp.title else None,
                    start=start,
                    end=end,
                    summary=exp.summary,
                )

                # Try to find a matching existing entry by fuzzy company+title
                match_idx = self._find_matching_experience(entries, normalized)

                if match_idx is None:
                    entries.append(normalized)
                    sources.add(frag.source_type.value)
                else:
                    # Merge: fill in missing fields from new entry
                    existing = entries[match_idx]
                    updates = {}
                    if not existing.start and normalized.start:
                        updates["start"] = normalized.start
                    if not existing.end and normalized.end:
                        updates["end"] = normalized.end
                    if not existing.summary and normalized.summary:
                        updates["summary"] = normalized.summary
                    if not existing.company and normalized.company:
                        updates["company"] = normalized.company
                    if not existing.title and normalized.title:
                        updates["title"] = normalized.title
                    if updates:
                        entries[match_idx] = existing.model_copy(update=updates)
                    sources.add(frag.source_type.value)

        if entries:
            provenance.append(Provenance(
                field="experience",
                source=", ".join(sorted(sources)),
                method="dedup_merge",
            ))

        return entries

    def _find_matching_experience(
        self, entries: list[Experience], candidate: Experience
    ) -> int | None:
        """Find an existing experience entry that matches the candidate."""
        for i, existing in enumerate(entries):
            # Compare company names (fuzzy)
            company_match = False
            if existing.company and candidate.company:
                company_match = fuzz.ratio(
                    existing.company.lower(), candidate.company.lower()
                ) >= 80
            elif not existing.company and not candidate.company:
                company_match = True

            # Compare titles (fuzzy)
            title_match = False
            if existing.title and candidate.title:
                title_match = fuzz.ratio(
                    existing.title.lower(), candidate.title.lower()
                ) >= 80
            elif not existing.title and not candidate.title:
                title_match = True

            # If both company and title match, it's a duplicate
            if company_match and title_match:
                return i

            # Also match if company matches and start dates match
            if company_match and existing.start and candidate.start:
                if existing.start == candidate.start:
                    return i

        return None

    # --- Education merge ---

    def _merge_education(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> list[Education]:
        """
        Merge education: deduplicate by fuzzy (institution + degree) matching,
        prefer more complete entries.
        """
        entries: list[Education] = []
        sources: set[str] = set()

        for frag in fragments:
            for edu in frag.education:
                # Skip empty entries
                if not edu.institution and not edu.degree:
                    continue

                match_idx = self._find_matching_education(entries, edu)

                if match_idx is None:
                    entries.append(edu)
                    sources.add(frag.source_type.value)
                else:
                    # Merge: fill missing fields
                    existing = entries[match_idx]
                    updates = {}
                    if not existing.field and edu.field:
                        updates["field"] = edu.field
                    if not existing.end_year and edu.end_year:
                        updates["end_year"] = edu.end_year
                    if not existing.degree and edu.degree:
                        updates["degree"] = edu.degree
                    if not existing.institution and edu.institution:
                        updates["institution"] = edu.institution
                    # Prefer longer degree name (more descriptive)
                    if (existing.degree and edu.degree
                            and len(edu.degree) > len(existing.degree)):
                        updates["degree"] = edu.degree
                    if updates:
                        entries[match_idx] = existing.model_copy(update=updates)
                    sources.add(frag.source_type.value)

        if entries:
            provenance.append(Provenance(
                field="education",
                source=", ".join(sorted(sources)),
                method="dedup_merge",
            ))

        return entries

    def _find_matching_education(
        self, entries: list[Education], candidate: Education
    ) -> int | None:
        """Find an existing education entry that matches the candidate."""
        for i, existing in enumerate(entries):
            # Compare institution names (fuzzy)
            inst_match = False
            if existing.institution and candidate.institution:
                inst_match = fuzz.ratio(
                    existing.institution.lower(), candidate.institution.lower()
                ) >= 75
            elif not existing.institution and not candidate.institution:
                inst_match = True

            if not inst_match:
                continue

            # If institutions match, check if degrees are related
            if existing.degree and candidate.degree:
                # Normalize common abbreviations for comparison
                d1 = self._normalize_degree_for_comparison(existing.degree)
                d2 = self._normalize_degree_for_comparison(candidate.degree)
                degree_match = (
                    fuzz.partial_ratio(d1, d2) >= 65
                    or fuzz.ratio(d1, d2) >= 60
                )
                if degree_match:
                    return i
            elif existing.end_year and candidate.end_year:
                if existing.end_year == candidate.end_year:
                    return i
            else:
                return i

        return None

    @staticmethod
    def _normalize_degree_for_comparison(degree: str) -> str:
        """Expand common degree abbreviations for better fuzzy matching."""
        d = degree.lower().strip()
        replacements = {
            "b.tech": "bachelor of technology",
            "btech": "bachelor of technology",
            "b.e.": "bachelor of engineering",
            "b.e": "bachelor of engineering",
            "m.tech": "master of technology",
            "mtech": "master of technology",
            "m.e.": "master of engineering",
            "b.s.": "bachelor of science",
            "b.s": "bachelor of science",
            "bs": "bachelor of science",
            "m.s.": "master of science",
            "m.s": "master of science",
            "ms": "master of science",
            "b.a.": "bachelor of arts",
            "m.a.": "master of arts",
            "b.sc": "bachelor of science",
            "m.sc": "master of science",
            "ph.d": "doctor of philosophy",
            "ph.d.": "doctor of philosophy",
            "phd": "doctor of philosophy",
            "mba": "master of business administration",
        }
        for abbr, full in replacements.items():
            if d.startswith(abbr):
                d = d.replace(abbr, full, 1)
                break
        return d

    # --- Location merge ---

    def _merge_location(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> Optional[Location]:
        """
        Merge location: pick the most complete location,
        normalize country to ISO-3166 alpha-2.
        """
        best: Optional[Location] = None
        best_score = -1
        best_source = None

        for frag in fragments:
            loc = frag.location
            if not loc:
                continue

            # Score by completeness
            score = sum([
                bool(loc.city),
                bool(loc.region),
                bool(loc.country),
            ])

            if score > best_score:
                best = loc
                best_score = score
                best_source = frag

        if best:
            # Normalize country
            country = normalize_country(best.country) if best.country else None
            best = Location(
                city=best.city,
                region=best.region,
                country=country,
            )
            if best_source:
                provenance.append(Provenance(
                    field="location",
                    source=best_source.source_type.value,
                    method="most_complete",
                ))

        return best

    # --- Links merge ---

    def _merge_links(
        self,
        fragments: list[CandidateFragment],
        provenance: list[Provenance],
    ) -> Optional[Links]:
        """Merge links: take first non-null for each link type."""
        linkedin = None
        github = None
        portfolio = None
        other: list[str] = []
        sources: set[str] = set()

        for frag in fragments:
            if not frag.links:
                continue

            if not linkedin and frag.links.linkedin:
                linkedin = normalize_url(frag.links.linkedin)
                sources.add(frag.source_type.value)
            if not github and frag.links.github:
                github = normalize_url(frag.links.github)
                sources.add(frag.source_type.value)
            if not portfolio and frag.links.portfolio:
                portfolio = normalize_url(frag.links.portfolio)
                sources.add(frag.source_type.value)
            for url in frag.links.other:
                norm = normalize_url(url)
                if norm and norm not in other:
                    other.append(norm)
                    sources.add(frag.source_type.value)

        if any([linkedin, github, portfolio, other]):
            provenance.append(Provenance(
                field="links",
                source=", ".join(sorted(sources)),
                method="first_non_null",
            ))
            return Links(
                linkedin=linkedin,
                github=github,
                portfolio=portfolio,
                other=other,
            )

        return None
