from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.crawlers.faculty import FacultyCrawler
from app.models.schemas import TutorProfile
from app.rag.vector_store import VectorStore
from app.storage.database import init_database
from app.storage.repositories import TutorRepository, load_tutors_from_json


class IngestionService:
    def __init__(self, repository: TutorRepository | None = None, vector_store: VectorStore | None = None):
        self.repository = repository or TutorRepository()
        self.vector_store = vector_store or VectorStore()
        self.crawler = FacultyCrawler()

    def ingest_profile(self, profile: TutorProfile) -> TutorProfile:
        profile = self.repository.upsert(profile)
        self.vector_store.upsert_tutor(profile)
        return profile

    def ingest_url(self, url: str) -> TutorProfile:
        profile = self.crawler.crawl(url)
        return self.ingest_profile(profile)

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
