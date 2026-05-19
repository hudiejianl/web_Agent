from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests


@dataclass
class BrowserQualityResult:
    ok: bool
    query: str
    trace_id: str
    detail: str
    quality_report: dict[str, Any]


class BrowserQualityCheckError(RuntimeError):
    pass


def request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 90), **kwargs)
    response.raise_for_status()
    return response.json()


def run_browser_quality_check(
    base_url: str,
    query: str,
    max_candidates: int = 6,
    max_ingest: int = 3,
    navigation_depth: int = 2,
    max_navigation_pages: int = 6,
    min_eligible: int = 1,
    min_average_quality: float = 0.2,
    use_playwright: bool = True,
) -> BrowserQualityResult:
    base_url = base_url.rstrip("/")
    payload = request_json(
        "POST",
        f"{base_url}/api/browser/research",
        json={
            "query": query,
            "max_search_pages": 1,
            "max_candidates": max_candidates,
            "max_ingest": max_ingest,
            "navigation_depth": navigation_depth,
            "max_navigation_pages": max_navigation_pages,
            "use_playwright": use_playwright,
            "dry_run": True,
        },
    )
    report = payload.get("quality_report") or {}
    eligible = int(report.get("eligible_candidates") or 0)
    average_quality = float(report.get("average_profile_quality_score") or 0.0)
    dry_run = payload.get("dry_run") is True
    ok = dry_run and eligible >= min_eligible and average_quality >= min_average_quality
    detail = f"eligible={eligible}, average_quality={average_quality:.4f}, rejected={report.get('rejected_candidates', 0)}"
    result = BrowserQualityResult(ok=ok, query=payload.get("query", query), trace_id=payload.get("trace_id", ""), detail=detail, quality_report=report)
    if not ok:
        raise BrowserQualityCheckError(detail)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Browser Research dry-run quality check against a running FastAPI server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--query", default="武汉 多模态 人工智能 导师 个人主页")
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--max-ingest", type=int, default=3)
    parser.add_argument("--navigation-depth", type=int, default=2)
    parser.add_argument("--max-navigation-pages", type=int, default=6)
    parser.add_argument("--min-eligible", type=int, default=1)
    parser.add_argument("--min-average-quality", type=float, default=0.2)
    parser.add_argument("--no-playwright", action="store_true")
    args = parser.parse_args()

    result = run_browser_quality_check(
        base_url=args.base_url,
        query=args.query,
        max_candidates=args.max_candidates,
        max_ingest=args.max_ingest,
        navigation_depth=args.navigation_depth,
        max_navigation_pages=args.max_navigation_pages,
        min_eligible=args.min_eligible,
        min_average_quality=args.min_average_quality,
        use_playwright=not args.no_playwright,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
