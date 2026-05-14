from __future__ import annotations

import chromadb

from app.config import get_settings
from app.models.schemas import TutorProfile
from app.rag.embeddings import get_embedding_function


class VectorStore:
    def __init__(self):
        settings = get_settings()
        self.client = chromadb.PersistentClient(path=settings.chroma_path)
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_tutor(self, profile: TutorProfile) -> None:
        if not profile.id:
            raise ValueError("Tutor profile must have an id before indexing")
        self.collection.upsert(
            ids=[profile.id],
            documents=[profile.document_text()],
            metadatas=[
                {
                    "name": profile.name,
                    "institution": profile.institution,
                    "location": profile.location or "",
                    "homepage": profile.homepage or "",
                }
            ],
        )

    def query(self, text: str, limit: int = 5) -> list[str]:
        result = self.collection.query(query_texts=[text], n_results=limit)
        ids = result.get("ids") or [[]]
        return ids[0]
