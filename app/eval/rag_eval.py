from __future__ import annotations

import json
from pathlib import Path

from app.models.schemas import RAGEvaluationCase, RAGEvaluationCaseResult, RAGEvaluationComparisonResponse, RAGEvaluationResponse, TutorProfile
from app.rag.retriever import TutorRetriever
from app.services.ingestion import ensure_seed_data
from app.storage.database import init_database


class RAGEvaluator:
    def __init__(self, retriever: TutorRetriever | None = None, dataset_path: str = "data/sample/rag_eval.json"):
        init_database()
        ensure_seed_data()
        self.retriever = retriever or TutorRetriever()
        self.dataset_path = dataset_path

    def evaluate(self, limit: int = 5, strategy: str = "reranker") -> RAGEvaluationResponse:
        cases = self.load_cases()
        results = [self.evaluate_case(case, limit=limit, strategy=strategy) for case in cases]
        return RAGEvaluationResponse(
            strategy=strategy,
            case_count=len(results),
            recall=self._average([result.recall for result in results]),
            precision=self._average([result.precision for result in results]),
            relevance=self._average([result.relevance for result in results]),
            cases=results,
        )

    def compare(self, limit: int = 5, strategies: list[str] | None = None) -> RAGEvaluationComparisonResponse:
        strategies = strategies or ["baseline", "hybrid", "reranker"]
        return RAGEvaluationComparisonResponse(strategies=[self.evaluate(limit=limit, strategy=strategy) for strategy in strategies])

    def evaluate_case(self, case: RAGEvaluationCase, limit: int = 5, strategy: str = "reranker") -> RAGEvaluationCaseResult:
        retrieved = self.retriever.search(case.query, limit=limit, strategy=strategy)
        retrieved_names = [profile.name for profile in retrieved]
        expected = set(case.expected_tutor_names)
        retrieved_set = set(retrieved_names)
        hits = expected & retrieved_set
        recall = len(hits) / len(expected) if expected else 0.0
        precision = len(hits) / len(retrieved_set) if retrieved_set else 0.0
        return RAGEvaluationCaseResult(
            case_id=case.id,
            query=case.query,
            expected_tutor_names=case.expected_tutor_names,
            retrieved_tutor_names=retrieved_names,
            recall=round(recall, 4),
            precision=round(precision, 4),
            relevance=round(self._relevance(case, retrieved), 4),
        )

    def load_cases(self) -> list[RAGEvaluationCase]:
        path = Path(self.dataset_path)
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return [RAGEvaluationCase.model_validate(item) for item in payload]

    def _relevance(self, case: RAGEvaluationCase, profiles: list[TutorProfile]) -> float:
        if not profiles or not case.relevant_terms:
            return 0.0
        scores = []
        for profile in profiles:
            document = profile.document_text().lower()
            matched = sum(1 for term in case.relevant_terms if term.lower() in document)
            scores.append(matched / len(case.relevant_terms))
        return sum(scores) / len(scores)

    def _average(self, values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0
