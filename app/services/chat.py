from __future__ import annotations

from app.graph.admission_graph import AdmissionGraph
from app.models.schemas import ChatResponse
from app.services.ingestion import ensure_seed_data
from app.storage.database import init_database
from app.storage.repositories import PlanRepository, TraceRepository


# ChatService 是对话 API 的应用层入口，负责调用 LangGraph 并封装响应。
class ChatService:
    def __init__(self):
        init_database()
        ensure_seed_data()
        self.graph = AdmissionGraph()
        self.traces = TraceRepository()
        self.plans = PlanRepository()

    def chat(self, session_id: str, message: str) -> ChatResponse:
        state = self.graph.invoke(session_id=session_id, message=message)
        trace = state.get("trace", [])
        trace_run = self.traces.save(session_id=session_id, source="chat", trace=trace)
        self.plans.save(session_id=session_id, trace_id=trace_run.trace_id, plan=state["plan"])
        return ChatResponse(
            session_id=session_id,
            trace_id=trace_run.trace_id,
            answer=state["answer"],
            plan=state["plan"],
            tutors=state.get("tutors", []),
            retrieval_evidence=state.get("retrieval_evidence", []),
            memory=state["memory"],
            trace=trace,
        )
