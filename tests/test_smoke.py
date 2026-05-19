import os

import pytest
import requests

os.environ["LLM_PROVIDER"] = "none"

from fastapi.testclient import TestClient

from app.main import app


def test_settings_clamp_risky_limits(monkeypatch):
    from app.config import Settings

    settings = Settings(
        max_browser_search_pages=99,
        max_browser_candidates=999,
        max_browser_ingest=999,
        max_browser_navigation_pages=999,
        browser_fetch_retries=0,
        rag_chunk_size=1,
        rag_chunk_overlap=9999,
        max_context_messages=1,
        summary_trigger_messages=999,
        request_timeout_seconds=0,
    )

    assert settings.max_browser_search_pages == 5
    assert settings.max_browser_candidates == 50
    assert settings.max_browser_ingest == 20
    assert settings.max_browser_navigation_pages == 50
    assert settings.browser_fetch_retries == 1
    assert settings.rag_chunk_size == 100
    assert settings.rag_chunk_overlap == 1000
    assert settings.max_context_messages == 2
    assert settings.summary_trigger_messages == 100
    assert settings.request_timeout_seconds == 1


def test_observability_is_optional(monkeypatch):
    from app import observability

    class DisabledSettings:
        enable_opentelemetry = False
        otel_service_name = "test-service"
        otel_exporter_otlp_endpoint = ""

    monkeypatch.setattr("app.observability.get_settings", lambda: DisabledSettings())
    observability.configure_observability()

    with observability.request_span("test"):
        assert True


def test_observability_handles_missing_dependencies(monkeypatch):
    from app import observability

    class EnabledSettings:
        enable_opentelemetry = True
        otel_service_name = "test-service"
        otel_exporter_otlp_endpoint = ""

    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("app.observability.get_settings", lambda: EnabledSettings())
    monkeypatch.setattr("builtins.__import__", fake_import)

    observability.configure_observability()


