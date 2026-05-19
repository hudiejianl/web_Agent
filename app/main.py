from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agents.browser_agent import BrowserAgent
from app.config import get_settings
from app.logging_config import configure_logging
from app.models.schemas import AgentPlanRun, AgentTraceRun, BrowserBrowseRequest, BrowserBrowseResponse, BrowserResearchRequest, BrowserResearchResponse, ChatRequest, ChatResponse, IngestUrlPreviewResponse, IngestUrlRequest, IngestUrlResponse, PlanRunResponse, RAGBenchmarkDatasetSummary, RAGConfigurationComparisonResponse, RAGEvaluationComparisonResponse, RAGEvaluationReportResponse, RAGEvaluationResponse, RAGEvaluationRun, RAGEvaluationRunResponse, SearchResponse, SystemCapabilitiesResponse, SystemCapability, TraceRunResponse, UniversitySeedSiteResponse
from app.observability import configure_observability, request_span
from app.eval.rag_eval import RAGEvaluator
from app.rag.retriever import TutorRetriever
from app.services.browser_research import BrowserResearchService
from app.services.chat import ChatService
from app.services.ingestion import IngestionService, ProfileQualityError, ensure_seed_data
from app.services.seed_sites import UniversitySeedSiteService
from app.storage.database import init_database
from app.storage.repositories import MemoryRepository, PlanRepository, RAGEvaluationRepository, TraceRepository

