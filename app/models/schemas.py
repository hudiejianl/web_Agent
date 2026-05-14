from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class TaskType(str, Enum):
    chat = "chat"
    search_tutors = "search_tutors"
    ingest_url = "ingest_url"
    compare_tutors = "compare_tutors"


class Evidence(BaseModel):
    title: str
    url: str | None = None
    snippet: str


class RetrievalEvidence(BaseModel):
    tutor_id: str
    tutor_name: str
    field: str
    snippet: str
    matched_terms: list[str] = Field(default_factory=list)
    source_url: str | None = None
    score: float = 0.0


class Paper(BaseModel):
    title: str
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    doi: str | None = None
    abstract: str | None = None


class TutorProfile(BaseModel):
    id: str | None = None
    name: str
    title: str | None = None
    institution: str
    department: str | None = None
    location: str | None = None
    homepage: str | None = None
    email: str | None = None
    model_config = ConfigDict(populate_by_name=True)

    research_areas: list[str] = Field(default_factory=list)
    admission_directions: list[str] = Field(default_factory=list, alias="招生方向")
    requirements: list[str] = Field(default_factory=list)
    papers: list[Paper] = Field(default_factory=list)
    summary: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def document_text(self) -> str:
        papers = "；".join(p.title for p in self.papers[:8])
        evidence = "；".join(item.snippet for item in self.evidence[:5])
        return "\n".join(
            part
            for part in [
                f"导师：{self.name}",
                f"职称：{self.title or ''}",
                f"机构：{self.institution} {self.department or ''}",
                f"地区：{self.location or ''}",
                f"研究方向：{'、'.join(self.research_areas)}",
                f"招生方向：{'、'.join(self.admission_directions)}",
                f"申请要求：{'、'.join(self.requirements)}",
                f"代表论文：{papers}",
                f"简介：{self.summary}",
                f"证据：{evidence}",
            ]
            if part.strip("： ")
        )


class UserProfile(BaseModel):
    research_interests: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    target_degree: str | None = None
    background: str | None = None
    constraints: list[str] = Field(default_factory=list)


class MemoryState(BaseModel):
    session_id: str
    profile: UserProfile = Field(default_factory=UserProfile)
    summary: str = ""
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PlanStep(BaseModel):
    id: str
    name: str
    agent: str = "Planner"
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    depends_on: list[str] = Field(default_factory=list)
    rationale: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""
    error: str | None = None


class AgentPlan(BaseModel):
    task_type: TaskType = TaskType.chat
    objective: str = ""
    constraints: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    need_retrieval: bool = True
    need_ingestion: bool = False
    urls: list[str] = Field(default_factory=list)


class AgentTrace(BaseModel):
    agent: str
    action: str
    status: Literal["started", "completed", "failed", "skipped"] = "completed"
    detail: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    plan: AgentPlan
    tutors: list[TutorProfile] = Field(default_factory=list)
    retrieval_evidence: list[RetrievalEvidence] = Field(default_factory=list)
    memory: MemoryState
    trace: list[AgentTrace] = Field(default_factory=list)


class IngestUrlRequest(BaseModel):
    url: HttpUrl


class IngestUrlResponse(BaseModel):
    tutor: TutorProfile
    indexed: bool


class BrowserAction(BaseModel):
    type: Literal["click", "wait", "scroll"]
    selector: str | None = None
    value: str | int | float | None = None


class BrowserBrowseRequest(BaseModel):
    url: HttpUrl
    use_playwright: bool = True
    actions: list[BrowserAction] = Field(default_factory=list)


class BrowserBrowseResponse(BaseModel):
    url: str
    final_url: str
    title: str
    text: str
    links: list[dict[str, str]] = Field(default_factory=list)
    dom: dict[str, Any] = Field(default_factory=dict)
    screenshots: list[str] = Field(default_factory=list)
    used_playwright: bool = False
    actions: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class CandidateLink(BaseModel):
    text: str = ""
    url: str
    source_url: str | None = None
    score: float = 0.0
    reason: str = ""
    status: Literal["pending", "browsed", "ingested", "failed", "skipped"] = "pending"
    error: str | None = None


class BrowserResearchRequest(BaseModel):
    query: str
    search_engine: Literal["bing", "baidu"] = "bing"
    seed_urls: list[HttpUrl] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    max_queries: int = 5
    max_search_pages: int = 1
    max_candidates: int = 6
    max_ingest: int = 3
    navigation_depth: int = 1
    max_navigation_pages: int = 8
    use_playwright: bool = True


class BrowserResearchResponse(BaseModel):
    query: str
    rewritten_queries: list[str] = Field(default_factory=list)
    search_urls: list[str] = Field(default_factory=list)
    candidates: list[CandidateLink] = Field(default_factory=list)
    tutors: list[TutorProfile] = Field(default_factory=list)
    trace: list[AgentTrace] = Field(default_factory=list)


class SearchResponse(BaseModel):
    tutors: list[TutorProfile]
