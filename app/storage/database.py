from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import get_settings


# SQLite 作为本地演示存储，保存导师档案、长期记忆、会话消息和 Agent Trace。
SCHEMA = """
CREATE TABLE IF NOT EXISTS tutors (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    document TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    session_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_traces (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_traces_session_created
ON agent_traces (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_plans (
    plan_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_plans_session_created
ON agent_plans (session_id, created_at DESC);
"""


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_database() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA)
        connection.commit()
