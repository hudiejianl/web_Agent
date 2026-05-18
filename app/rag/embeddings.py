from __future__ import annotations

import hashlib
import math

import requests

from app.config import get_settings


BGE_MODEL_ALIASES = {
    "bge-m3": "BAAI/bge-m3",
    "bge-large-zh": "BAAI/bge-large-zh-v1.5",
    "bge-large-zh-v1.5": "BAAI/bge-large-zh-v1.5",
}


class HashingEmbeddingFunction:
    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in input]

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().replace("，", " ").replace("。", " ").split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OpenAICompatibleEmbeddingFunction:
    def __init__(self, model: str, api_key: str, base_url: str, timeout_seconds: int = 30):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def __call__(self, input: list[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": input},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in data]


def get_embedding_function():
    settings = get_settings()
    if settings.embedding_provider == "openai-compatible" and settings.embedding_api_key:
        base_url = settings.embedding_base_url or settings.openai_base_url
        return OpenAICompatibleEmbeddingFunction(settings.embedding_model, settings.embedding_api_key, base_url, settings.embedding_timeout_seconds)
    if settings.embedding_model == "hashing":
        return HashingEmbeddingFunction()
    model_name = BGE_MODEL_ALIASES.get(settings.embedding_model, settings.embedding_model)
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        return SentenceTransformerEmbeddingFunction(model_name=model_name)
    except Exception:
        return HashingEmbeddingFunction()
