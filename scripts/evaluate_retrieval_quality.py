from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.rag_eval import RAGEvaluator
from app.models.schemas import TutorProfile
from app.rag.retriever import TutorRetriever
from app.storage.repositories import load_tutors_from_json
from scripts.audit_tutor_data import quality_reasons


@dataclass
class RetrievalQualityCaseResult:
    case_id: str
    query: str
    expected_tutor_names: list[str]
    retrieved_tutor_names: list[str]
    hit_tutor_names: list[str]
    recall: float
    precision: float
    rank_of_first_hit: int | None
    top1_hit: bool
    has_interference: bool
    interference_tutor_names: list[str]
    extra_valid_tutor_names: list[str]
    notes: list[str]


@dataclass
class RetrievalQualityReport:
    case_count: int
    avg_recall: float
    avg_precision: float
    avg_hit_count: float
    avg_rank_of_first_hit: float
    top1_hit_rate: float
    interference_case_count: int
    exact_match_case_count: int
    result: list[RetrievalQualityCaseResult]


class RetrievalQualityError(RuntimeError):
    pass


class InMemoryTutorRepository:
    def __init__(self, profiles: list[TutorProfile]):
        self.profiles = profiles
        for index, profile in enumerate(self.profiles):
            profile.id = profile.id or f"in-memory-{index}"

    def list(self, limit: int = 200) -> list[TutorProfile]:
        return self.profiles[:limit]

    def get(self, tutor_id: str) -> TutorProfile | None:
        return next((profile for profile in self.profiles if profile.id == tutor_id), None)


class EmptyVectorStore:
    def query(self, text: str, limit: int = 5) -> list[str]:
        return []


def build_retriever(sample_path: str = "") -> TutorRetriever:
    if not sample_path:
        return TutorRetriever()
    profiles = load_tutors_from_json(sample_path)
    return TutorRetriever(repository=InMemoryTutorRepository(profiles), vector_store=EmptyVectorStore())


def evaluate_retrieval_quality(limit: int = 5, strategy: str = "reranker", dataset_path: str = "data/sample/rag_eval.json", sample_path: str = "") -> RetrievalQualityReport:
    try:
        evaluator = RAGEvaluator(retriever=build_retriever(sample_path), dataset_path=dataset_path)
    except TypeError:
        evaluator = RAGEvaluator()
    retriever = getattr(evaluator, "retriever", None) or build_retriever(sample_path)
    cases = evaluator.load_cases()
    results: list[RetrievalQualityCaseResult] = []
    hit_counts: list[int] = []
    first_hit_ranks: list[int] = []
    interference_case_count = 0
    exact_match_case_count = 0

    for case in cases:
        retrieved = retriever.search(case.query, limit=limit, strategy=strategy)
        retrieved_names = [profile.name for profile in retrieved]
        expected = set(case.expected_tutor_names)
        hits = [name for name in retrieved_names if name in expected]
        notes: list[str] = []
        interference_names: list[str] = []
        extra_valid_names: list[str] = []
        for profile in retrieved:
            if profile.name in expected:
                continue
            reasons = quality_reasons(profile)
            if reasons:
                interference_names.append(profile.name)
                notes.append(f"{profile.name}: {';'.join(reasons)}")
            else:
                extra_valid_names.append(profile.name)
        if interference_names:
            interference_case_count += 1
            notes.append(f"interference={','.join(interference_names)}")
        if set(retrieved_names[: len(expected)]) == expected and expected:
            exact_match_case_count += 1
            notes.append("exact_top_match")
        recall = len(hits) / len(expected) if expected else 0.0
        precision = len(hits) / len(retrieved_names) if retrieved_names else 0.0
        first_hit = next((index + 1 for index, name in enumerate(retrieved_names) if name in expected), None)
        top1_hit = bool(retrieved_names and retrieved_names[0] in expected)
        hit_counts.append(len(hits))
        if first_hit:
            first_hit_ranks.append(first_hit)
        results.append(RetrievalQualityCaseResult(
            case_id=case.id,
            query=case.query,
            expected_tutor_names=case.expected_tutor_names,
            retrieved_tutor_names=retrieved_names,
            hit_tutor_names=hits,
            recall=round(recall, 4),
            precision=round(precision, 4),
            rank_of_first_hit=first_hit,
            top1_hit=top1_hit,
            has_interference=bool(interference_names),
            interference_tutor_names=interference_names,
            extra_valid_tutor_names=extra_valid_names,
            notes=notes,
        ))

    avg_recall = round(sum(item.recall for item in results) / len(results), 4) if results else 0.0
    avg_precision = round(sum(item.precision for item in results) / len(results), 4) if results else 0.0
    avg_hit_count = round(sum(hit_counts) / len(hit_counts), 4) if hit_counts else 0.0
    avg_rank_of_first_hit = round(sum(first_hit_ranks) / len(first_hit_ranks), 4) if first_hit_ranks else 0.0
    top1_hit_rate = round(sum(1 for item in results if item.top1_hit) / len(results), 4) if results else 0.0
    return RetrievalQualityReport(
        case_count=len(results),
        avg_recall=avg_recall,
        avg_precision=avg_precision,
        avg_hit_count=avg_hit_count,
        avg_rank_of_first_hit=avg_rank_of_first_hit,
        top1_hit_rate=top1_hit_rate,
        interference_case_count=interference_case_count,
        exact_match_case_count=exact_match_case_count,
        result=results,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate whether retrieval returns the correct tutor data instead of interference.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--strategy", default="reranker")
    parser.add_argument("--dataset", default="data/sample/rag_eval.json")
    parser.add_argument("--sample", default="", help="Optional tutor sample JSON for isolated evaluation instead of the runtime tutor database.")
    parser.add_argument("--min-avg-recall", type=float, default=0.5)
    parser.add_argument("--min-top1-hit-rate", type=float, default=0.0)
    parser.add_argument("--max-interference-cases", type=int, default=0)
    args = parser.parse_args()

    report = evaluate_retrieval_quality(limit=args.limit, strategy=args.strategy, dataset_path=args.dataset, sample_path=args.sample)
    payload = asdict(report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if report.avg_recall < args.min_avg_recall or report.top1_hit_rate < args.min_top1_hit_rate or report.interference_case_count > args.max_interference_cases:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
