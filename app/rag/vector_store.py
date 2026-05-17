from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.models.schemas import TutorProfile
from app.rag.embeddings import get_embedding_function


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    chunk_size = max(chunk_size, 1)
    overlap = max(0, min(overlap, chunk_size - 1))
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = end - overlap
    return chunks


class VectorStore:
    def __init__(self):
        settings = get_settings()
        self.client = chromadb.PersistentClient(path=settings.chroma_path, settings=ChromaSettings(anonymized_telemetry=False))
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_tutor(self, profile: TutorProfile) -> None:
        if not profile.id:
            raise ValueError("Tutor profile must have an id before indexing")
        settings = get_settings()
        chunks = chunk_text(profile.document_text(), settings.rag_chunk_size, settings.rag_chunk_overlap) or [profile.document_text()]
        chunk_ids = [f"{profile.id}::chunk::{index}" for index, _ in enumerate(chunks)]
        self.collection.upsert(
            ids=chunk_ids,
            documents=chunks,
            metadatas=[
                {
                    "tutor_id": profile.id,
                    "chunk_index": index,
                    "name": profile.name,
                    "institution": profile.institution,
                    "location": profile.location or "",
                    "homepage": profile.homepage or "",
                }
                for index, _ in enumerate(chunks)
            ],
        )

    def query(self, text: str, limit: int = 5) -> list[str]:
        result = self.collection.query(query_texts=[text], n_results=max(limit * 4, limit))
        ids = result.get("ids") or [[]]
        metadatas = result.get("metadatas") or [[]]
        ranked: list[str] = []
        for item_id, metadata in zip(ids[0], metadatas[0]):
            tutor_id = (metadata or {}).get("tutor_id") or item_id.split("::chunk::", 1)[0]
            if tutor_id not in ranked:
                ranked.append(tutor_id)
            if len(ranked) >= limit:
                break
        return ranked
