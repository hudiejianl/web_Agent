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


# 导师档案是检索、推荐、网页采集入库共用的核心数据结构。
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
        # 向量检索和 BM25 都基于这段聚合文本建立导师可检索文档。
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


class MemoryEvent(BaseModel):
    type: Literal["contacted", "favorited", "rejected", "feedback"]
    tutor_name: str = ""
    note: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SemanticMemory(BaseModel):
    research_focus: list[str] = Field(default_factory=list)
    application_strategy: list[str] = Field(default_factory=list)
    advisor_preferences: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class ProceduralMemory(BaseModel):
    workflow_preferences: list[str] = Field(default_factory=list)
    material_preferences: list[str] = Field(default_factory=list)
    communication_preferences: list[str] = Field(default_factory=list)
    scheduling_preferences: list[str] = Field(default_factory=list)


class RelevantMemory(BaseModel):
    type: str
    content: str
    score: float = 0.0


class MemoryReflection(BaseModel):
    topic: Literal["long_term_goal", "strategy", "workflow", "risk", "interaction"]
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryConflict(BaseModel):
    field: str
    previous: str
    current: str
    resolution: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# 长期记忆保存用户画像、事件记忆、语义记忆、流程记忆、近期对话和压缩摘要，用于多轮咨询上下文延续。
class MemoryState(BaseModel):
    session_id: str
    profile: UserProfile = Field(default_factory=UserProfile)
    summary: str = ""
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    episodic_events: list[MemoryEvent] = Field(default_factory=list)
    semantic: SemanticMemory = Field(default_factory=SemanticMemory)
    procedural: ProceduralMemory = Field(default_factory=ProceduralMemory)
    reflections: list[MemoryReflection] = Field(default_factory=list)
    conflicts: list[MemoryConflict] = Field(default_factory=list)
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
    is_replan: bool = False
    replan_from: str | None = None


class AgentPlanRun(BaseModel):
    plan_id: str
    session_id: str = "default"
    trace_id: str = ""
    plan: AgentPlan
    created_at: datetime = Field(default_factory=datetime.utcnow)


# AgentTrace 记录一次请求中每个智能体节点的执行轨迹，用于持久化调试和前端展示。
class AgentTrace(BaseModel):
    agent: str
    action: str
    status: Literal["started", "completed", "failed", "skipped"] = "completed"
    detail: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AgentHandoff(BaseModel):
    source_agent: str
    target_agent: str
    payload_type: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# AgentTraceRun 表示一次请求的完整轨迹，可通过 trace_id 从数据库回查。
class AgentTraceRun(BaseModel):
    trace_id: str
    session_id: str = "default"
    source: str
    trace: list[AgentTrace] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    session_id: str
    trace_id: str = ""
    answer: str
    plan: AgentPlan
    tutors: list[TutorProfile] = Field(default_factory=list)
    retrieval_evidence: list[RetrievalEvidence] = Field(default_factory=list)
    memory: MemoryState
    trace: list[AgentTrace] = Field(default_factory=list)
    agent_handoffs: list[AgentHandoff] = Field(default_factory=list)


class IngestUrlRequest(BaseModel):
    url: HttpUrl


class IngestUrlResponse(BaseModel):
    tutor: TutorProfile
    indexed: bool


class IngestUrlPreviewResponse(BaseModel):
    tutor: TutorProfile
    indexed: bool = False
    ingest_eligible: bool = False
    profile_quality_score: float = 0.0
    page_quality: float = 0.0
    quality_reasons: list[str] = Field(default_factory=list)


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
    page_quality: float = 0.0
    confidence: float = 0.0
    profile_quality_score: float = 0.0
    ingest_eligible: bool = False
    quality_reasons: list[str] = Field(default_factory=list)
    reason: str = ""
    link_type: str = "candidate"
    depth: int = 0
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
    dry_run: bool = False


