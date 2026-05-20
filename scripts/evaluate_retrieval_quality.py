from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.rag_eval import RAGEvaluator
from app.rag.retriever import TutorRetriever
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
    interference_case_count: int
    exact_match_case_count: int
    result: list[RetrievalQualityCaseResult]


class RetrievalQualityError(RuntimeError):
    pass


def evaluate_retrieval_quality(limit: int = 5, strategy: str = "reranker") -> RetrievalQualityReport:
    evaluator = RAGEvaluator()
    retriever = TutorRetriever()
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
        hit_counts.append(len(hits))
        if hits:
            first_hit = next((index + 1 for index, name in enumerate(retrieved_names) if name in expected), 0)
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
            has_interference=bool(interference_names),
            interference_tutor_names=interference_names,
            extra_valid_tutor_names=extra_valid_names,
            notes=notes,
        ))

    avg_recall = round(sum(item.recall for item in results) / len(results), 4) if results else 0.0
    avg_precision = round(sum(item.precision for item in results) / len(results), 4) if results else 0.0
    avg_hit_count = round(sum(hit_counts) / len(hit_counts), 4) if hit_counts else 0.0
    avg_rank_of_first_hit = round(sum(first_hit_ranks) / len(first_hit_ranks), 4) if first_hit_ranks else 0.0
    return RetrievalQualityReport(
        case_count=len(results),
        avg_recall=avg_recall,
        avg_precision=avg_precision,
        avg_hit_count=avg_hit_count,
        avg_rank_of_first_hit=avg_rank_of_first_hit,
        interference_case_count=interference_case_count,
        exact_match_case_count=exact_match_case_count,
        result=results,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate whether retrieval returns the correct tutor data instead of interference.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--strategy", default="reranker")
    parser.add_argument("--min-avg-recall", type=float, default=0.5)
    parser.add_argument("--max-interference-cases", type=int, default=0)
    args = parser.parse_args()

    report = evaluate_retrieval_quality(limit=args.limit, strategy=args.strategy)
    payload = asdict(report)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if report.avg_recall < args.min_avg_recall or report.interference_case_count > args.max_interference_cases:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
