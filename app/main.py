from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agents.browser_agent import BrowserAgent
from app.config import get_settings
from app.models.schemas import BrowserBrowseRequest, BrowserBrowseResponse, BrowserResearchRequest, BrowserResearchResponse, ChatRequest, ChatResponse, IngestUrlRequest, IngestUrlResponse, SearchResponse
from app.rag.retriever import TutorRetriever
from app.services.browser_research import BrowserResearchService
from app.services.chat import ChatService
from app.services.ingestion import IngestionService, ensure_seed_data
from app.storage.database import init_database
from app.storage.repositories import MemoryRepository

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    ensure_seed_data()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


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
    return BrowserResearchService().research(request)


@app.get("/api/tutors/search", response_model=SearchResponse)
def search_tutors(q: str, limit: int = 5) -> SearchResponse:
    return SearchResponse(tutors=TutorRetriever().search(q, limit=limit))


@app.get("/api/memory/{session_id}")
def get_memory(session_id: str):
    return MemoryRepository().get(session_id)