def test_run_script_invokes_uvicorn(monkeypatch):
    from scripts import run

    calls = []
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("RELOAD", "true")
    monkeypatch.setattr(run.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    run.main()

    assert calls == [(("app.main:app",), {"host": "0.0.0.0", "port": 9000, "reload": True})]


def test_tutor_data_audit_flags_noisy_records():
    from app.models.schemas import TutorProfile
    from scripts.audit_tutor_data import audit_profiles

    valid = TutorProfile(name="张三", institution="示例大学", department="计算机学院", homepage="https://cs.example.edu.cn/teacher/zhangsan", research_areas=["人工智能"], summary="张三教授研究方向为人工智能。")
    noisy = TutorProfile(name="site:edu.cn 武汉 多模态 人", institution="未知机构", homepage="https://www.bing.com/search?q=demo", summary="旅游 bing 未知")

    report = audit_profiles([valid, noisy])

    assert report.total == 2
    assert report.valid == 1
    assert report.invalid == 1
    assert report.issues[0].name == noisy.name
    assert "invalid_source_url" in report.issues[0].reasons
    assert "noisy_name" in report.issues[0].reasons


def test_clean_invalid_tutors_dry_run(monkeypatch):
    from app.models.schemas import TutorProfile
    from scripts import clean_invalid_tutors

    valid = TutorProfile(id="valid", name="张三", institution="示例大学", department="计算机学院", homepage="https://cs.example.edu.cn/teacher/zhangsan", research_areas=["人工智能"], summary="张三教授研究方向为人工智能。")
    noisy = TutorProfile(id="bad", name="site:edu.cn 武汉 多模态 人", institution="未知机构", homepage="https://www.bing.com/search?q=demo", summary="旅游 bing 未知")
    monkeypatch.setattr(clean_invalid_tutors, "load_profiles", lambda: [valid, noisy])

    result = clean_invalid_tutors.clean_invalid_tutors(dry_run=True)

    assert result["dry_run"] is True
    assert result["would_delete_count"] == 1
    assert result["deleted_count"] == 0
    assert result["remaining_report"]["quality_passed"] is True


def test_ingest_url_rejects_noisy_profile(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.services.ingestion import IngestionService, ProfileQualityError

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {"url": url, "title": "Search", "text": "site:edu.cn 武汉 多模态 人工智能 导师 旅游 bing 未知", "links": []}

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)

    with pytest.raises(ProfileQualityError) as exc:
        IngestionService().ingest_url("https://www.bing.com/search?q=site%3Aedu.cn")

    assert "搜索结果页" in str(exc.value)


def test_ingest_url_accepts_quality_profile(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import TutorProfile
    from app.services.ingestion import IngestionService

    saved = []

    class FakeRepository:
        def upsert(self, profile: TutorProfile) -> TutorProfile:
            profile.id = "manual-ingest"
            saved.append(profile)
            return profile

    class FakeVectorStore:
        def upsert_tutor(self, profile: TutorProfile) -> None:
            return None

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {
            "url": url,
            "title": "张三 教授 - 示例大学计算机学院",
            "text": "张三 教授 示例大学 计算机学院 个人主页 教师简介 研究方向 人工智能 多模态 招生 代表论文 zhangsan@example.edu.cn " * 8,
            "links": [{"text": "代表论文", "url": "https://cs.example.edu.cn/teacher/zhangsan/papers"}],
        }

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)

    profile = IngestionService(repository=FakeRepository(), vector_store=FakeVectorStore()).ingest_url("https://cs.example.edu.cn/teacher/zhangsan")

    assert profile.id == "manual-ingest"
    assert profile.name == "张三"
    assert saved[0].homepage == "https://cs.example.edu.cn/teacher/zhangsan"


def test_ingest_url_preview_does_not_index(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import TutorProfile
    from app.services.ingestion import IngestionService

    class FakeRepository:
        def upsert(self, profile: TutorProfile) -> TutorProfile:
            raise AssertionError("preview_url must not write profiles")

    class FakeVectorStore:
        def upsert_tutor(self, profile: TutorProfile) -> None:
            raise AssertionError("preview_url must not index profiles")

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {
            "url": url,
            "title": "张三 教授 - 示例大学计算机学院",
            "text": "张三 教授 示例大学 计算机学院 个人主页 教师简介 研究方向 人工智能 多模态 招生 代表论文 zhangsan@example.edu.cn " * 8,
            "links": [],
        }

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)

    preview = IngestionService(repository=FakeRepository(), vector_store=FakeVectorStore()).preview_url("https://cs.example.edu.cn/teacher/zhangsan")

    assert preview.indexed is False
    assert preview.ingest_eligible is True
    assert preview.profile_quality_score >= 0.55
    assert preview.tutor.name == "张三"


def test_ingest_url_preview_endpoint(monkeypatch):
    from app.agents.browser_agent import BrowserAgent

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {
            "url": url,
            "title": "张三 教授 - 示例大学计算机学院",
            "text": "张三 教授 示例大学 计算机学院 个人主页 教师简介 研究方向 人工智能 多模态 招生 代表论文 zhangsan@example.edu.cn " * 8,
            "links": [],
        }

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)

    response = TestClient(app).post("/api/ingest/url/preview", json={"url": "https://cs.example.edu.cn/teacher/zhangsan"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["indexed"] is False
    assert payload["ingest_eligible"] is True
    assert payload["profile_quality_score"] >= 0.55
    assert payload["tutor"]["name"] == "张三"


def test_demo_check_runs_core_endpoints(monkeypatch):
    from scripts import demo_check

    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_request(method, url, timeout=30, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/health"):
            return FakeResponse({"status": "ok", "app": "demo"})
        if url.endswith("/api/chat"):
            return FakeResponse({"answer": "建议", "trace_id": "trace-1", "plan": {"steps": [{"id": "retrieve"}]}, "tutors": [{"name": "李老师"}]})
        if url.endswith("/api/browser/seed-sites"):
            return FakeResponse({"sites": [{"score": 3.0, "reason": "匹配武汉"}]})
        if url.endswith("/api/eval/rag/dataset"):
            return FakeResponse({"case_count": 1, "cases": [{"id": "case-1"}]})
        if url.endswith("/api/eval/rag/compare"):
            return FakeResponse({"strategies": [{"strategy": "baseline"}, {"strategy": "hybrid"}, {"strategy": "reranker"}]})
        raise AssertionError(url)

    monkeypatch.setattr(demo_check.requests, "request", fake_request)

    results = demo_check.run_checks("http://server.local/", session_id="demo")

    assert [result.name for result in results] == ["health", "chat", "seed-sites", "rag-dataset", "rag-compare"]
    assert all(result.ok for result in results)
    assert calls[1][2]["json"]["session_id"] == "demo"


def test_browser_quality_check_uses_dry_run(monkeypatch):
    from scripts import browser_quality_check

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "query": "武汉 多模态",
                "trace_id": "trace-browser",
                "dry_run": True,
                "quality_report": {
                    "eligible_candidates": 2,
                    "rejected_candidates": 1,
                    "average_profile_quality_score": 0.42,
                },
            }

    def fake_request(method, url, timeout=90, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(browser_quality_check.requests, "request", fake_request)

    result = browser_quality_check.run_browser_quality_check("http://server.local/", "武汉 多模态", min_eligible=1, min_average_quality=0.2)

    assert result.ok is True
    assert result.trace_id == "trace-browser"
    assert "eligible=2" in result.detail
    assert calls[0][1] == "http://server.local/api/browser/research"
    assert calls[0][2]["json"]["dry_run"] is True


def test_browser_quality_check_fails_low_quality(monkeypatch):
    from scripts import browser_quality_check

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"query": "武汉 多模态", "trace_id": "trace-browser", "dry_run": True, "quality_report": {"eligible_candidates": 0, "rejected_candidates": 3, "average_profile_quality_score": 0.05}}

    monkeypatch.setattr(browser_quality_check.requests, "request", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(browser_quality_check.BrowserQualityCheckError):
        browser_quality_check.run_browser_quality_check("http://server.local/", "武汉 多模态", min_eligible=1, min_average_quality=0.2)


def test_health():
    client = TestClient(app)
    response = client.get("/api/health", headers={"X-Request-ID": "test-request-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-id"
    assert response.json()["status"] == "ok"


def test_index_serves_workflow_ui():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "工作流可视化" in response.text
    assert "系统能力概览" in response.text
    assert "loadCapabilities" in response.text
    assert "navigationDepth" in response.text
    assert "匹配高校入口" in response.text
    assert "仅预检不入库" in response.text
    assert "previewIngestUrl" in response.text
    assert "loadSeedSites" in response.text
    assert "escapeHtml" in response.text


def test_system_capabilities_endpoint():
    client = TestClient(app)
    response = client.get("/api/system/capabilities")

    assert response.status_code == 200
    payload = response.json()
    names = {item["name"] for item in payload["capabilities"]}
    assert "Multi-Agent Workflow" in names
    assert "RAG Retrieval" in names
    assert "Browser Research" in names
    assert payload["next_recommended_steps"]


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
    step_statuses = {step["id"]: step["status"] for step in payload["plan"]["steps"]}
    assert step_statuses["check_recent_papers"] in {"completed", "skipped"}
    assert step_statuses["analyze_research_fit"] in {"completed", "skipped"}
    assert step_statuses["check_admission_status"] in {"completed", "skipped"}
    assert step_statuses["score_candidates"] == "completed"
    assert payload["trace"]
    assert any(item["agent"] == "Planner Agent" for item in payload["trace"])
    assert payload["agent_handoffs"]
    assert any(item["source_agent"] == "Memory Agent" and item["target_agent"] == "Planner Agent" for item in payload["agent_handoffs"])
    assert any(item["payload_type"] == "retrieval_results" for item in payload["agent_handoffs"])

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


def test_memory_resolves_preference_conflicts():
    client = TestClient(app)
    session_id = "conflict-session"
    first = client.post("/api/chat", json={"session_id": session_id, "message": "我想申请硕士，偏好上海，并且收藏张三老师"})
    assert first.status_code == 200

    second = client.post("/api/chat", json={"session_id": session_id, "message": "改成博士，只考虑北京，不要张三老师"})
    assert second.status_code == 200
    memory = second.json()["memory"]

    assert memory["profile"]["target_degree"] == "博士"
    assert memory["profile"]["preferred_locations"] == ["北京"]
    assert any(item["field"] == "target_degree" and item["previous"] == "硕士" and item["current"] == "博士" for item in memory["conflicts"])
    assert any(item["field"] == "preferred_locations" and item["previous"] == "上海" and item["current"] == "北京" for item in memory["conflicts"])
    assert any(item["field"] == "episodic_events" and "张三" in item["current"] for item in memory["conflicts"])
    assert not any(event["type"] == "favorited" and event["tutor_name"] == "张三" for event in memory["episodic_events"])
    assert any(event["type"] == "rejected" and event["tutor_name"] == "张三" for event in memory["episodic_events"])


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


def test_context_compressor_builds_structured_summary():
    from app.memory.compression import ContextCompressor
    from app.models.schemas import MemoryEvent, MemoryState

    memory = MemoryState(session_id="compress-session")
    memory.profile.research_interests = ["多模态", "RAG"]
    memory.profile.preferred_locations = ["上海"]
    memory.profile.target_degree = "硕士"
    memory.semantic.application_strategy = ["顶会论文导向"]
    memory.procedural.workflow_preferences = ["先查论文和主页再联系"]
    memory.episodic_events = [MemoryEvent(type="contacted", tutor_name="张三")]
    memory.recent_messages = [
        {"role": "user", "content": "第一轮对话"},
        {"role": "assistant", "content": "第二轮回复"},
        {"role": "user", "content": "第三轮对话"},
    ]

    summary = ContextCompressor(recent_window=2).compress(memory)

    assert "用户画像" in summary
    assert "多模态" in summary
    assert "顶会论文导向" in summary
    assert "先查论文和主页再联系" in summary
    assert "contacted:张三" in summary
    assert "第一轮对话" not in summary
    assert "第三轮对话" in summary


def test_planner_decomposes_research_workflow():
    from app.agents.planner_agent import PlannerAgent

    plan = PlannerAgent().plan("帮我找武汉地区做多模态方向、近三年发过顶会、并且有企业合作的导师")
    step_ids = [step.id for step in plan.steps]

    assert [
        "retrieve_tutors",
        "check_recent_papers",
        "analyze_research_fit",
        "check_admission_status",
        "score_candidates",
        "generate_advice",
    ] == step_ids[-6:]
    assert "武汉" in plan.constraints
    assert "近三年" in plan.constraints
    assert "企业合作" in plan.constraints
    assert plan.steps[-1].depends_on == ["score_candidates"]


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
    assert "| Strategy | Cases | Recall | Precision | Relevance | Faithfulness |" in report_payload["markdown"]
    assert "faithfulness" in payload
    assert "faithfulness" in payload["cases"][0]
    assert [item["strategy"] for item in report_payload["comparison"]["strategies"]] == ["baseline", "hybrid", "reranker"]

    runs_response = client.get("/api/eval/rag/runs?limit=3")
    assert runs_response.status_code == 200
    runs = runs_response.json()["runs"]
    assert runs
    assert {item["source"] for item in runs} & {"single", "compare", "report"}

    run_response = client.get(f"/api/eval/rag/runs/{runs[0]['evaluation_id']}")
    assert run_response.status_code == 200
    assert run_response.json()["evaluation_id"] == runs[0]["evaluation_id"]

    configurations_response = client.get("/api/eval/rag/configurations")
    assert configurations_response.status_code == 200
    configurations_payload = configurations_response.json()
    assert configurations_payload["configurations"]
    assert all(item["config"] for item in configurations_payload["configurations"])

    dataset_response = client.get("/api/eval/rag/dataset")
    assert dataset_response.status_code == 200
    dataset_payload = dataset_response.json()
    assert dataset_payload["case_count"] >= 3
    assert "李若水" in dataset_payload["unique_expected_tutors"]
    assert "上海" in dataset_payload["covered_locations"]
    assert "RAG" in dataset_payload["covered_research_terms"]


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


def test_browser_seed_sites_endpoint():
    client = TestClient(app)
    response = client.get("/api/browser/seed-sites?q=武汉 多模态")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sites"]
    assert payload["sites"][0]["score"] > 0
    assert "武汉" in payload["sites"][0]["matched_terms"]
    assert payload["sites"][0]["reason"]
    assert any("武汉" in item["tags"] for item in payload["sites"])


def test_browser_seed_sites_ranks_institution_and_research_terms():
    client = TestClient(app)
    response = client.get("/api/browser/seed-sites?q=浙江大学 医学影像 人工智能")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sites"]
    assert payload["sites"][0]["institution"] == "浙江大学"
    assert "医学影像" in payload["sites"][0]["matched_terms"]
    assert "浙江大学" in payload["sites"][0]["reason"]


def test_browser_research_uses_seed_sites_when_seed_urls_missing(monkeypatch):
    from app.models.schemas import BrowserResearchRequest, UniversitySeedSite
    from app.services.browser_research import BrowserResearchService
    from app.services.seed_sites import UniversitySeedSiteService

    class FakeSeedSites(UniversitySeedSiteService):
        def list_sites(self, query: str = "", limit: int = 20):
            return [UniversitySeedSite(name="示例学院", institution="示例大学", location="武汉", url="https://cs.example.edu.cn/", tags=["武汉"], score=3.0)]

    service = BrowserResearchService(seed_sites=FakeSeedSites())
    urls = service._build_search_urls(BrowserResearchRequest(query="武汉 多模态 导师", max_search_pages=1), ["site:edu.cn 武汉 多模态 导师"])

    assert "https://cs.example.edu.cn/" in urls
    assert any("bing.com" in url for url in urls)


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


def test_browser_research_discovers_pagination_links():
    from app.services.browser_research import BrowserResearchService

    service = BrowserResearchService()
    links = [
        {"text": "下一页", "url": "https://cs.example.edu.cn/faculty/page/2"},
        {"text": "校外链接", "url": "https://other.example.com/page/2"},
        {"text": "新闻", "url": "https://cs.example.edu.cn/news/1"},
    ]

    pagination = service._pagination_links(links, "https://cs.example.edu.cn/faculty")

    assert [item.url for item in pagination] == ["https://cs.example.edu.cn/faculty/page/2"]
    assert pagination[0].reason == "分页链接"


def test_browser_research_scores_page_quality_and_confidence():
    from app.models.schemas import CandidateLink
    from app.services.browser_research import BrowserResearchService

    service = BrowserResearchService()
    high_quality = service._page_quality({"text": "张三 教授 研究方向 人工智能 多模态 招生 论文 email zhangsan@example.edu.cn" * 20, "links": [{"text": "论文", "url": "https://example.com/paper"}]})
    candidate = CandidateLink(text="张三 教授 个人主页", url="https://cs.example.edu.cn/teacher/zhangsan", score=8.0, page_quality=high_quality)
    service._score_candidate_confidence(candidate)

    assert high_quality > 0.7
    assert candidate.confidence > 0.7


def test_browser_research_follows_deep_navigation_chain(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.services.browser_research import BrowserResearchService
    from app.services.ingestion import IngestionService

    visited = []

    def fake_fetch(self, url, use_playwright=False, actions=None):
        visited.append(url)
        if "search" in url:
            return {
                "url": url,
                "title": "Search",
                "text": "search results",
                "links": [{"text": "示例大学", "url": "https://www.example.edu.cn"}],
            }
        if url == "https://www.example.edu.cn":
            return {
                "url": url,
                "title": "示例大学",
                "text": "示例大学 计算机学院 人工智能学院",
                "links": [{"text": "计算机学院", "url": "https://cs.example.edu.cn"}],
            }
        if url == "https://cs.example.edu.cn":
            return {
                "url": url,
                "title": "计算机学院",
                "text": "计算机学院 师资队伍 人工智能 多模态",
                "links": [{"text": "师资队伍", "url": "https://cs.example.edu.cn/faculty"}],
            }
        if url == "https://cs.example.edu.cn/faculty":
            return {
                "url": url,
                "title": "师资队伍",
                "text": "教师队伍 导师简介",
                "links": [{"text": "张三 教授 个人主页", "url": "https://cs.example.edu.cn/teacher/zhangsan"}],
            }
        if url == "https://cs.example.edu.cn/teacher/zhangsan":
            return {
                "url": url,
                "title": "张三 教授",
                "text": "张三 教授 研究方向 人工智能 多模态 招生 email zhangsan@example.edu.cn",
                "links": [{"text": "代表论文", "url": "https://cs.example.edu.cn/teacher/zhangsan/papers"}],
            }
        return {
            "url": url,
            "title": "代表论文",
            "text": "张三 代表论文 多模态 大模型",
            "links": [],
        }

    def fake_ingest_profile(self, profile):
        profile.id = profile.id or "deep-tutor"
        return profile

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)
    monkeypatch.setattr(IngestionService, "ingest_profile", fake_ingest_profile)
    monkeypatch.setattr(BrowserResearchService, "_build_search_urls", lambda self, request, rewritten_queries: ["https://example.com/search?q=deep"])

    client = TestClient(app)
    response = client.post(
        "/api/browser/research",
        json={"query": "人工智能 多模态 导师", "allowed_domains": ["example.edu.cn"], "max_candidates": 8, "max_ingest": 1, "navigation_depth": 4, "max_navigation_pages": 8, "use_playwright": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "https://cs.example.edu.cn/teacher/zhangsan" in visited
    assert "https://cs.example.edu.cn/teacher/zhangsan/papers" in [item["url"] for item in payload["candidates"]]
    assert {item["link_type"] for item in payload["candidates"]} & {"school", "college", "faculty_list", "profile", "paper"}
    assert any(item["action"] == "discover_navigation_links" and "深链路" in item["detail"] for item in payload["trace"])


def test_browser_research_rejects_search_page_profiles(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import BrowserResearchRequest, CandidateLink
    from app.services.browser_research import BrowserResearchService
    from app.services.ingestion import IngestionService

    ingested = []

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {"url": url, "title": "Search", "text": "site:edu.cn 武汉 多模态 人工智能 导师 旅游 bing 未知", "links": []}

    def fake_ingest_profile(self, profile):
        ingested.append(profile)
        return profile

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)
    monkeypatch.setattr(IngestionService, "ingest_profile", fake_ingest_profile)

    service = BrowserResearchService()
    candidate = CandidateLink(text="搜索结果", url="https://www.bing.com/search?q=site%3Aedu.cn", score=9.0, link_type="profile", confidence=0.9)
    tutors = service._browse_and_ingest(BrowserResearchRequest(query="武汉 多模态 导师"), [candidate], [])

    assert tutors == []
    assert ingested == []
    assert candidate.status == "skipped"
    assert candidate.ingest_eligible is False
    assert candidate.profile_quality_score == 0
    assert "搜索结果页" in candidate.error
    assert "搜索结果页" in candidate.quality_reasons[0]


def test_browser_research_precheck_skips_navigation_links(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import BrowserResearchRequest, CandidateLink
    from app.services.browser_research import BrowserResearchService

    fetched = []

    def fake_fetch(self, url, use_playwright=False, actions=None):
        fetched.append(url)
        return {"url": url, "title": "师资队伍", "text": "教师队伍", "links": []}

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)

    service = BrowserResearchService()
    candidate = CandidateLink(text="师资队伍", url="https://cs.example.edu.cn/faculty", score=8.0, link_type="faculty_list")
    tutors = service._browse_and_ingest(BrowserResearchRequest(query="人工智能 导师"), [candidate], [])

    assert tutors == []
    assert fetched == []
    assert candidate.status == "skipped"
    assert candidate.ingest_eligible is False
    assert "只用于导航发现" in candidate.error


def test_browser_research_scores_valid_profile_for_ingest(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import BrowserResearchRequest, CandidateLink
    from app.services.browser_research import BrowserResearchService
    from app.services.ingestion import IngestionService

    ingested = []

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {
            "url": url,
            "title": "张三 教授 - 示例大学计算机学院",
            "text": "张三 教授 示例大学 计算机学院 个人主页 教师简介 研究方向 人工智能 多模态 招生 代表论文 zhangsan@example.edu.cn " * 8,
            "links": [{"text": "代表论文", "url": "https://cs.example.edu.cn/teacher/zhangsan/papers"}],
        }

    def fake_ingest_profile(self, profile):
        profile.id = "valid-profile"
        ingested.append(profile)
        return profile

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)
    monkeypatch.setattr(IngestionService, "ingest_profile", fake_ingest_profile)

    service = BrowserResearchService()
    candidate = CandidateLink(text="张三 教授 个人主页", url="https://cs.example.edu.cn/teacher/zhangsan", score=9.0, link_type="profile")
    tutors = service._browse_and_ingest(BrowserResearchRequest(query="人工智能 多模态 导师"), [candidate], [])

    assert [tutor.id for tutor in tutors] == ["valid-profile"]
    assert len(ingested) == 1
    assert candidate.status == "ingested"
    assert candidate.ingest_eligible is True
    assert candidate.profile_quality_score >= 0.55
    assert "识别到研究方向" in candidate.quality_reasons


def test_browser_research_dry_run_scores_without_ingesting(monkeypatch):
    from app.agents.browser_agent import BrowserAgent
    from app.models.schemas import BrowserResearchRequest, CandidateLink
    from app.services.browser_research import BrowserResearchService
    from app.services.ingestion import IngestionService

    def fake_fetch(self, url, use_playwright=False, actions=None):
        return {
            "url": url,
            "title": "张三 教授 - 示例大学计算机学院",
            "text": "张三 教授 示例大学 计算机学院 个人主页 教师简介 研究方向 人工智能 多模态 招生 代表论文 zhangsan@example.edu.cn " * 8,
            "links": [],
        }

    def fake_ingest_profile(self, profile):
        raise AssertionError("dry_run must not write profiles")

    monkeypatch.setattr(BrowserAgent, "fetch", fake_fetch)
    monkeypatch.setattr(IngestionService, "ingest_profile", fake_ingest_profile)

    service = BrowserResearchService()
    candidate = CandidateLink(text="张三 教授 个人主页", url="https://cs.example.edu.cn/teacher/zhangsan", score=9.0, link_type="profile")
    tutors = service._browse_and_ingest(BrowserResearchRequest(query="人工智能 多模态 导师", dry_run=True), [candidate], [])

    assert [tutor.name for tutor in tutors] == ["张三"]
    assert candidate.status == "browsed"
    assert candidate.ingest_eligible is True
    assert candidate.profile_quality_score >= 0.55


def test_browser_research_quality_report_summarizes_candidates():
    from app.models.schemas import CandidateLink
    from app.services.browser_research import BrowserResearchService

    eligible = CandidateLink(text="张三", url="https://cs.example.edu.cn/teacher/zhangsan", link_type="profile", status="ingested", page_quality=0.8, profile_quality_score=0.72, confidence=0.9, ingest_eligible=True)
    rejected = CandidateLink(text="师资队伍", url="https://cs.example.edu.cn/faculty", link_type="faculty_list", status="skipped", quality_reasons=["faculty_list 链接只用于导航发现，不直接入库"])

    report = BrowserResearchService()._build_quality_report([eligible, rejected], tutor_count=1)

    assert report.total_candidates == 2
    assert report.eligible_candidates == 1
    assert report.rejected_candidates == 1
    assert report.ingested_or_previewed_tutors == 1
    assert report.average_profile_quality_score == 0.36
    assert report.status_counts == {"ingested": 1, "skipped": 1}
    assert report.link_type_counts == {"profile": 1, "faculty_list": 1}
    assert report.rejection_reasons == {"faculty_list 链接只用于导航发现，不直接入库": 1}
    assert report.top_candidates[0].url == eligible.url


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
                "links": [
                    {"text": "下一页", "url": "https://cs.example.edu.cn/faculty/page/2"},
                    {"text": "张三 教授 个人主页 研究方向 人工智能 多模态", "url": "https://cs.example.edu.cn/teacher/zhangsan"},
                ],
            }
        if url.endswith("/faculty/page/2"):
            return {
                "url": url,
                "title": "师资队伍第 2 页 - 示例大学计算机学院",
                "text": "教师队伍 大模型 智能体",
                "links": [{"text": "李四 教授 个人主页 研究方向 大模型 智能体", "url": "https://cs.example.edu.cn/teacher/lisi"}],
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
    assert payload["quality_report"]["total_candidates"] == len(payload["candidates"])
    assert payload["quality_report"]["eligible_candidates"] >= 1
    assert payload["quality_report"]["top_candidates"]
    assert payload["candidates"][0]["confidence"] > 0
    assert "page_quality" in payload["candidates"][0]
    assert payload["tutors"]
    assert payload["tutors"][0]["name"] == "张三"
    assert any(item["agent"] == "Query Rewriter Agent" for item in payload["trace"])
    assert any(item["action"] == "browse_search_page" and item["status"] == "failed" and item["metadata"]["error_type"] == "RuntimeError" for item in payload["trace"])
    assert any(item["action"] == "discover_navigation_links" and "识别分页 1" in item["detail"] for item in payload["trace"])
    assert any(item["agent"] == "Browser Agent" for item in payload["trace"])

    trace_response = client.get(f"/api/traces/{payload['trace_id']}")
    assert trace_response.status_code == 200
    assert trace_response.json()["source"] == "browser_research"
