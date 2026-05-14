from __future__ import annotations

from app.models.schemas import TutorProfile
from app.rag.bm25 import BM25Retriever
from app.rag.vector_store import VectorStore
from app.storage.repositories import TutorRepository


class TutorRetriever:
    def __init__(self, repository: TutorRepository | None = None, vector_store: VectorStore | None = None):
        self.repository = repository or TutorRepository()
        self.vector_store = vector_store or VectorStore()

    def search(self, query: str, limit: int = 5) -> list[TutorProfile]:
        candidate_limit = max(limit * 3, 10)
        all_profiles = self.repository.list(limit=200)
        dense_ids = self.vector_store.query(query, limit=candidate_limit)
        dense_profiles = [profile for tutor_id in dense_ids if (profile := self.repository.get(tutor_id))]
        bm25_results = BM25Retriever(all_profiles).search(query, limit=candidate_limit)
        merged = self._merge_results(dense_profiles, bm25_results)
        if merged:
            return merged[:limit]
        return self._keyword_search(query, limit, all_profiles)

    def _merge_results(self, dense_profiles: list[TutorProfile], bm25_results: list[tuple[TutorProfile, float]]) -> list[TutorProfile]:
        scores: dict[str, float] = {}
        profiles: dict[str, TutorProfile] = {}
        for rank, profile in enumerate(dense_profiles):
            if not profile.id:
                continue
            profiles[profile.id] = profile
            scores[profile.id] = scores.get(profile.id, 0.0) + 1.0 / (rank + 1)
        max_bm25 = max((score for _, score in bm25_results), default=0.0) or 1.0
        for rank, (profile, score) in enumerate(bm25_results):
            if not profile.id:
                continue
            profiles[profile.id] = profile
            normalized = score / max_bm25
            scores[profile.id] = scores.get(profile.id, 0.0) + 1.2 * normalized + 0.2 / (rank + 1)
        return [profiles[tutor_id] for tutor_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)]

    def _keyword_search(self, query: str, limit: int, profiles: list[TutorProfile] | None = None) -> list[TutorProfile]:
        keywords = [item for item in query.lower().replace("，", " ").replace("。", " ").split() if item]
        scored: list[tuple[int, TutorProfile]] = []
        for profile in profiles or self.repository.list(limit=100):
            text = profile.document_text().lower()
            score = sum(1 for keyword in keywords if keyword in text)
            if score:
                scored.append((score, profile))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [profile for _, profile in scored[:limit]]
