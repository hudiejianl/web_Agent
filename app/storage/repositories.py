from __future__ import annotations

import json
from datetime import datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.models.schemas import AgentTrace, AgentTraceRun, MemoryState, TutorProfile
from app.storage.database import get_connection


def tutor_id_for(profile: TutorProfile) -> str:
    # 用主页或机构姓名生成稳定 ID，避免重复采集同一导师时产生多条记录。
    key = profile.homepage or f"{profile.institution}:{profile.name}:{profile.department or ''}"
    return str(uuid5(NAMESPACE_URL, key))


class TutorRepository:
    def upsert(self, profile: TutorProfile) -> TutorProfile:
        profile.id = profile.id or tutor_id_for(profile)
        profile.updated_at = datetime.utcnow()
        payload = profile.model_dump_json(by_alias=True)
        document = profile.document_text()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO tutors (id, payload, document, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    document = excluded.document,
                    updated_at = excluded.updated_at
                """,
                (profile.id, payload, document, profile.updated_at.isoformat()),
            )
            connection.commit()
        return profile

    def list(self, limit: int = 50) -> list[TutorProfile]:
        with get_connection() as connection:
            rows = connection.execute("SELECT payload FROM tutors ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [TutorProfile.model_validate_json(row["payload"]) for row in rows]

    def get(self, tutor_id: str) -> TutorProfile | None:
        with get_connection() as connection:
            row = connection.execute("SELECT payload FROM tutors WHERE id = ?", (tutor_id,)).fetchone()
        return TutorProfile.model_validate_json(row["payload"]) if row else None


class TraceRepository:
    # Trace 按运行批次整体保存，便于通过 trace_id 复盘一次 Agent 执行。
    def save(self, session_id: str, source: str, trace: list[AgentTrace]) -> AgentTraceRun:
        run = AgentTraceRun(trace_id=str(uuid4()), session_id=session_id, source=source, trace=trace)
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO agent_traces (trace_id, session_id, source, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run.trace_id, run.session_id, run.source, run.model_dump_json(), run.created_at.isoformat()),
            )
            connection.commit()
        return run

    def get(self, trace_id: str) -> AgentTraceRun | None:
        with get_connection() as connection:
            row = connection.execute("SELECT payload FROM agent_traces WHERE trace_id = ?", (trace_id,)).fetchone()
        return AgentTraceRun.model_validate_json(row["payload"]) if row else None

    def list_by_session(self, session_id: str, limit: int = 20) -> list[AgentTraceRun]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM agent_traces WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [AgentTraceRun.model_validate_json(row["payload"]) for row in rows]


class MemoryRepository:
    def get(self, session_id: str) -> MemoryState:
        with get_connection() as connection:
            row = connection.execute("SELECT payload FROM memories WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return MemoryState(session_id=session_id)
        return MemoryState.model_validate_json(row["payload"])

    def save(self, memory: MemoryState) -> MemoryState:
        memory.updated_at = datetime.utcnow()
        payload = memory.model_dump_json()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO memories (session_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (memory.session_id, payload, memory.updated_at.isoformat()),
            )
            connection.commit()
        return memory

    def append_message(self, session_id: str, role: str, content: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.utcnow().isoformat()),
            )
            connection.commit()

    def recent_messages(self, session_id: str, limit: int = 12) -> list[dict[str, str]]:
        with get_connection() as connection:
            rows = connection.execute(
                "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]


def load_tutors_from_json(path: str) -> list[TutorProfile]:
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    return [TutorProfile.model_validate(item) for item in payload]
