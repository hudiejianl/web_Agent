from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import UniversitySeedSite


class UniversitySeedSiteService:
    def __init__(self, dataset_path: str = "data/sample/university_seed_sites.json"):
        self.dataset_path = dataset_path

    def list_sites(self, query: str = "", limit: int = 20) -> list[UniversitySeedSite]:
        sites = self._load_sites()
        scored = [site.model_copy(update={"score": self._score(site, query)}) for site in sites]
        ranked = sorted(scored, key=lambda item: item.score, reverse=True)
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

    def _score(self, site: UniversitySeedSite, query: str) -> float:
        if not query:
            return 1.0
        text = " ".join([site.name, site.institution, site.location, *site.tags]).lower()
        terms = [term.strip().lower() for term in query.replace("，", " ").replace("、", " ").split() if term.strip()]
        score = sum(1.0 for term in terms if term in text)
        if site.location and site.location.lower() in query.lower():
            score += 2.0
        return score
