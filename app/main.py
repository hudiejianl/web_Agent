from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.browser_agent import BrowserAgent
from app.config import get_settings
from app.logging_config import configure_logging
from app.models.schemas import BrowserBrowseRequest, BrowserBrowseResponse, BrowserResearchRequest, BrowserResearchResponse, ChatRequest, ChatResponse, IngestUrlRequest, IngestUrlResponse, RAGEvaluationComparisonResponse, RAGEvaluationReportResponse, RAGEvaluationResponse, SearchResponse, AgentTraceRun, TraceRunResponse
from app.eval.rag_eval import RAGEvaluator
from app.rag.retriever import TutorRetriever
from app.services.browser_research import BrowserResearchService
from app.services.chat import ChatService
from app.services.ingestion import IngestionService, ensure_seed_data
from app.storage.database import init_database
from app.storage.repositories import MemoryRepository, TraceRepository

configure_logging()
settings = get_settings()
logger = logging.getLogger("app.requests")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    ensure_seed_data()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    start = time.perf_counter()
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


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService()


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return get_chat_service().chat(request.session_id, request.message)


@app.post("/api/ingest/url", response_model=IngestUrlResponse)
def ingest_url(request: IngestUrlRequest) -> IngestUrlResponse:
    profile = IngestionService().ingest_url(str(request.url))
    return IngestUrlResponse(tutor=profile, indexed=True)


@app.post("/api/browser/browse", response_model=BrowserBrowseResponse)
def browse(request: BrowserBrowseRequest) -> BrowserBrowseResponse:
    return BrowserAgent().browse(str(request.url), actions=request.actions) if request.use_playwright else BrowserBrowseResponse.model_validate(BrowserAgent().fetch(str(request.url)))


@app.post("/api/browser/research", response_model=BrowserResearchResponse)
def browser_research(request: BrowserResearchRequest) -> BrowserResearchResponse:
    if not settings.enable_browser_research:
        raise HTTPException(status_code=403, detail="Browser research is disabled by configuration")
    return BrowserResearchService().research(request)


@app.get("/api/tutors/search", response_model=SearchResponse)
def search_tutors(q: str, limit: int = 5) -> SearchResponse:
    return SearchResponse(tutors=TutorRetriever().search(q, limit=limit))


@app.get("/api/eval/rag", response_model=RAGEvaluationResponse)
def evaluate_rag(limit: int = 5, strategy: str = "reranker") -> RAGEvaluationResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    return RAGEvaluator().evaluate(limit=limit, strategy=strategy)


@app.get("/api/eval/rag/compare", response_model=RAGEvaluationComparisonResponse)
def compare_rag(limit: int = 5) -> RAGEvaluationComparisonResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    return RAGEvaluator().compare(limit=limit)


@app.get("/api/eval/rag/report", response_model=RAGEvaluationReportResponse)
def report_rag(limit: int = 5) -> RAGEvaluationReportResponse:
    if not settings.enable_rag_eval:
        raise HTTPException(status_code=403, detail="RAG evaluation is disabled by configuration")
    return RAGEvaluator().report(limit=limit)


@app.get("/api/traces/{trace_id}", response_model=AgentTraceRun)
def get_trace(trace_id: str) -> AgentTraceRun:
    trace = TraceRepository().get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@app.get("/api/traces/session/{session_id}", response_model=TraceRunResponse)
def list_session_traces(session_id: str, limit: int = 20) -> TraceRunResponse:
    return TraceRunResponse(runs=TraceRepository().list_by_session(session_id, limit=limit))


@app.get("/api/memory/{session_id}")
def get_memory(session_id: str):
    return MemoryRepository().get(session_id)
