"""Shared sandbox execution helper.

Centralises the payload construction and executor dispatch that was
previously duplicated across tools.py, main.py:_execute_direct, and
main.py:submit_run.
"""

from __future__ import annotations

from typing import Any, Dict

from .executors.base import Executor


def execute_in_sandbox(
    executor: Executor,
    dataset: Dict[str, Any],
    *,
    query_type: str,
    sql: str = "",
    python_code: str = "",
    timeout_seconds: int,
    max_rows: int,
    max_output_bytes: int,
) -> Dict[str, Any]:
    """Build a runner payload from *dataset* and dispatch via *executor*.

    Returns the raw dict from executor.submit_run so callers can extract
    ``result``, ``run_id``, etc. as needed.
    """
    files = [
        {"name": entry["name"], "path": f"/data/{entry['path']}"}
        for entry in dataset.get("files", [])
    ]
    payload: Dict[str, Any] = {
        "dataset_id": dataset["id"],
        "files": files,
        "query_type": query_type,
        "timeout_seconds": timeout_seconds,
        "max_rows": max_rows,
        "max_output_bytes": max_output_bytes,
    }
    if query_type == "python":
        payload["python_code"] = python_code
    else:
        payload["sql"] = sql
    return executor.submit_run(payload, query_type=query_type)
