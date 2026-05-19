from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


class DemoCheckError(RuntimeError):
    pass


def request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
    response.raise_for_status()
    return response.json()


def run_checks(base_url: str, session_id: str = "demo-check") -> list[CheckResult]:
    base_url = base_url.rstrip("/")
    results = [
        check_health(base_url),
        check_chat(base_url, session_id),
        check_seed_sites(base_url),
        check_rag_dataset(base_url),
        check_rag_compare(base_url),
    ]
    failed = [result for result in results if not result.ok]
    if failed:
        raise DemoCheckError("; ".join(f"{item.name}: {item.detail}" for item in failed))
    return results


def check_health(base_url: str) -> CheckResult:
    payload = request_json("GET", f"{base_url}/api/health")
    return CheckResult("health", payload.get("status") == "ok", payload.get("app", "unknown app"))


def check_chat(base_url: str, session_id: str) -> CheckResult:
    payload = request_json(
        "POST",
        f"{base_url}/api/chat",
        json={"session_id": session_id, "message": "我想申请 AI 和 RAG 方向硕士，偏好江浙沪，帮我推荐导师。"},
    )
    ok = bool(payload.get("answer") and payload.get("trace_id") and payload.get("plan", {}).get("steps"))
    return CheckResult("chat", ok, f"trace_id={payload.get('trace_id', '')}, tutors={len(payload.get('tutors', []))}")


def check_seed_sites(base_url: str) -> CheckResult:
    payload = request_json("GET", f"{base_url}/api/browser/seed-sites", params={"q": "武汉 多模态 人工智能", "limit": 3})
    sites = payload.get("sites", [])
    ok = bool(sites and sites[0].get("score", 0) > 0 and sites[0].get("reason"))
    return CheckResult("seed-sites", ok, f"matches={len(sites)}")


def check_rag_dataset(base_url: str) -> CheckResult:
    payload = request_json("GET", f"{base_url}/api/eval/rag/dataset")
    ok = payload.get("case_count", 0) > 0 and bool(payload.get("cases"))
    return CheckResult("rag-dataset", ok, f"cases={payload.get('case_count', 0)}")


def check_rag_compare(base_url: str) -> CheckResult:
    payload = request_json("GET", f"{base_url}/api/eval/rag/compare", params={"limit": 5})
    strategies = payload.get("strategies", [])
    names = [item.get("strategy") for item in strategies]
    ok = {"baseline", "hybrid", "reranker"}.issubset(set(names))
    return CheckResult("rag-compare", ok, f"strategies={', '.join(name for name in names if name)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an end-to-end demo check against a running FastAPI server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--session-id", default="demo-check")
    args = parser.parse_args()

    results = run_checks(args.base_url, args.session_id)
    print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