class BrowserResearchQualityReport(BaseModel):
    total_candidates: int = 0
    eligible_candidates: int = 0
    rejected_candidates: int = 0
    ingested_or_previewed_tutors: int = 0
    average_profile_quality_score: float = 0.0
    average_page_quality: float = 0.0
    status_counts: dict[str, int] = Field(default_factory=dict)
    link_type_counts: dict[str, int] = Field(default_factory=dict)
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    top_candidates: list[CandidateLink] = Field(default_factory=list)


class BrowserResearchResponse(BaseModel):
    query: str
    trace_id: str = ""
    dry_run: bool = False
    rewritten_queries: list[str] = Field(default_factory=list)
    search_urls: list[str] = Field(default_factory=list)
    candidates: list[CandidateLink] = Field(default_factory=list)
    tutors: list[TutorProfile] = Field(default_factory=list)
    quality_report: BrowserResearchQualityReport = Field(default_factory=BrowserResearchQualityReport)
    trace: list[AgentTrace] = Field(default_factory=list)


class UniversitySeedSite(BaseModel):
    name: str
    institution: str
    location: str
    url: str
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0
    matched_terms: list[str] = Field(default_factory=list)
    reason: str = ""


class UniversitySeedSiteResponse(BaseModel):
    sites: list[UniversitySeedSite] = Field(default_factory=list)


class SearchResponse(BaseModel):
    tutors: list[TutorProfile]


class SystemCapability(BaseModel):
    name: str
    status: Literal["completed", "partial", "planned"] = "completed"
    features: list[str] = Field(default_factory=list)


class SystemCapabilitiesResponse(BaseModel):
    app_name: str
    capabilities: list[SystemCapability] = Field(default_factory=list)
    next_recommended_steps: list[str] = Field(default_factory=list)


class TraceRunResponse(BaseModel):
    runs: list[AgentTraceRun] = Field(default_factory=list)


class PlanRunResponse(BaseModel):
    runs: list[AgentPlanRun] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str
    request_id: str = ""


class RAGEvaluationCase(BaseModel):
    id: str
    query: str
    expected_tutor_names: list[str] = Field(default_factory=list)
    relevant_terms: list[str] = Field(default_factory=list)


class RAGBenchmarkDatasetSummary(BaseModel):
    case_count: int
    expected_tutor_count: int
    unique_expected_tutors: list[str] = Field(default_factory=list)
    covered_locations: list[str] = Field(default_factory=list)
    covered_research_terms: list[str] = Field(default_factory=list)
    cases: list[RAGEvaluationCase] = Field(default_factory=list)


class RAGEvaluationCaseResult(BaseModel):
    case_id: str
    query: str
    expected_tutor_names: list[str]
    retrieved_tutor_names: list[str]
    recall: float
    precision: float
    relevance: float
    faithfulness: float


class RAGConfigSnapshot(BaseModel):
    embedding_provider: str = "local"
    embedding_model: str = "hashing"
    retrieval_strategy: str = "reranker"
    chunk_size: int = 0
    chunk_overlap: int = 0
    reranker: str = "local"


class RAGEvaluationResponse(BaseModel):
    strategy: str = "reranker"
    case_count: int
    recall: float
    precision: float
    relevance: float
    faithfulness: float
    config: RAGConfigSnapshot | None = None
    cases: list[RAGEvaluationCaseResult] = Field(default_factory=list)


class RAGEvaluationComparisonResponse(BaseModel):
    strategies: list[RAGEvaluationResponse] = Field(default_factory=list)


class RAGConfigurationComparisonResponse(BaseModel):
    configurations: list[RAGEvaluationResponse] = Field(default_factory=list)


class RAGEvaluationReportResponse(BaseModel):
    markdown: str
    comparison: RAGEvaluationComparisonResponse


class RAGEvaluationRun(BaseModel):
    evaluation_id: str
    source: Literal["single", "compare", "report", "configurations"]
    payload: RAGEvaluationResponse | RAGEvaluationComparisonResponse | RAGEvaluationReportResponse | RAGConfigurationComparisonResponse
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RAGEvaluationRunResponse(BaseModel):
    runs: list[RAGEvaluationRun] = Field(default_factory=list)
