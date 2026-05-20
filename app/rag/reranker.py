from __future__ import annotations

import re

import requests

from app.config import get_settings
from app.models.schemas import TutorProfile
from app.rag.bm25 import BM25Retriever


LOCATION_TERMS = ["北京", "上海", "杭州", "南京", "武汉", "广州", "深圳", "西安", "江浙沪", "浙江", "江苏"]
INTENT_TERMS = ["导师", "教授", "招生", "硕士", "博士", "研究方向", "论文", "顶会", "企业合作"]
INSTITUTION_ALIASES = {"华科": "华中科技大学", "华中大": "华中科技大学"}
ROLE_TERMS = ["博士生导师", "硕士生导师", "博导", "硕导", "教授", "副教授", "讲师", "研究员"]


class TutorReranker:
    def rerank(self, query: str, profiles: list[TutorProfile], limit: int | None = None) -> list[TutorProfile]:
        if not profiles:
            return []
        settings = get_settings()
        if settings.reranker_provider == "openai-compatible" and settings.reranker_api_key:
            try:
                return self._api_rerank(query, profiles, limit, settings)
            except Exception:
                pass
        return self._local_rerank(query, profiles, limit)

    def _api_rerank(self, query: str, profiles: list[TutorProfile], limit: int | None, settings: object) -> list[TutorProfile]:
        base_url = (settings.reranker_base_url or settings.openai_base_url).rstrip("/")
        documents = [profile.document_text() for profile in profiles]
        response = requests.post(
            f"{base_url}/rerank",
            headers={"Authorization": f"Bearer {settings.reranker_api_key}", "Content-Type": "application/json"},
            json={"model": settings.reranker_model, "query": query, "documents": documents, "top_n": limit or len(profiles)},
            timeout=settings.reranker_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json().get("results", [])
        ranked = []
        seen = set()
        for item in sorted(data, key=lambda value: value.get("relevance_score", value.get("score", 0.0)), reverse=True):
            index = item.get("index")
            if isinstance(index, int) and 0 <= index < len(profiles) and index not in seen:
                ranked.append(profiles[index])
                seen.add(index)
        ranked.extend(profile for index, profile in enumerate(profiles) if index not in seen)
        return ranked[:limit] if limit else ranked

    def _local_rerank(self, query: str, profiles: list[TutorProfile], limit: int | None = None) -> list[TutorProfile]:
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
        expanded_query = self._expand_query(query)
        query_terms = self._query_terms(expanded_query)
        document = profile.document_text().lower()
        score = 0.0
        for term in query_terms:
            term_lower = term.lower()
            if not term_lower or term_lower in INTENT_TERMS:
                continue
            if term_lower in document:
                score += 0.6 if len(term_lower) <= 2 else 1.0
        for phrase in self._query_phrases(expanded_query):
            if phrase.lower() in document:
                score += 2.5
        for area in profile.research_areas:
            area_lower = area.lower()
            if any(term.lower() in area_lower or area_lower in term.lower() for term in query_terms):
                score += 3.0
        for direction in profile.admission_directions:
            direction_lower = direction.lower()
            if any(term.lower() in direction_lower or direction_lower in term.lower() for term in query_terms):
                score += 2.5
        if profile.institution and profile.institution in expanded_query:
            score += 2.0
        if profile.department and profile.department in expanded_query:
            score += 1.5
        if profile.location and profile.location in expanded_query:
            score += 2.0
        if any(location in expanded_query for location in LOCATION_TERMS) and profile.location and profile.location in expanded_query:
            score += 1.0
        score += self._role_score(expanded_query, profile)
        score += self._discipline_score(expanded_query, profile)
        if any(term in expanded_query for term in INTENT_TERMS) and (profile.requirements or profile.admission_directions):
            score += 0.8
        if profile.papers and any(term in expanded_query for term in ["论文", "顶会", "近三年"]):
            score += 1.0
        return score

    def _expand_query(self, query: str) -> str:
        expanded = query
        for alias, full_name in INSTITUTION_ALIASES.items():
            if alias in expanded and full_name not in expanded:
                expanded = f"{expanded} {full_name}"
        return expanded

    def _query_phrases(self, query: str) -> list[str]:
        phrases = []
        for term in ["大数据处理", "计算机软件与理论", "数据库管理系统", "多媒体处理", "多媒体技术", "博士生导师", "硕士生导师"]:
            if term in query:
                phrases.append(term)
        return phrases

    def _role_score(self, query: str, profile: TutorProfile) -> float:
        profile_text = profile.document_text()
        score = 0.0
        for role in ROLE_TERMS:
            if role in query and role in profile_text:
                score += 3.0 if role in {"博士生导师", "硕士生导师", "博导", "硕导"} else 1.5
        if "博士" in query:
            score += 4.0 if "博士生导师" in profile_text or "博导" in profile_text else -3.0
        if "硕士" in query:
            score += 3.0 if "硕士生导师" in profile_text or "硕导" in profile_text else -2.0
        if profile.title and profile.title in query:
            score += 1.5
        return score

    def _discipline_score(self, query: str, profile: TutorProfile) -> float:
        profile_text = profile.document_text()
        score = 0.0
        for phrase in ["计算机软件与理论", "大数据处理", "数据库管理系统", "多媒体处理技术"]:
            if phrase in query:
                score += 4.0 if phrase in profile_text else -1.5
        return score

    def _query_terms(self, query: str) -> list[str]:
        normalized = query.replace("，", " ").replace("。", " ").replace("、", " ").lower()
        tokens = re.findall(r"[A-Za-z0-9_]+|[一-鿿]{2,8}", normalized)
        expanded = []
        for token in tokens:
            expanded.append(token)
            if re.fullmatch(r"[一-鿿]{3,8}", token):
                expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
                expanded.extend(token[index : index + 4] for index in range(max(len(token) - 3, 0)))
        return list(dict.fromkeys(expanded))
