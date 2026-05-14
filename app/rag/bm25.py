from __future__ import annotations

import math
import re
from collections import Counter

from app.models.schemas import TutorProfile


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[一-鿿]{1,4}")


class BM25Retriever:
    def __init__(self, profiles: list[TutorProfile], k1: float = 1.5, b: float = 0.75):
        self.profiles = profiles
        self.k1 = k1
        self.b = b
        self.documents = [self._tokenize(profile.document_text()) for profile in profiles]
        self.term_frequencies = [Counter(document) for document in self.documents]
        self.document_frequencies = self._document_frequencies(self.documents)
        self.average_document_length = sum(len(document) for document in self.documents) / len(self.documents) if self.documents else 0.0

    def search(self, query: str, limit: int = 5) -> list[tuple[TutorProfile, float]]:
        query_terms = self._tokenize(query)
        if not query_terms or not self.profiles:
            return []
        scored = []
        for profile, terms, frequencies in zip(self.profiles, self.documents, self.term_frequencies):
            score = self._score(query_terms, terms, frequencies)
            if score > 0:
                scored.append((profile, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _score(self, query_terms: list[str], document_terms: list[str], frequencies: Counter[str]) -> float:
        score = 0.0
        document_length = len(document_terms)
        if not document_length:
            return 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            idf = self._idf(term)
            denominator = frequency + self.k1 * (1 - self.b + self.b * document_length / (self.average_document_length or 1.0))
            score += idf * frequency * (self.k1 + 1) / denominator
        return score

    def _idf(self, term: str) -> float:
        total = len(self.documents)
        containing = self.document_frequencies.get(term, 0)
        return math.log(1 + (total - containing + 0.5) / (containing + 0.5))

    def _document_frequencies(self, documents: list[list[str]]) -> Counter[str]:
        frequencies: Counter[str] = Counter()
        for document in documents:
            frequencies.update(set(document))
        return frequencies

    def _tokenize(self, text: str) -> list[str]:
        normalized = text.lower().replace("，", " ").replace("。", " ").replace("、", " ")
        tokens = TOKEN_PATTERN.findall(normalized)
        expanded = []
        for token in tokens:
            expanded.append(token)
            if re.fullmatch(r"[一-鿿]{3,4}", token):
                expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
        return expanded
