"""
Conversation message storage abstraction.

SQLite is implemented for now, with a provider factory so future backends
like Redis/Postgres can be added without changing chat flow code.
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class MessageStore(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def append_message(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        dataset_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_messages(self, *, thread_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        raise NotImplementedError


class SQLiteMessageStore(MessageStore):
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  dataset_id TEXT,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  run_id TEXT,
                  metadata_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_id "
                "ON thread_messages(thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_id_id "
                "ON thread_messages(thread_id, id)"
            )
            conn.commit()
        finally:
            conn.close()

    def append_message(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        dataset_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO thread_messages (
                  thread_id, created_at, dataset_id, role, content, run_id, metadata_json
                ) VALUES (?, datetime('now'), ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    dataset_id,
                    role,
                    content,
                    run_id,
                    json.dumps(metadata) if metadata is not None else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_messages(self, *, thread_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, thread_id, created_at, dataset_id, role, content, run_id, metadata_json
                FROM (
                  SELECT *
                  FROM thread_messages
                  WHERE thread_id = ?
                  ORDER BY id DESC
                  LIMIT ?
                ) recent
                ORDER BY id ASC
                """,
                (thread_id, limit),
            ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                data = dict(row)
                if data.get("metadata_json"):
                    data["metadata"] = json.loads(data["metadata_json"])
                else:
                    data["metadata"] = None
                data.pop("metadata_json", None)
                out.append(data)
            return out
        finally:
            conn.close()


def create_message_store(provider: str, db_path: str) -> MessageStore:
    normalized = (provider or "sqlite").strip().lower()
    if normalized == "sqlite":
        return SQLiteMessageStore(db_path=db_path)
    raise ValueError(
        f"Unsupported message storage provider: {provider}. "
        "Supported providers: sqlite. Future providers can be added via MessageStore."
    )
