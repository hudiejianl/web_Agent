from __future__ import annotations

import re

from app.models.schemas import RetrievalEvidence, TutorProfile


FIELD_EXTRACTORS = {
    "research_areas": lambda profile: "、".join(profile.research_areas),
    "admission_directions": lambda profile: "、".join(profile.admission_directions),
    "requirements": lambda profile: "、".join(profile.requirements),
    "papers": lambda profile: "；".join(paper.title for paper in profile.papers[:5]),
    "summary": lambda profile: profile.summary,
    "institution": lambda profile: f"{profile.institution} {profile.department or ''} {profile.location or ''}",
    "source_evidence": lambda profile: "；".join(item.snippet for item in profile.evidence[:3]),
}
FIELD_WEIGHTS = {
    "research_areas": 3.0,
    "admission_directions": 2.5,
    "papers": 2.0,
    "requirements": 1.8,
    "institution": 1.5,
    "summary": 1.2,
    "source_evidence": 1.0,
}


class RetrievalEvidenceBuilder:
    def build(self, query: str, profiles: list[TutorProfile], limit_per_tutor: int = 3) -> list[RetrievalEvidence]:
        terms = self._terms(query)
        evidence: list[RetrievalEvidence] = []
        for profile in profiles:
            tutor_evidence = self._profile_evidence(profile, terms)
            evidence.extend(tutor_evidence[:limit_per_tutor])
        return evidence

    def _profile_evidence(self, profile: TutorProfile, terms: list[str]) -> list[RetrievalEvidence]:
        items: list[RetrievalEvidence] = []
        if not profile.id:
            return items
        for field, extractor in FIELD_EXTRACTORS.items():
            text = extractor(profile).strip()
            if not text:
                continue
            matched_terms = [term for term in terms if term.lower() in text.lower()]
            if not matched_terms:
                continue
            score = FIELD_WEIGHTS[field] + min(len(matched_terms), 5) * 0.5
            items.append(
                RetrievalEvidence(
                    tutor_id=profile.id,
                    tutor_name=profile.name,
                    field=field,
                    snippet=self._highlight(text, matched_terms),
                    matched_terms=matched_terms,
                    source_url=profile.homepage or (profile.evidence[0].url if profile.evidence else None),
                    score=score,
                )
            )
        items.sort(key=lambda item: item.score, reverse=True)
        return items

    def _terms(self, query: str) -> list[str]:
        normalized = query.replace("，", " ").replace("。", " ").replace("、", " ").lower()
        tokens = re.findall(r"[A-Za-z0-9_]+|[一-鿿]{2,4}", normalized)
        expanded: list[str] = []
        for token in tokens:
            expanded.append(token)
            if re.fullmatch(r"[一-鿿]{3,4}", token):
                expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
        return list(dict.fromkeys(expanded))

    def _highlight(self, text: str, terms: list[str]) -> str:
        snippet = text[:300]
        for term in sorted(terms, key=len, reverse=True):
            if not term:
                continue
            snippet = re.sub(re.escape(term), lambda match: f"**{match.group(0)}**", snippet, flags=re.IGNORECASE)
        return snippet
