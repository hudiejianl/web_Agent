import os

os.environ["LLM_PROVIDER"] = "none"

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_returns_tutor_recommendations():
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"session_id": "test-session", "message": "我想申请 AI 和 RAG 方向硕士，偏好江浙沪，推荐导师"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "建议" in payload["answer"] or "关注" in payload["answer"]
    assert payload["tutors"]
    assert payload["retrieval_evidence"]
    assert any("**" in item["snippet"] for item in payload["retrieval_evidence"])
    assert payload["plan"]["steps"]
    assert payload["trace"]
    assert any(item["agent"] == "Planner Agent" for item in payload["trace"])


def test_rag_evaluation_endpoint():
    client = TestClient(app)
    response = client.get("/api/eval/rag")
    assert response.status_code == 200
    payload = response.json()
    assert payload["case_count"] >= 1
    assert payload["strategy"] == "reranker"
    assert "recall" in payload
    assert payload["cases"]

    compare_response = client.get("/api/eval/rag/compare")
    assert compare_response.status_code == 200
    compare_payload = compare_response.json()
    assert [item["strategy"] for item in compare_payload["strategies"]] == ["baseline", "hybrid", "reranker"]

    report_response = client.get("/api/eval/rag/report")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert "# RAG Evaluation Report" in report_payload["markdown"]
    assert "| Strategy | Cases | Recall | Precision | Relevance |" in report_payload["markdown"]
    assert [item["strategy"] for item in report_payload["comparison"]["strategies"]] == ["baseline", "hybrid", "reranker"]


def test_browser_agent_sets_windows_proactor_policy(monkeypatch):
    import asyncio

    from app.agents import browser_agent
    from app.agents.browser_agent import BrowserAgent

    class FakeSelectorPolicy:
        pass

    class FakeProactorPolicy:
        pass

    selected_policy = FakeSelectorPolicy()
    applied = []
    monkeypatch.setattr(browser_agent.sys, "platform", "win32")
    monkeypatch.setattr(browser_agent.asyncio, "WindowsProactorEventLoopPolicy", FakeProactorPolicy, raising=False)
    monkeypatch.setattr(browser_agent.asyncio, "get_event_loop_policy", lambda: selected_policy)
    monkeypatch.setattr(browser_agent.asyncio, "set_event_loop_policy", lambda policy: applied.append(policy))

    BrowserAgent()._ensure_playwright_event_loop_policy()

    assert isinstance(applied[0], FakeProactorPolicy)


def test_browser_browse_endpoint(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import BrowserBrowseResponse

    def fake_browse(self, url, actions=None):
        return BrowserBrowseResponse(
            url=url,
            final_url=url,
            title="Demo Page",
            text="dynamic content loaded",
            links=[{"text": "Profile", "url": "https://example.com/profile"}],
            dom={"headings": [{"tag": "h1", "text": "Demo"}], "links_count": 1},
            used_playwright=True,
            actions=[{"type": "wait", "status": "completed"}],
        )

    monkeypatch.setattr(BrowserAgent, "browse", fake_browse)
    client = TestClient(app)
    response = client.post(
        "/api/browser/browse",
        json={"url": "https://example.com", "use_playwright": True, "actions": [{"type": "wait", "value": 100}]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["used_playwright"] is True
    assert payload["dom"]["headings"][0]["text"] == "Demo"


def test_browser_research_endpoint(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.services.browser_research import BrowserResearchService
    from app.services.ingestion import IngestionService

    def fake_fetch(self, url, use_playwright=False, actions=None):
        if "search" in url:
            return {
                "url": url,
                "title": "Search",
                "text": "search results",
                "links": [{"text": "示例大学 计算机学院 师资队伍", "url": "https://cs.example.edu.cn/faculty"}],
            }
        if url.endswith("/faculty"):
            return {
                "url": url,
                "title": "师资队伍 - 示例大学计算机学院",
                "text": "教师队伍 人工智能 多模态",
                "links": [{"text": "张三 教授 个人主页 研究方向 人工智能 多模态", "url": "https://cs.example.edu.cn/teacher/zhangsan"}],
            }
        return {
            "url": url,
            "title": "张三 教授 - 示例大学",
            "text": "张三 教授 示例大学 计算机学院 人工智能 多模态 zhangsan@example.edu.cn",
            "links": [],
        }

    def fake_ingest_profile(self, profile):
        profile.id = profile.id or "demo-tutor"
        return profile

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)
    monkeypatch.setattr(IngestionService, "ingest_profile", fake_ingest_profile)
    monkeypatch.setattr(BrowserResearchService, "_build_search_urls", lambda self, request, rewritten_queries: ["https://example.com/search?q=demo"])

    client = TestClient(app)
    response = client.post(
        "/api/browser/research",
        json={"query": "人工智能 多模态 导师", "max_search_pages": 1, "max_candidates": 3, "max_ingest": 1, "navigation_depth": 1, "use_playwright": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["rewritten_queries"]
    assert payload["candidates"]
    assert payload["tutors"]
    assert payload["tutors"][0]["name"] == "张三"
    assert any(item["agent"] == "Query Rewriter Agent" for item in payload["trace"])
    assert any(item["action"] == "discover_navigation_links" for item in payload["trace"])
    assert any(item["agent"] == "Browser Agent" for item in payload["trace"])
