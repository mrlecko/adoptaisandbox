"""
LangChain tool definitions for the CSV Analyst agent.

All tools are created via create_tools(), which closes over the executor and
config so the tools themselves are plain functions compatible with LangChain's
@tool decorator.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.tools import tool

from .datasets import get_dataset_by_id, load_registry
from .executors.base import Executor
from .validators.compiler import QueryPlanCompiler
from .validators.sql_policy import normalize_sql_for_dataset, validate_sql_policy

from .execution import execute_in_sandbox

# Names that produce execution results — capsule extraction filters on these
EXECUTION_TOOL_NAMES = {"execute_sql", "execute_query_plan", "execute_python"}


def create_tools(
    *,
    executor: Executor,
    compiler: QueryPlanCompiler,
    datasets_dir: str,
    max_rows: int,
    max_output_bytes: int,
    timeout_seconds: int,
    enable_python_execution: bool,
) -> List[Any]:
    """Return the 5 agent tools, each closed over the shared services."""

    # ── helpers shared by tools ──────────────────────────────────────────

    def _load_reg() -> Dict[str, Any]:
        return load_registry(datasets_dir)

    def _run_sandbox(
        dataset: Dict[str, Any],
        sql: str,
        query_type: str = "sql",
        python_code: str = "",
    ) -> Dict[str, Any]:
        return execute_in_sandbox(
            executor,
            dataset,
            query_type=query_type,
            sql=sql,
            python_code=python_code,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
            max_output_bytes=max_output_bytes,
        )

    # ── tool: list_datasets ──────────────────────────────────────────────

    @tool
    def list_datasets() -> str:
        """List all available CSV datasets with their descriptions and prompts."""
        registry = _load_reg()
        summary = {
            "datasets": [
                {
                    "id": ds["id"],
                    "name": ds["name"],
                    "description": ds.get("description"),
                    "prompts": ds.get("prompts", []),
                    "version_hash": ds.get("version_hash"),
                }
                for ds in registry.get("datasets", [])
            ]
        }
        return json.dumps(summary)

    # ── tool: get_dataset_schema ─────────────────────────────────────────

    @tool
    def get_dataset_schema(dataset_id: str) -> str:
        """Get the schema and 3 sample rows for a dataset.

        Args:
            dataset_id: The identifier of the dataset (e.g. 'ecommerce', 'support', 'sensors').
        """
        import csv
        from pathlib import Path

        registry = _load_reg()
        ds = get_dataset_by_id(registry, dataset_id)
        files = []
        for f in ds.get("files", []):
            abs_path = Path(datasets_dir) / f["path"]
            sample: list[dict[str, Any]] = []
            if abs_path.exists():
                with abs_path.open(newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    for i, row in enumerate(reader):
                        if i >= 3:
                            break
                        sample.append(row)
            files.append(
                {
                    "name": f["name"],
                    "path": f["path"],
                    "schema": f.get("schema", {}),
                    "sample_rows": sample,
                }
            )
        return json.dumps({"id": ds["id"], "name": ds["name"], "files": files})

    # ── tool: execute_sql ────────────────────────────────────────────────

    @tool
    def execute_sql(dataset_id: str, sql: str) -> str:
        """Execute a SQL query against a dataset in a sandboxed runner.

        Args:
            dataset_id: The identifier of the dataset to query.
            sql: A SELECT or WITH SQL query (no DDL / DML).
        """
        registry = _load_reg()
        dataset = get_dataset_by_id(registry, dataset_id)

        sql = normalize_sql_for_dataset(sql, dataset_id)
        policy_error = validate_sql_policy(sql)
        if policy_error:
            return json.dumps(
                {
                    "status": "error",
                    "error": {"type": "SQL_POLICY_VIOLATION", "message": policy_error},
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "compiled_sql": sql,
                }
            )

        raw = _run_sandbox(dataset, sql, query_type="sql")
        result = raw.get("result", raw)
        result["compiled_sql"] = sql
        return json.dumps(result)

    # ── tool: execute_query_plan ─────────────────────────────────────────

    @tool
    def execute_query_plan(dataset_id: str, plan: str) -> str:
        """Compile a QueryPlan JSON object to SQL and execute it.

        Args:
            dataset_id: The identifier of the dataset to query.
            plan: JSON string of the QueryPlan object.
        """
        from .models.query_plan import QueryPlan

        plan_dict = json.loads(plan) if isinstance(plan, str) else plan
        # dataset_id from function arg wins over anything in plan body
        merged = {**plan_dict, "dataset_id": dataset_id}
        query_plan = QueryPlan.model_validate(merged)
        compiled_sql = compiler.compile(query_plan)

        # Reuse execute_sql logic (but call sandbox directly to include plan_json)
        registry = _load_reg()
        dataset = get_dataset_by_id(registry, dataset_id)

        normalized_sql = normalize_sql_for_dataset(compiled_sql, dataset_id)
        policy_error = validate_sql_policy(normalized_sql)
        if policy_error:
            return json.dumps(
                {
                    "status": "error",
                    "error": {"type": "SQL_POLICY_VIOLATION", "message": policy_error},
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "compiled_sql": normalized_sql,
                    "plan_json": query_plan.model_dump(),
                }
            )

        raw = _run_sandbox(dataset, normalized_sql, query_type="sql")
        result = raw.get("result", raw)
        result["compiled_sql"] = normalized_sql
        result["plan_json"] = query_plan.model_dump()
        return json.dumps(result)

    # ── tool: execute_python ─────────────────────────────────────────────

    @tool
    def execute_python(dataset_id: str, python_code: str) -> str:
        """Execute Python/pandas code against a dataset in a sandboxed runner.

        Args:
            dataset_id: The identifier of the dataset.
            python_code: Python code string. Must set result_df or result.
        """
        if not enable_python_execution:
            return json.dumps(
                {
                    "status": "error",
                    "error": {
                        "type": "FEATURE_DISABLED",
                        "message": "Python execution mode is disabled.",
                    },
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                }
            )

        registry = _load_reg()
        dataset = get_dataset_by_id(registry, dataset_id)
        raw = _run_sandbox(dataset, "", query_type="python", python_code=python_code)
        result = raw.get("result", raw)
        return json.dumps(result)

    return [
        list_datasets,
        get_dataset_schema,
        execute_sql,
        execute_query_plan,
        execute_python,
    ]
