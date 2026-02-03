"""
Single-file FastAPI agent server for CSV Analyst Chat.

This module intentionally keeps the first implementation compact:
- One FastAPI app
- Classic LangChain-compatible query generation path (optional, API-key gated)
- Tool-like deterministic execution helpers
- Runner sandbox invocation
- SQLite run capsules
- Static UI + streaming endpoint
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from .models.query_plan import QueryPlan, SelectColumn
from .validators.compiler import QueryPlanCompiler

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency guard
    load_dotenv = None


LOGGER = logging.getLogger("csv-analyst-agent-server")


class Settings(BaseModel):
    """Runtime configuration for the single-file server."""

    datasets_dir: str = Field(default="datasets")
    capsule_db_path: str = Field(default="agent-server/capsules.db")
    anthropic_api_key: Optional[str] = Field(default=None)
    openai_api_key: Optional[str] = Field(default=None)
    llm_provider: Literal["auto", "anthropic", "openai"] = Field(default="auto")
    anthropic_model: str = Field(default="claude-3-5-sonnet-20240620")
    openai_model: str = Field(default="gpt-4o-mini")
    runner_image: str = Field(default="csv-analyst-runner:test")
    run_timeout_seconds: int = Field(default=10)
    max_rows: int = Field(default=200)
    max_output_bytes: int = Field(default=65536)
    enable_python_execution: bool = Field(default=True)
    log_level: str = Field(default="info")


class ChatRequest(BaseModel):
    """Chat request body."""

    dataset_id: str
    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response body."""

    assistant_message: str
    run_id: str
    status: Literal["succeeded", "failed", "rejected"]
    result: Dict[str, Any]
    details: Dict[str, Any]


class StreamRequest(ChatRequest):
    """Streaming request body (same as chat request)."""


class AgentDraft(BaseModel):
    """Structured output target for optional LLM query generation."""

    query_mode: Literal["plan", "sql"] = "plan"
    assistant_message: str = "Done."
    plan: Optional[QueryPlan] = None
    sql: Optional[str] = None

    @model_validator(mode="after")
    def _validate_executable_payload(self) -> "AgentDraft":
        if self.query_mode == "plan" and self.plan is None:
            raise ValueError("plan is required when query_mode='plan'")
        if self.query_mode == "sql" and not (self.sql and self.sql.strip()):
            raise ValueError("sql is required when query_mode='sql'")
        return self


class SqlRescueDraft(BaseModel):
    """Backup structured output when plan generation is non-executable."""

    sql: str
    assistant_message: str = "Executed query."

    @model_validator(mode="after")
    def _validate_sql(self) -> "SqlRescueDraft":
        if not self.sql.strip():
            raise ValueError("sql is required")
        return self


SQL_BLOCKLIST = [
    "drop",
    "delete",
    "insert",
    "update",
    "create",
    "alter",
    "attach",
    "install",
    "load",
    "pragma",
    "call",
    "copy",
    "export",
]


def _contains_blocked_sql_token(sql_lower: str, token: str) -> bool:
    pattern = rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])"
    return re.search(pattern, sql_lower) is not None


def _normalize_sql_for_dataset(sql: str, dataset_id: str) -> str:
    """Allow optional dataset-qualified table refs like support.tickets."""
    normalized = re.sub(
        rf'(?i)"{re.escape(dataset_id)}"\s*\.\s*',
        "",
        sql,
    )
    normalized = re.sub(
        rf"(?i)\b{re.escape(dataset_id)}\s*\.\s*",
        "",
        normalized,
    )
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry(settings: Settings) -> Dict[str, Any]:
    registry_path = Path(settings.datasets_dir) / "registry.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"Dataset registry not found: {registry_path}")
    return json.loads(registry_path.read_text())


def _dataset_by_id(registry: Dict[str, Any], dataset_id: str) -> Dict[str, Any]:
    for ds in registry.get("datasets", []):
        if ds["id"] == dataset_id:
            return ds
    raise KeyError(f"Unknown dataset_id: {dataset_id}")


