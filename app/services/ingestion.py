from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.crawlers.faculty import FacultyCrawler
from app.models.schemas import IngestUrlPreviewResponse, TutorProfile
from app.rag.vector_store import VectorStore
from app.services.profile_quality import ProfileQualityScorer
from app.storage.database import init_database
from app.storage.repositories import TutorRepository, load_tutors_from_json


class ProfileQualityError(ValueError):
    def __init__(self, score: float, reasons: list[str]):
        self.score = score
        self.reasons = reasons
        super().__init__(f"导师档案质量不足，质量分 {score}，原因：{'；'.join(reasons)}")


class IngestionService:
    def __init__(self, repository: TutorRepository | None = None, vector_store: VectorStore | None = None):
        self.repository = repository or TutorRepository()
        self.vector_store = vector_store or VectorStore()
        self.crawler = FacultyCrawler()
        self.profile_quality = ProfileQualityScorer()

    def ingest_profile(self, profile: TutorProfile) -> TutorProfile:
        profile = self.repository.upsert(profile)
        self.vector_store.upsert_tutor(profile)
        return profile

    def preview_url(self, url: str) -> IngestUrlPreviewResponse:
        page = self.crawler.browser.fetch(url)
        profile = self.crawler.researcher.structure_faculty_page(page)
        profile.homepage = profile.homepage or url
        page_quality = self._page_quality(page)
        quality = self.profile_quality.score(profile, url, title=str(page.get("title") or ""), text=str(page.get("text") or ""), page_quality=page_quality)
        return IngestUrlPreviewResponse(
            tutor=profile,
            indexed=False,
            ingest_eligible=quality.ingest_eligible,
            profile_quality_score=quality.score,
            page_quality=page_quality,
            quality_reasons=quality.reasons,
        )

    def ingest_url(self, url: str) -> TutorProfile:
        preview = self.preview_url(url)
        if not preview.ingest_eligible:
            raise ProfileQualityError(preview.profile_quality_score, preview.quality_reasons)
        return self.ingest_profile(preview.tutor)

    def _page_quality(self, page: dict) -> float:
        text = page.get("text", "") or ""
        links = page.get("links", []) or []
        score = 0.0
        if len(text) >= 300:
            score += 0.25
        if len(text) >= 1000:
            score += 0.2
        if any(keyword in text for keyword in ["研究方向", "招生", "论文", "个人主页", "教授", "导师"]):
            score += 0.25
        if any(keyword in text.lower() for keyword in ["email", "@", "publication", "research"]):
            score += 0.15
        if links:
            score += 0.15
        return round(min(score, 1.0), 4)

    def ingest_seed_file(self, path: str = "data/sample/faculty_seed.json") -> list[TutorProfile]:
        init_database()
        seed_path = Path(path)
        if not seed_path.exists():
            return []
        profiles = load_tutors_from_json(str(seed_path))
        return [self.ingest_profile(profile) for profile in profiles]


def ensure_seed_data() -> None:
    if not get_settings().auto_seed_data:
        return
    repository = TutorRepository()
    if repository.list(limit=1):
        return
    IngestionService(repository=repository).ingest_seed_file()
