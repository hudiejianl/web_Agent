from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import UniversitySeedSite


class UniversitySeedSiteService:
    def __init__(self, dataset_path: str = "data/sample/university_seed_sites.json"):
        self.dataset_path = dataset_path

    def list_sites(self, query: str = "", limit: int = 20) -> list[UniversitySeedSite]:
        sites = self._load_sites()
        scored = []
        for site in sites:
            score, matched_terms = self._score(site, query)
            scored.append(site.model_copy(update={"score": score, "matched_terms": matched_terms, "reason": self._reason(site, matched_terms)}))
        ranked = sorted(scored, key=lambda item: (item.score, len(item.tags)), reverse=True)
        if query:
            ranked = [site for site in ranked if site.score > 0]
        return ranked[: max(1, min(limit, 50))]

    def seed_urls_for_query(self, query: str, limit: int = 4) -> list[str]:
        return [site.url for site in self.list_sites(query=query, limit=limit)]

    def _load_sites(self) -> list[UniversitySeedSite]:
        path = Path(self.dataset_path)
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return [UniversitySeedSite.model_validate(item) for item in payload]

    def _score(self, site: UniversitySeedSite, query: str) -> tuple[float, list[str]]:
        if not query:
            return 1.0, []
        searchable = " ".join([site.name, site.institution, site.location, *site.tags]).lower()
        query_text = query.lower().replace("，", " ").replace("、", " ")
        terms = [term.strip() for term in query_text.split() if term.strip()]
        matched_terms = list(dict.fromkeys(term for term in terms if term in searchable))
        score = float(len(matched_terms))
        if site.location and site.location.lower() in query_text:
            score += 2.0
        if site.institution and site.institution.lower() in query_text:
            score += 2.0
        if any(tag.lower() in query_text for tag in site.tags):
            score += 0.5
        return score, matched_terms

    def _reason(self, site: UniversitySeedSite, matched_terms: list[str]) -> str:
        if not matched_terms:
            return "默认高校入口"
        return f"匹配 {site.location} / {site.institution} / {'、'.join(matched_terms)}"