def _sample_rows(csv_path: Path, max_rows: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not csv_path.exists():
        return rows
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(row)
    return rows


def _validate_sql_policy(sql: str) -> Optional[str]:
    sql_clean = sql.strip()
    lowered = sql_clean.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return "Only SELECT/WITH queries are allowed."

    # Reject multiple statements.
    if ";" in sql_clean.rstrip(";"):
        return "Multiple SQL statements are not allowed."

    for token in SQL_BLOCKLIST:
        if _contains_blocked_sql_token(lowered, token):
            return f"SQL contains blocked token: {token}"

    return None


def _init_capsule_db(db_path: str) -> None:
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
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(run_capsules)").fetchall()
        }
        if "python_code" not in columns:
            conn.execute("ALTER TABLE run_capsules ADD COLUMN python_code TEXT")
        conn.commit()
    finally:
        conn.close()


def _insert_capsule(db_path: str, capsule: Dict[str, Any]) -> None:
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


def _get_capsule(db_path: str, run_id: str) -> Optional[Dict[str, Any]]:
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


def _default_runner_executor(
    settings: Settings,
    dataset: Dict[str, Any],
    sql: str,
    timeout_seconds: int,
    max_rows: int,
    query_type: str = "sql",
    python_code: Optional[str] = None,
    max_output_bytes: int = 65536,
) -> Dict[str, Any]:
    files = []
    for entry in dataset.get("files", []):
        files.append(
            {
                "name": entry["name"],
                "path": f"/data/{entry['path']}",
            }
        )

    payload = {
        "dataset_id": dataset["id"],
        "files": files,
        "query_type": query_type,
        "timeout_seconds": timeout_seconds,
        "max_rows": max_rows,
        "max_output_bytes": max_output_bytes,
    }
    if query_type == "python":
        payload["python_code"] = python_code or ""
    else:
        payload["sql"] = sql

    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--cpus",
        "0.5",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-v",
        f"{Path(settings.datasets_dir).resolve()}:/data:ro",
    ]
    if query_type == "python":
        cmd.extend(["--entrypoint", "python3"])
    cmd.append(settings.runner_image)
    if query_type == "python":
        cmd.append("/app/runner_python.py")

    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds + 5,
    )

    if not proc.stdout.strip():
        return {
            "status": "error",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 0,
            "stdout_trunc": "",
            "stderr_trunc": proc.stderr.strip()[:4096],
            "error": {
                "type": "RUNNER_INTERNAL_ERROR",
                "message": "Runner returned empty stdout.",
            },
        }

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 0,
            "stdout_trunc": proc.stdout[:4096],
            "stderr_trunc": proc.stderr[:4096],
            "error": {
                "type": "RUNNER_INTERNAL_ERROR",
                "message": "Runner returned invalid JSON.",
            },
        }


def _fallback_plan(dataset_id: str, dataset: Dict[str, Any], max_rows: int) -> QueryPlan:
    first_file = dataset["files"][0]
    table = Path(first_file["name"]).stem
    return QueryPlan(
        dataset_id=dataset_id,
        table=table,
        select=[SelectColumn(column=list(first_file["schema"].keys())[0])],
        limit=max_rows,
    )


def _generate_with_langchain(
    settings: Settings,
    dataset: Dict[str, Any],
    message: str,
    max_rows: int,
) -> Optional[Any]:
    try:
        from langchain_core.prompts import ChatPromptTemplate
    except Exception:
        return None

    schema_summary = {
        "dataset_id": dataset["id"],
        "description": dataset.get("description"),
        "files": [
            {
                "name": f["name"],
                "schema": list(f.get("schema", {}).keys()),
            }
            for f in dataset.get("files", [])
        ],
    }

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a careful data analyst. Default to query_mode='plan' with a valid QueryPlan. "
                    "Only use query_mode='sql' when the user explicitly asks for SQL. "
                    "Always keep LIMIT <= {max_rows}."
                ),
            ),
            ("human", "Dataset schema: {schema}\n\nUser message: {message}"),
        ]
    )

    model = None
    provider = settings.llm_provider

    if provider in ("auto", "openai") and settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
        except Exception:
            if provider == "openai":
                return None
        else:
            model = ChatOpenAI(
                model=settings.openai_model,
                temperature=0,
                api_key=settings.openai_api_key,
            ).with_structured_output(AgentDraft)

    if model is None and provider in ("auto", "anthropic") and settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
        except Exception:
            if provider == "anthropic":
                return None
        else:
            model = ChatAnthropic(
                model=settings.anthropic_model,
                temperature=0,
                api_key=settings.anthropic_api_key,
            ).with_structured_output(AgentDraft)

    if model is None:
        return None

    chain = prompt | model
    return chain.invoke(
        {
            "schema": json.dumps(schema_summary),
            "message": message,
            "max_rows": max_rows,
        }
    )