configure_logging()
settings = get_settings()
configure_observability()
logger = logging.getLogger("app.requests")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    ensure_seed_data()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(request, exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(request, 422, "validation_error", str(exc.errors()))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled request error request_id=%s path=%s", _request_id(request), request.url.path)
    return _error_response(request, 500, "internal_error", str(exc))


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    attributes = {"http.method": request.method, "http.route": request.url.path, "request.id": request_id}
    with request_span(f"{request.method} {request.url.path}", attributes):
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception("request failed request_id=%s method=%s path=%s duration_ms=%.2f", request_id, request.method, request.url.path, duration_ms)
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info("request completed request_id=%s method=%s path=%s status=%s duration_ms=%.2f", request_id, request.method, request.url.path, response.status_code, duration_ms)
        return response


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _error_response(request: Request, status_code: int, error: str, detail: str) -> JSONResponse:
    request_id = _request_id(request)
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(status_code=status_code, headers=headers, content={"error": error, "detail": detail, "request_id": request_id})


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService()


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/system/capabilities", response_model=SystemCapabilitiesResponse)
def system_capabilities() -> SystemCapabilitiesResponse:
    return SystemCapabilitiesResponse(
        app_name=settings.app_name,
        capabilities=[
            SystemCapability(name="Multi-Agent Workflow", features=["LangGraph workflow", "structured planning", "agent handoffs", "persistent plans and traces"]),
            SystemCapability(name="RAG Retrieval", features=["dense retrieval", "BM25", "hybrid retrieval", "reranker", "chunking", "highlighted evidence"]),
            SystemCapability(name="Memory", features=["episodic memory", "semantic memory", "procedural memory", "memory retrieval", "reflection", "conflict resolution", "context compression"]),
            SystemCapability(name="Browser Research", features=["query rewriting", "search filtering", "Playwright browsing", "deep navigation", "candidate confidence", "profile quality scoring", "dry-run precheck", "profile ingestion"]),
            SystemCapability(name="Evaluation", features=["benchmark dataset", "recall", "precision", "relevance", "faithfulness", "configuration comparison", "saved evaluation runs"]),
            SystemCapability(name="Frontend", features=["built-in workflow UI", "React/Vite workflow frontend", "Plan/Trace/Evidence/Memory/Handoff visualization"]),
            SystemCapability(name="Engineering", features=["Dockerfile", "startup script", "request IDs", "structured errors", "optional OpenTelemetry"]),
        ],
        next_recommended_steps=[
            "继续扩充高校种子站点库和真实导师 benchmark 数据",
            "可选接入官方搜索 API，替换直接搜索结果页解析",
            "部署到可访问环境并录制端到端演示流程",
        ],
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return get_chat_service().chat(request.session_id, request.message)


@app.post("/api/ingest/url/preview", response_model=IngestUrlPreviewResponse)
def preview_ingest_url(request: IngestUrlRequest) -> IngestUrlPreviewResponse:
    return IngestionService().preview_url(str(request.url))


@app.post("/api/ingest/url", response_model=IngestUrlResponse)
def ingest_url(request: IngestUrlRequest) -> IngestUrlResponse:
    try:
        profile = IngestionService().ingest_url(str(request.url))
    except ProfileQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return IngestUrlResponse(tutor=profile, indexed=True)


@app.post("/api/browser/browse", response_model=BrowserBrowseResponse)
def browse(request: BrowserBrowseRequest) -> BrowserBrowseResponse:
    return BrowserAgent().browse(str(request.url), actions=request.actions) if request.use_playwright else BrowserBrowseResponse.model_validate(BrowserAgent().fetch(str(request.url)))


@app.post("/api/browser/research", response_model=BrowserResearchResponse)
def browser_research(request: BrowserResearchRequest) -> BrowserResearchResponse:
    if not settings.enable_browser_research:
        raise HTTPException(status_code=403, detail="Browser research is disabled by configuration")
    return BrowserResearchService().research(request)


@app.get("/api/browser/seed-sites", response_model=UniversitySeedSiteResponse)
def browser_seed_sites(q: str = "", limit: int = 20) -> UniversitySeedSiteResponse:
    return UniversitySeedSiteResponse(sites=UniversitySeedSiteService().list_sites(query=q, limit=limit))


@app.get("/api/tutors/search", response_model=SearchResponse)
def search_tutors(q: str, limit: int = 5) -> SearchResponse:
    return SearchResponse(tutors=TutorRetriever().search(q, limit=limit))


@app.get("/api/eval/rag", response_model=RAGEvaluationResponse)
def evaluate_rag(limit: int = 5, strategy: str = "reranker") -> RAGEvaluationResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    result = RAGEvaluator().evaluate(limit=limit, strategy=strategy)
    RAGEvaluationRepository().save("single", result)
    return result


@app.get("/api/eval/rag/compare", response_model=RAGEvaluationComparisonResponse)
def compare_rag(limit: int = 5) -> RAGEvaluationComparisonResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    result = RAGEvaluator().compare(limit=limit)
    RAGEvaluationRepository().save("compare", result)
    return result


@app.get("/api/eval/rag/report", response_model=RAGEvaluationReportResponse)
def report_rag(limit: int = 5) -> RAGEvaluationReportResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    result = RAGEvaluator().report(limit=limit)
    RAGEvaluationRepository().save("report", result)
    return result


@app.get("/api/eval/rag/configurations", response_model=RAGConfigurationComparisonResponse)
def compare_rag_configurations(limit: int = 5) -> RAGConfigurationComparisonResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    result = RAGEvaluator().compare_configurations(limit=limit)
    RAGEvaluationRepository().save("configurations", result)
    return result


@app.get("/api/eval/rag/dataset", response_model=RAGBenchmarkDatasetSummary)
def get_rag_benchmark_dataset() -> RAGBenchmarkDatasetSummary:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    return RAGEvaluator().dataset_summary()


@app.get("/api/eval/rag/runs", response_model=RAGEvaluationRunResponse)
def list_rag_evaluation_runs(limit: int = 20) -> RAGEvaluationRunResponse:
    return RAGEvaluationRunResponse(runs=RAGEvaluationRepository().list(limit=limit))


@app.get("/api/eval/rag/runs/{evaluation_id}", response_model=RAGEvaluationRun)
def get_rag_evaluation_run(evaluation_id: str) -> RAGEvaluationRun:
    run = RAGEvaluationRepository().get(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="RAG evaluation run not found")
    return run


@app.get("/api/traces/{trace_id}", response_model=AgentTraceRun)
def get_trace(trace_id: str) -> AgentTraceRun:
    trace = TraceRepository().get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@app.get("/api/traces/session/{session_id}", response_model=TraceRunResponse)
def list_session_traces(session_id: str, limit: int = 20) -> TraceRunResponse:
    return TraceRunResponse(runs=TraceRepository().list_by_session(session_id, limit=limit))


@app.get("/api/plans/{plan_id}", response_model=AgentPlanRun)
def get_plan(plan_id: str) -> AgentPlanRun:
    plan = PlanRepository().get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.get("/api/plans/session/{session_id}", response_model=PlanRunResponse)
def list_session_plans(session_id: str, limit: int = 20) -> PlanRunResponse:
    return PlanRunResponse(runs=PlanRepository().list_by_session(session_id, limit=limit))


@app.get("/api/memory/{session_id}")
def get_memory(session_id: str):
    return MemoryRepository().get(session_id)
