from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from .models import AgentRunContext, ChatMessage, RunEvent


class RuntimeStore(Protocol):
    def create_session(self) -> str: ...
    def list_sessions(self) -> list[dict]: ...
    def messages(self, session_id: str) -> list[dict]: ...
    def save_message(
        self, session_id: str, run_id: str, role: str, content: str, output: dict | None = None
    ) -> None: ...
    def save(self, state: AgentRunContext) -> None: ...
    def load(self, run_id: str) -> AgentRunContext: ...
    def append(self, event: RunEvent, state: AgentRunContext) -> None: ...
    def events(self, run_id: str, after: int = 0) -> list[dict]: ...
    def active_run(self, session_id: str) -> str | None: ...
    def runs(self, session_id: str) -> list[dict]: ...


class MemoryRuntimeStore:
    """Default embeddable store; no disk access unless a host supplies a store."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict]] = {}
        self._runs: dict[str, dict] = {}
        self._events: dict[str, list[dict]] = {}

    def create_session(self) -> str:
        session_id = str(uuid4())
        self._sessions[session_id] = []
        return session_id

    def list_sessions(self) -> list[dict]:
        return [{"id": sid} for sid in self._sessions]

    def messages(self, session_id: str) -> list[dict]:
        if session_id not in self._sessions:
            raise KeyError("会话不存在")
        return self._sessions[session_id]

    def save_message(self, session_id, run_id, role, content, output=None) -> None:
        messages = self.messages(session_id)
        entry = {"run_id": run_id, "role": role, "content": content, "output": output}
        for index, item in enumerate(messages):
            if item["run_id"] == run_id and item["role"] == role:
                messages[index] = entry
                return
        messages.append(entry)

    def save(self, state: AgentRunContext) -> None:
        self._runs[state.run_id] = state.model_dump(mode="json")

    def load(self, run_id: str) -> AgentRunContext:
        if run_id not in self._runs:
            raise KeyError("运行不存在")
        return AgentRunContext.model_validate(self._runs[run_id])

    def append(self, event: RunEvent, state: AgentRunContext) -> None:
        self._events.setdefault(event.run_id, []).append(event.model_dump(mode="json"))
        self.save(state)

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        self.load(run_id)
        return [item for item in self._events.get(run_id, []) if item["sequence"] > after]

    def active_run(self, session_id: str) -> str | None:
        return next(
            (
                rid
                for rid, state in self._runs.items()
                if state["session_id"] == session_id
                and state["status"] in {"running", "awaiting_approval"}
            ),
            None,
        )

    def runs(self, session_id: str) -> list[dict]:
        self.messages(session_id)
        return [
            {"id": rid, "status": state["status"]}
            for rid, state in self._runs.items()
            if state["session_id"] == session_id
        ]


class SQLiteRuntimeStore:
    """Single-host durable sessions, checkpoints and replayable run events."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS messages (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, run_id TEXT, role TEXT, content TEXT, output TEXT,
                UNIQUE(run_id, role));
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, session_id TEXT, status TEXT, snapshot TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT, sequence INTEGER, payload TEXT, PRIMARY KEY(run_id, sequence));
        """)
        self._db.commit()
        os.chmod(path, 0o600)

    def create_session(self) -> str:
        sid = str(uuid4())
        with self._lock, self._db:
            self._db.execute("INSERT INTO sessions(id) VALUES (?)", (sid,))
        return sid

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [
                dict(row)
                for row in self._db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
            ]

    def messages(self, session_id: str) -> list[dict]:
        with self._lock:
            if not self._db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
                raise KeyError("会话不存在")
            rows = self._db.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY sequence", (session_id,)
            )
            return [
                {**dict(row), "output": json.loads(row["output"]) if row["output"] else None}
                for row in rows
            ]

    def save_message(self, session_id, run_id, role, content, output=None) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO messages(session_id,run_id,role,content,output)
                VALUES (?,?,?,?,?) ON CONFLICT(run_id,role) DO UPDATE
                SET content=excluded.content,output=excluded.output""",
                (
                    session_id,
                    run_id,
                    role,
                    content,
                    json.dumps(output, ensure_ascii=False) if output else None,
                ),
            )

    def save(self, state: AgentRunContext) -> None:
        with self._lock, self._db:
            self._save(state)

    def _save(self, state: AgentRunContext) -> None:
        self._db.execute(
            """INSERT INTO runs(id,session_id,status,snapshot) VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status,snapshot=excluded.snapshot""",
            (state.run_id, state.session_id, state.status, state.model_dump_json()),
        )

    def load(self, run_id: str) -> AgentRunContext:
        with self._lock:
            row = self._db.execute("SELECT snapshot FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError("运行不存在")
        return AgentRunContext.model_validate_json(row["snapshot"])

    def append(self, event: RunEvent, state: AgentRunContext) -> None:
        with self._lock, self._db:
            self._save(state)
            self._db.execute(
                "INSERT INTO events VALUES (?,?,?)",
                (event.run_id, event.sequence, event.model_dump_json()),
            )

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        self.load(run_id)
        with self._lock:
            return [
                json.loads(row["payload"])
                for row in self._db.execute(
                    "SELECT payload FROM events WHERE run_id=? AND sequence>? ORDER BY sequence",
                    (run_id, after),
                )
            ]

    def active_run(self, session_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                """SELECT id FROM runs WHERE session_id=?
                AND status IN ('running','awaiting_approval') LIMIT 1""",
                (session_id,),
            ).fetchone()
        return row["id"] if row else None

    def runs(self, session_id: str) -> list[dict]:
        self.messages(session_id)
        with self._lock:
            return [
                dict(row)
                for row in self._db.execute(
                    "SELECT id,status,created_at FROM runs WHERE session_id=? ORDER BY rowid",
                    (session_id,),
                )
            ]

    def recover_interrupted(self) -> None:
        with self._lock:
            ids = [
                row["id"] for row in self._db.execute("SELECT id FROM runs WHERE status='running'")
            ]
        for rid in ids:
            state = self.load(rid)
            state.status = "failed"
            state.sequence += 1
            self.append(
                RunEvent(
                    run_id=rid,
                    sequence=state.sequence,
                    type="run.error",
                    data={
                        "message": "服务在执行期间重启；该运行已停止，未自动重放可能已执行的操作。",
                        "code": "RUN_INTERRUPTED",
                    },
                ),
                state,
            )


def bounded_history(messages: list[ChatMessage], max_messages=20, max_chars=24_000):
    selected = []
    remaining = max_chars
    for message in reversed(messages[-max_messages:]):
        if len(message.content) > remaining:
            break
        selected.append(message)
        remaining -= len(message.content)
    return list(reversed(selected))