def _coerce_agent_draft(raw: Any) -> Optional[AgentDraft]:
    """Normalize provider output into AgentDraft across LangChain version differences."""
    if raw is None:
        return None

    if isinstance(raw, AgentDraft):
        return raw

    candidate: Any = raw
    if isinstance(raw, dict):
        if isinstance(raw.get("parsed"), AgentDraft):
            return raw["parsed"]
        if isinstance(raw.get("parsed"), dict):
            candidate = raw["parsed"]
        elif isinstance(raw.get("output"), dict):
            candidate = raw["output"]

    if isinstance(candidate, dict):
        try:
            return AgentDraft.model_validate(candidate)
        except ValidationError:
            return None

    if hasattr(candidate, "model_dump"):
        try:
            return AgentDraft.model_validate(candidate.model_dump())
        except ValidationError:
            return None

    return None


def _coerce_sql_rescue_draft(raw: Any) -> Optional[SqlRescueDraft]:
    if raw is None:
        return None
    if isinstance(raw, SqlRescueDraft):
        return raw

    candidate: Any = raw
    if isinstance(raw, dict):
        if isinstance(raw.get("parsed"), SqlRescueDraft):
            return raw["parsed"]
        if isinstance(raw.get("parsed"), dict):
            candidate = raw["parsed"]
        elif isinstance(raw.get("output"), dict):
            candidate = raw["output"]

    if isinstance(candidate, dict):
        try:
            return SqlRescueDraft.model_validate(candidate)
        except ValidationError:
            return None

    if hasattr(candidate, "content") and isinstance(candidate.content, str):
        text = candidate.content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
            return SqlRescueDraft.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None

    if hasattr(candidate, "model_dump"):
        try:
            return SqlRescueDraft.model_validate(candidate.model_dump())
        except ValidationError:
            return None

    return None


def _generate_sql_rescue_with_langchain(
    settings: Settings,
    dataset: Dict[str, Any],
    message: str,
    max_rows: int,
) -> Optional[SqlRescueDraft]:
    """Fallback LLM path: ask for SQL-only structured payload."""
    try:
        from langchain_core.prompts import ChatPromptTemplate
    except Exception:
        return None

    schema_summary = {
        "dataset_id": dataset["id"],
        "description": dataset.get("description"),
        "files": [
            {
                "name": f["name"],
                "schema": list(f.get("schema", {}).keys()),
            }
            for f in dataset.get("files", [])
        ],
    }

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "Return only executable SQL for DuckDB in a structured response. "
                    "Use only tables from schema; enforce LIMIT <= {max_rows}. "
                    "Return one SELECT/WITH query."
                ),
            ),
            ("human", "Dataset schema: {schema}\n\nUser message: {message}"),
        ]
    )

    model = None
    provider = settings.llm_provider

    if provider in ("auto", "openai") and settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
        except Exception:
            if provider == "openai":
                return None
        else:
            model = ChatOpenAI(
                model=settings.openai_model,
                temperature=0,
                api_key=settings.openai_api_key,
            ).with_structured_output(SqlRescueDraft)

    if model is None and provider in ("auto", "anthropic") and settings.anthropic_api_key:
        try:
            from langchain_anthropic import ChatAnthropic
        except Exception:
            if provider == "anthropic":
                return None
        else:
            model = ChatAnthropic(
                model=settings.anthropic_model,
                temperature=0,
                api_key=settings.anthropic_api_key,
            ).with_structured_output(SqlRescueDraft)

    if model is None:
        return None

    chain = prompt | model
    raw = chain.invoke(
        {
            "schema": json.dumps(schema_summary),
            "message": message,
            "max_rows": max_rows,
        }
    )
    return _coerce_sql_rescue_draft(raw)


@dataclass
class AppServices:
    settings: Settings
    runner_executor: Callable[..., Dict[str, Any]]
    compiler: QueryPlanCompiler


def _normalize_runner_to_status(result: Dict[str, Any]) -> Literal["succeeded", "failed"]:
    return "succeeded" if result.get("status") == "success" else "failed"


