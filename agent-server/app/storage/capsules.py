"""
SQLite persistence helpers for run capsules.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


def init_capsule_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_capsules (
              run_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              dataset_id TEXT NOT NULL,
              dataset_version_hash TEXT,
              question TEXT,
              query_mode TEXT NOT NULL,
              plan_json TEXT,
              compiled_sql TEXT,
              python_code TEXT,
              status TEXT NOT NULL,
              result_json TEXT,
              error_json TEXT,
              exec_time_ms INTEGER
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_capsules_created_at ON run_capsules(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_capsules_dataset_id ON run_capsules(dataset_id)"
        )
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(run_capsules)").fetchall()
        }
        if "python_code" not in columns:
            conn.execute("ALTER TABLE run_capsules ADD COLUMN python_code TEXT")
        conn.commit()
    finally:
        conn.close()


def insert_capsule(db_path: str, capsule: Dict[str, Any]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO run_capsules (
              run_id, created_at, dataset_id, dataset_version_hash, question,
              query_mode, plan_json, compiled_sql, python_code, status, result_json,
              error_json, exec_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capsule["run_id"],
                capsule["created_at"],
                capsule["dataset_id"],
                capsule.get("dataset_version_hash"),
                capsule.get("question"),
                capsule["query_mode"],
                json.dumps(capsule.get("plan_json")) if capsule.get("plan_json") is not None else None,
                capsule.get("compiled_sql"),
                capsule.get("python_code"),
                capsule["status"],
                json.dumps(capsule.get("result_json")) if capsule.get("result_json") is not None else None,
                json.dumps(capsule.get("error_json")) if capsule.get("error_json") is not None else None,
                capsule.get("exec_time_ms"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_capsule(db_path: str, run_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM run_capsules WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("plan_json", "result_json", "error_json"):
            if data.get(key):
                data[key] = json.loads(data[key])
        return data
    finally:
        conn.close()
