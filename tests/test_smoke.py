import os

import pytest
import requests

os.environ["LLM_PROVIDER"] = "none"

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    client = TestClient(app)
    response = client.get("/api/health", headers={"X-Request-ID": "test-request-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"
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
    assert payload["trace_id"]
    assert payload["tutors"]
    assert payload["retrieval_evidence"]
    assert any("**" in item["snippet"] for item in payload["retrieval_evidence"])
    assert payload["plan"]["steps"]
    assert payload["trace"]
    assert any(item["agent"] == "Planner Agent" for item in payload["trace"])

    trace_response = client.get(f"/api/traces/{payload['trace_id']}")
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()
    assert trace_payload["source"] == "chat"
    assert trace_payload["trace"]

    session_traces_response = client.get("/api/traces/session/test-session")
    assert session_traces_response.status_code == 200
    assert any(item["trace_id"] == payload["trace_id"] for item in session_traces_response.json()["runs"])

    session_plans_response = client.get("/api/plans/session/test-session")
    assert session_plans_response.status_code == 200
    plan_runs = session_plans_response.json()["runs"]
    assert plan_runs
    assert plan_runs[0]["trace_id"] == payload["trace_id"]
    assert plan_runs[0]["plan"]["steps"]

    plan_response = client.get(f"/api/plans/{plan_runs[0]['plan_id']}")
    assert plan_response.status_code == 200
    assert plan_response.json()["plan_id"] == plan_runs[0]["plan_id"]


def test_memory_builds_procedural_profile():
    client = TestClient(app)
    session_id = "procedural-session"
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "我希望先查论文和主页再联系导师，帮我准备中文邮件模板和简历，表达要简洁正式，并按时间线定期跟进"},
    )
    assert response.status_code == 200
    procedural = response.json()["memory"]["procedural"]

    assert "先查论文和主页再联系" in procedural["workflow_preferences"]
    assert "偏好邮件模板" in procedural["material_preferences"]
    assert "偏好简历优化" in procedural["material_preferences"]
    assert "沟通风格偏正式" in procedural["communication_preferences"]
    assert "希望表达简洁直接" in procedural["communication_preferences"]
    assert "需要申请时间线" in procedural["scheduling_preferences"]
    assert "需要定期跟进" in procedural["scheduling_preferences"]


def test_memory_builds_semantic_profile():
    client = TestClient(app)
    session_id = "semantic-session"
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "我想找武汉多模态方向、近三年有顶会论文和企业合作、主页信息完整并且仍在招生的硕士导师"},
    )
    assert response.status_code == 200
    semantic = response.json()["memory"]["semantic"]

    assert "多模态" in semantic["research_focus"]
    assert "顶会论文导向" in semantic["application_strategy"]
    assert "企业合作导向" in semantic["application_strategy"]
    assert "地域优先" in semantic["application_strategy"]
    assert "偏好有招生信息的导师" in semantic["advisor_preferences"]
    assert "偏好主页信息完整的导师" in semantic["advisor_preferences"]


def test_memory_records_episodic_events():
    client = TestClient(app)
    session_id = "episodic-session"
    response = client.post("/api/chat", json={"session_id": session_id, "message": "我已经联系了张三老师，也想收藏李四教授，但不要王五导师"})
    assert response.status_code == 200
    events = response.json()["memory"]["episodic_events"]

    assert any(event["type"] == "contacted" and event["tutor_name"] == "张三" for event in events)
    assert any(event["type"] == "favorited" and event["tutor_name"] == "李四" for event in events)
    assert any(event["type"] == "rejected" and event["tutor_name"] == "王五" for event in events)

    memory_response = client.get(f"/api/memory/{session_id}")
    assert memory_response.status_code == 200
    assert memory_response.json()["episodic_events"]


def test_chat_uses_relevant_memory_in_answer():
    client = TestClient(app)
    session_id = "memory-retrieval-session"
    first = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "我已经联系了张三老师，想找多模态方向硕士，并且希望先查论文和主页再联系导师"},
    )
    assert first.status_code == 200
    assert first.json()["memory"]["reflections"]

    second = client.post("/api/chat", json={"session_id": session_id, "message": "继续帮我推荐多模态方向导师"})
    assert second.status_code == 200
    payload = second.json()

    assert "历史记忆参考" in payload["answer"]
    assert "多模态" in payload["answer"]
    assert "reflection:" in payload["answer"]
    assert any(item["action"] == "retrieve_relevant_memory" and item["metadata"]["memory_count"] > 0 for item in payload["trace"])