def create_app(
    settings: Optional[Settings] = None,
    runner_executor: Optional[Callable[..., Dict[str, Any]]] = None,
) -> FastAPI:
    if load_dotenv:
        repo_root = Path(__file__).resolve().parents[2]
        load_dotenv(repo_root / ".env", override=False)
        load_dotenv(Path.cwd() / ".env", override=False)

    settings = settings or Settings(
        datasets_dir=os.getenv("DATASETS_DIR", "datasets"),
        capsule_db_path=os.getenv("CAPSULE_DB_PATH", "agent-server/capsules.db"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        llm_provider=os.getenv("LLM_PROVIDER", "auto"),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        runner_image=os.getenv("RUNNER_IMAGE", "csv-analyst-runner:test"),
        run_timeout_seconds=int(os.getenv("RUN_TIMEOUT_SECONDS", "10")),
        max_rows=int(os.getenv("MAX_ROWS", "200")),
        max_output_bytes=int(os.getenv("MAX_OUTPUT_BYTES", "65536")),
        enable_python_execution=os.getenv("ENABLE_PYTHON_EXECUTION", "true").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info"),
    )

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    _init_capsule_db(settings.capsule_db_path)

    app = FastAPI(title="CSV Analyst Agent Server")
    app.state.services = AppServices(
        settings=settings,
        runner_executor=runner_executor or _default_runner_executor,
        compiler=QueryPlanCompiler(),
    )

    def process_chat(
        request: ChatRequest,
        status_cb: Optional[Callable[[str], None]] = None,
    ) -> ChatResponse:
        services: AppServices = app.state.services
        registry = _load_registry(services.settings)
        dataset = _dataset_by_id(registry, request.dataset_id)
        run_id = str(uuid.uuid4())
        status_cb = status_cb or (lambda *_: None)

        status_cb("planning")
        explicit_sql = request.message.strip().lower().startswith("sql:")
        explicit_python = request.message.strip().lower().startswith("python:")

        query_mode: Literal["sql", "plan", "python"] = "sql" if explicit_sql else "plan"
        assistant_message = "Executed query."
        plan_json = None
        compiled_sql = None
        python_code = None

        if explicit_python:
            if not services.settings.enable_python_execution:
                result = {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {
                        "type": "FEATURE_DISABLED",
                        "message": "Python execution mode is disabled.",
                    },
                }
                response = ChatResponse(
                    assistant_message="Query rejected: Python execution is disabled.",
                    run_id=run_id,
                    status="rejected",
                    result=result,
                    details={
                        "dataset_id": request.dataset_id,
                        "query_mode": "python",
                        "plan_json": None,
                        "compiled_sql": None,
                        "python_code": None,
                    },
                )
                _insert_capsule(
                    services.settings.capsule_db_path,
                    {
                        "run_id": run_id,
                        "created_at": _utc_now_iso(),
                        "dataset_id": request.dataset_id,
                        "dataset_version_hash": dataset.get("version_hash"),
                        "question": request.message,
                        "query_mode": "python",
                        "plan_json": None,
                        "compiled_sql": None,
                        "python_code": None,
                        "status": response.status,
                        "result_json": response.result,
                        "error_json": response.result.get("error"),
                        "exec_time_ms": 0,
                    },
                )
                return response
            query_mode = "python"
            python_code = request.message.split(":", 1)[1].strip()
            sql = ""
            assistant_message = "Executed Python analysis."
        elif explicit_sql:
            sql = request.message.split(":", 1)[1].strip()
        else:
            raw_draft = _generate_with_langchain(
                settings=services.settings,
                dataset=dataset,
                message=request.message,
                max_rows=services.settings.max_rows,
            )
            draft = _coerce_agent_draft(raw_draft)
            if draft:
                query_mode = draft.query_mode
                assistant_message = draft.assistant_message
                if query_mode == "sql":
                    sql = draft.sql or ""
                else:
                    try:
                        plan = draft.plan or _fallback_plan(request.dataset_id, dataset, services.settings.max_rows)
                    except ValidationError as exc:
                        raise HTTPException(status_code=400, detail=str(exc)) from exc
                    plan_json = plan.model_dump()
                    compiled_sql = services.compiler.compile(plan)
                    sql = compiled_sql
            else:
                if raw_draft is not None:
                    LOGGER.warning("LLM output could not be parsed as AgentDraft; trying SQL rescue.")

                rescue = _generate_sql_rescue_with_langchain(
                    settings=services.settings,
                    dataset=dataset,
                    message=request.message,
                    max_rows=services.settings.max_rows,
                )
                if rescue:
                    query_mode = "sql"
                    assistant_message = rescue.assistant_message
                    sql = rescue.sql
                else:
                    plan = _fallback_plan(request.dataset_id, dataset, services.settings.max_rows)
                    plan_json = plan.model_dump()
                    compiled_sql = services.compiler.compile(plan)
                    sql = compiled_sql
                    assistant_message = "LLM unavailable or invalid response; executed a safe fallback query."

        if query_mode != "python":
            sql = _normalize_sql_for_dataset(sql, request.dataset_id)

            status_cb("validating")
            sql_policy_error = _validate_sql_policy(sql)
            if sql_policy_error:
                result = {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {
                        "type": "SQL_POLICY_VIOLATION",
                        "message": sql_policy_error,
                    },
                }
                response = ChatResponse(
                    assistant_message="Query rejected by SQL policy.",
                    run_id=run_id,
                    status="rejected",
                    result=result,
                    details={
                        "dataset_id": request.dataset_id,
                        "query_mode": query_mode,
                        "plan_json": plan_json,
                        "compiled_sql": compiled_sql or sql,
                        "python_code": python_code,
                    },
                )
                _insert_capsule(
                    services.settings.capsule_db_path,
                    {
                        "run_id": run_id,
                        "created_at": _utc_now_iso(),
                        "dataset_id": request.dataset_id,
                        "dataset_version_hash": dataset.get("version_hash"),
                        "question": request.message,
                        "query_mode": query_mode,
                        "plan_json": plan_json,
                        "compiled_sql": compiled_sql or sql,
                        "python_code": python_code,
                        "status": response.status,
                        "result_json": response.result,
                        "error_json": response.result.get("error"),
                        "exec_time_ms": 0,
                    },
                )
                return response
        else:
            status_cb("validating")

        status_cb("executing")
        runner_result = services.runner_executor(
            services.settings,
            dataset,
            sql,
            services.settings.run_timeout_seconds,
            services.settings.max_rows,
            query_type=query_mode,
            python_code=python_code,
            max_output_bytes=services.settings.max_output_bytes,
        )

        response_status = _normalize_runner_to_status(runner_result)
        response = ChatResponse(
            assistant_message=assistant_message,
            run_id=run_id,
            status=response_status,
            result={
                "columns": runner_result.get("columns", []),
                "rows": runner_result.get("rows", []),
                "row_count": runner_result.get("row_count", 0),
                "exec_time_ms": runner_result.get("exec_time_ms", 0),
                "error": runner_result.get("error"),
            },
            details={
                "dataset_id": request.dataset_id,
                "query_mode": query_mode,
                "plan_json": plan_json,
                "compiled_sql": compiled_sql or sql if query_mode != "python" else None,
                "python_code": python_code,
            },
        )

        _insert_capsule(
            services.settings.capsule_db_path,
            {
                "run_id": run_id,
                "created_at": _utc_now_iso(),
                "dataset_id": request.dataset_id,
                "dataset_version_hash": dataset.get("version_hash"),
                "question": request.message,
                "query_mode": query_mode,
                "plan_json": plan_json,
                "compiled_sql": compiled_sql or sql if query_mode != "python" else None,
                "python_code": python_code,
                "status": response.status,
                "result_json": response.result,
                "error_json": response.result.get("error"),
                "exec_time_ms": response.result.get("exec_time_ms", 0),
            },
        )
        return response

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/datasets")
    async def list_datasets():
        registry = _load_registry(app.state.services.settings)
        datasets = []
        for ds in registry.get("datasets", []):
            datasets.append(
                {
                    "id": ds["id"],
                    "name": ds["name"],
                    "description": ds.get("description"),
                    "prompts": ds.get("prompts", []),
                    "version_hash": ds.get("version_hash"),
                }
            )
        return {"datasets": datasets}

    @app.get("/datasets/{dataset_id}/schema")
    async def dataset_schema(dataset_id: str):
        registry = _load_registry(app.state.services.settings)
        try:
            ds = _dataset_by_id(registry, dataset_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Dataset not found")

        files = []
        for f in ds.get("files", []):
            rel_path = f["path"]
            abs_path = Path(app.state.services.settings.datasets_dir) / rel_path
            files.append(
                {
                    "name": f["name"],
                    "path": rel_path,
                    "schema": f.get("schema", {}),
                    "sample_rows": _sample_rows(abs_path, max_rows=3),
                }
            )
        return {"id": ds["id"], "name": ds["name"], "files": files}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        try:
            return process_chat(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/chat/stream")
    async def chat_stream(request: StreamRequest):
        def sse(event: str, payload: Dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

        async def stream():
            statuses: list[str] = []

            def cb(stage: str):
                statuses.append(stage)

            try:
                response = process_chat(request, status_cb=cb)
                for stage in statuses:
                    yield sse("status", {"stage": stage})
                yield sse("result", response.model_dump())
                yield sse("done", {"run_id": response.run_id})
            except Exception as exc:  # pragma: no cover - defensive stream guard
                yield sse(
                    "error",
                    {
                        "type": "RUNNER_INTERNAL_ERROR",
                        "message": str(exc),
                    },
                )
                yield sse("done", {})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        capsule = _get_capsule(app.state.services.settings.capsule_db_path, run_id)
        if not capsule:
            raise HTTPException(status_code=404, detail="Run not found")
        return capsule

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return HTMLResponse(
            """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>CSV Analyst Chat</title>
  <style>
    body { font-family: sans-serif; margin: 2rem; max-width: 900px; }
    textarea, input, select { width: 100%; margin-top: .5rem; margin-bottom: 1rem; }
    table, th, td { border: 1px solid #ddd; border-collapse: collapse; padding: .25rem .5rem; }
    #status { color: #555; margin-bottom: .75rem; }
    pre { background: #f6f6f6; padding: .5rem; overflow-x: auto; }
  </style>
</head>
<body>
  <h1>CSV Analyst Chat (Minimal)</h1>
  <label>Dataset</label>
  <select id="dataset"></select>
  <label>Message</label>
  <textarea id="message" rows="4" placeholder="Ask a question, SQL: SELECT ..., or PYTHON: result = ..."></textarea>
  <button id="send">Send</button>
  <div id="status"></div>
  <h3>Assistant</h3>
  <pre id="assistant"></pre>
  <h3>Result</h3>
  <div id="result"></div>
  <h3>Details</h3>
  <pre id="details"></pre>
  <script>
    async function loadDatasets() {
      const res = await fetch('/datasets');
      const data = await res.json();
      const sel = document.getElementById('dataset');
      sel.innerHTML = '';
      for (const ds of data.datasets) {
        const opt = document.createElement('option');
        opt.value = ds.id;
        opt.textContent = ds.id + ' - ' + ds.name;
        sel.appendChild(opt);
      }
    }

    function renderTable(columns, rows) {
      if (!columns || columns.length === 0) return '<em>No rows</em>';
      let html = '<table><thead><tr>';
      for (const c of columns) html += `<th>${c}</th>`;
      html += '</tr></thead><tbody>';
      for (const r of rows) {
        html += '<tr>';
        for (const v of r) html += `<td>${v ?? ''}</td>`;
        html += '</tr>';
      }
      html += '</tbody></table>';
      return html;
    }

    function updateFromPayload(data) {
      document.getElementById('status').textContent = `Status: ${data.status}`;
      document.getElementById('assistant').textContent = data.assistant_message;
      document.getElementById('result').innerHTML = renderTable(data.result.columns, data.result.rows);
      document.getElementById('details').textContent = JSON.stringify(data.details, null, 2);
    }

    document.getElementById('send').onclick = async () => {
      const dataset_id = document.getElementById('dataset').value;
      const message = document.getElementById('message').value;
      document.getElementById('status').textContent = 'Streaming...';
      const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ dataset_id, message }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        while (buffer.includes('\\n\\n')) {
          const idx = buffer.indexOf('\\n\\n');
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);

          let eventName = '';
          let eventData = '';
          for (const line of chunk.split('\\n')) {
            if (line.startsWith('event: ')) eventName = line.slice(7).trim();
            if (line.startsWith('data: ')) eventData = line.slice(6).trim();
          }
          if (!eventName || !eventData) continue;
          const parsed = JSON.parse(eventData);

          if (eventName === 'status') {
            document.getElementById('status').textContent = `Stage: ${parsed.stage}`;
          } else if (eventName === 'result') {
            updateFromPayload(parsed);
          } else if (eventName === 'error') {
            document.getElementById('status').textContent = `Error: ${parsed.message || 'unknown'}`;
          }
        }
      }
    };

    loadDatasets();
  </script>
</body>
</html>
            """.strip()
        )

    return app


app = create_app()
