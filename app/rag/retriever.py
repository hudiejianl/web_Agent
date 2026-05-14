from __future__ import annotations

from app.models.schemas import TutorProfile
from app.rag.vector_store import VectorStore
from app.storage.repositories import TutorRepository


class TutorRetriever:
    def __init__(self, repository: TutorRepository | None = None, vector_store: VectorStore | None = None):
        self.repository = repository or TutorRepository()
        self.vector_store = vector_store or VectorStore()

    def search(self, query: str, limit: int = 5) -> list[TutorProfile]:
        ids = self.vector_store.query(query, limit=limit)
        profiles = [profile for tutor_id in ids if (profile := self.repository.get(tutor_id))]
        if profiles:
            return profiles
        return self._keyword_search(query, limit)

    def _keyword_search(self, query: str, limit: int) -> list[TutorProfile]:
        keywords = [item for item in query.lower().replace("，", " ").replace("。", " ").split() if item]
        scored: list[tuple[int, TutorProfile]] = []
        for profile in self.repository.list(limit=100):
            text = profile.document_text().lower()
            score = sum(1 for keyword in keywords if keyword in text)
            if score:
                scored.append((score, profile))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [profile for _, profile in scored[:limit]]