def test_memory_builds_reflections():
    client = TestClient(app)
    session_id = "reflection-session"
    response = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "我想找多模态和RAG方向硕士，偏好顶会论文和主页信息完整，先查论文和主页再联系，风险是不确定是否招生"},
    )
    assert response.status_code == 200
    reflections = response.json()["memory"]["reflections"]

    assert any(item["topic"] == "long_term_goal" and "多模态" in item["content"] for item in reflections)
    assert any(item["topic"] == "strategy" and "顶会论文导向" in item["content"] for item in reflections)
    assert any(item["topic"] == "workflow" and "先查论文和主页再联系" in item["content"] for item in reflections)
    assert any(item["topic"] == "risk" and "需核实导师最新招生状态" in item["content"] for item in reflections)


def test_chat_replans_with_previous_constraints():
    client = TestClient(app)
    session_id = "replan-session"
    first = client.post("/api/chat", json={"session_id": session_id, "message": "我想申请 RAG 方向硕士，偏好上海"})
    assert first.status_code == 200
    first_plan = first.json()["plan"]
    assert first_plan["is_replan"] is False

    second = client.post("/api/chat", json={"session_id": session_id, "message": "另外优先考虑武汉和多模态方向"})
    assert second.status_code == 200
    second_payload = second.json()
    second_plan = second_payload["plan"]

    assert second_plan["is_replan"] is True
    assert second_plan["replan_from"]
    assert "RAG" in second_plan["constraints"]
    assert "上海" in second_plan["constraints"]
    assert "武汉" in second_plan["constraints"]
    assert "多模态" in second_plan["constraints"]
    assert any(item["action"] == "replan_task" for item in second_payload["trace"])


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


def test_api_errors_have_consistent_shape():
    client = TestClient(app)
    response = client.get("/api/traces/missing", headers={"X-Request-ID": "missing-trace-request"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "missing-trace-request"
    assert response.json() == {"error": "http_error", "detail": "Trace not found", "request_id": "missing-trace-request"}


def test_browser_agent_retries_and_classifies_timeout(monkeypatch):
    from app.agents.browser_agent import BrowserAgent, BrowserFetchError

    class FakeSettings:
        request_timeout_seconds = 1
        browser_fetch_retries = 2

    calls = []
    monkeypatch.setattr("app.agents.browser_agent.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.agents.browser_agent.time.sleep", lambda seconds: None)

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise requests.Timeout("slow upstream")

    monkeypatch.setattr("app.agents.browser_agent.requests.get", fake_get)

    with pytest.raises(BrowserFetchError) as exc_info:
        BrowserAgent().fetch("https://example.edu.cn/profile")

    assert len(calls) == 2
    assert exc_info.value.reason == "timeout"
    assert exc_info.value.attempts == 2


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


def test_browser_research_clamps_configured_limits(monkeypatch):
    from app.models.schemas import BrowserResearchRequest
    from app.services.browser_research import BrowserResearchService

    class FakeSettings:
        max_browser_search_pages = 1
        max_browser_candidates = 2
        max_browser_ingest = 1
        max_browser_navigation_pages = 3

    monkeypatch.setattr("app.services.browser_research.get_settings", lambda: FakeSettings())

    request = BrowserResearchRequest(query="人工智能 导师", max_search_pages=5, max_candidates=9, max_ingest=4, max_navigation_pages=10)
    clamped = BrowserResearchService()._clamp_request(request)

    assert clamped.max_search_pages == 1
    assert clamped.max_candidates == 2
    assert clamped.max_ingest == 1
    assert clamped.max_navigation_pages == 3


def test_browser_research_endpoint(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.services.browser_research import BrowserResearchService
    from app.services.ingestion import IngestionService

    def fake_fetch(self, url, use_playwright=False, actions=None):
        if "search" in url:
            if not hasattr(fake_fetch, "failed_once"):
                fake_fetch.failed_once = True
                raise RuntimeError("temporary search failure")
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
    monkeypatch.setattr(BrowserResearchService, "_build_search_urls", lambda self, request, rewritten_queries: ["https://example.com/search?q=demo", "https://example.com/search?q=demo2"])

    client = TestClient(app)
    response = client.post(
        "/api/browser/research",
        json={"query": "人工智能 多模态 导师", "max_search_pages": 1, "max_candidates": 3, "max_ingest": 1, "navigation_depth": 1, "use_playwright": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_id"]
    assert payload["rewritten_queries"]
    assert payload["candidates"]
    assert payload["tutors"]
    assert payload["tutors"][0]["name"] == "张三"
    assert any(item["agent"] == "Query Rewriter Agent" for item in payload["trace"])
    assert any(item["action"] == "browse_search_page" and item["status"] == "failed" and item["metadata"]["error_type"] == "RuntimeError" for item in payload["trace"])
    assert any(item["action"] == "discover_navigation_links" for item in payload["trace"])
    assert any(item["agent"] == "Browser Agent" for item in payload["trace"])

    trace_response = client.get(f"/api/traces/{payload['trace_id']}")
    assert trace_response.status_code == 200
    assert trace_response.json()["source"] == "browser_research"
