from __future__ import annotations

import re

from app.models.schemas import TutorProfile
from app.rag.bm25 import BM25Retriever


LOCATION_TERMS = ["北京", "上海", "杭州", "南京", "武汉", "广州", "深圳", "西安", "江浙沪", "浙江", "江苏"]
INTENT_TERMS = ["导师", "教授", "招生", "硕士", "博士", "研究方向", "论文", "顶会", "企业合作"]


class TutorReranker:
    def rerank(self, query: str, profiles: list[TutorProfile], limit: int | None = None) -> list[TutorProfile]:
        if not profiles:
            return []
        bm25_scores = {profile.id: score for profile, score in BM25Retriever(profiles).search(query, limit=len(profiles)) if profile.id}
        max_bm25 = max(bm25_scores.values(), default=0.0) or 1.0
        scored = []
        for original_rank, profile in enumerate(profiles):
            score = self._score_profile(query, profile)
            if profile.id:
                score += bm25_scores.get(profile.id, 0.0) / max_bm25
            score += 0.1 / (original_rank + 1)
            scored.append((score, profile))
        scored.sort(key=lambda item: item[0], reverse=True)
        reranked = [profile for _, profile in scored]
        return reranked[:limit] if limit else reranked

    def _score_profile(self, query: str, profile: TutorProfile) -> float:
        query_terms = self._query_terms(query)
        document = profile.document_text().lower()
        score = 0.0
        for term in query_terms:
            if term and term.lower() in document:
                score += 1.0
        for area in profile.research_areas:
            area_lower = area.lower()
            if any(term.lower() in area_lower or area_lower in term.lower() for term in query_terms):
                score += 2.0
        for direction in profile.admission_directions:
            direction_lower = direction.lower()
            if any(term.lower() in direction_lower or direction_lower in term.lower() for term in query_terms):
                score += 1.5
        if profile.location and profile.location in query:
            score += 2.0
        if any(location in query for location in LOCATION_TERMS) and profile.location and profile.location in query:
            score += 1.0
        if any(term in query for term in INTENT_TERMS) and (profile.requirements or profile.admission_directions):
            score += 0.8
        if profile.papers and any(term in query for term in ["论文", "顶会", "近三年"]):
            score += 1.0
        return score

    def _query_terms(self, query: str) -> list[str]:
        normalized = query.replace("，", " ").replace("。", " ").replace("、", " ").lower()
        tokens = re.findall(r"[A-Za-z0-9_]+|[一-鿿]{2,4}", normalized)
        expanded = []
        for token in tokens:
            expanded.append(token)
            if re.fullmatch(r"[一-鿿]{3,4}", token):
                expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
        return list(dict.fromkeys(expanded))
