from __future__ import annotations

from app.graph.admission_graph import AdmissionGraph
from app.models.schemas import ChatResponse
from app.services.ingestion import ensure_seed_data
from app.storage.database import init_database


class ChatService:
    def __init__(self):
        init_database()
        ensure_seed_data()
        self.graph = AdmissionGraph()

    def chat(self, session_id: str, message: str) -> ChatResponse:
        state = self.graph.invoke(session_id=session_id, message=message)
        return ChatResponse(
            session_id=session_id,
            answer=state["answer"],
            plan=state["plan"],
            tutors=state.get("tutors", []),
            retrieval_evidence=state.get("retrieval_evidence", []),
            memory=state["memory"],
            trace=state.get("trace", []),
        )
