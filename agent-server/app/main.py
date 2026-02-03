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
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from .datasets import get_dataset_by_id, load_registry
from .executors import create_sandbox_executor
from .models.query_plan import QueryPlan, SelectColumn
from .storage import MessageStore, create_message_store
from .storage.capsules import get_capsule, init_capsule_db, insert_capsule
from .validators.compiler import QueryPlanCompiler
from .validators.sql_policy import normalize_sql_for_dataset, validate_sql_policy

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
    sandbox_provider: Literal["docker", "microsandbox"] = Field(default="docker")
    msb_server_url: str = Field(default="http://127.0.0.1:5555/api/v1/rpc")
    msb_api_key: str = Field(default="")
    msb_namespace: str = Field(default="default")
    msb_memory_mb: int = Field(default=512)
    msb_cpus: float = Field(default=1.0)
    storage_provider: str = Field(default="sqlite")
    thread_history_window: int = Field(default=12)
    log_level: str = Field(default="info")

    @model_validator(mode="after")
    def _validate_provider_config(self) -> "Settings":
        if self.sandbox_provider == "microsandbox" and not self.msb_server_url.strip():
            raise ValueError("msb_server_url is required when sandbox_provider=microsandbox")
        if self.msb_memory_mb <= 0:
            raise ValueError("msb_memory_mb must be > 0")
        if self.msb_cpus <= 0:
            raise ValueError("msb_cpus must be > 0")
        return self


class ChatRequest(BaseModel):
    """Chat request body."""

    dataset_id: str
    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response body."""

    assistant_message: str
    run_id: str
    thread_id: Optional[str] = None
    status: Literal["succeeded", "failed", "rejected"]
    result: Dict[str, Any]
    details: Dict[str, Any]


class StreamRequest(ChatRequest):
    """Streaming request body (same as chat request)."""


class RunSubmitRequest(BaseModel):
    """Direct run submission endpoint payload."""

    dataset_id: str
    query_type: Literal["sql", "python", "plan"] = "sql"
    sql: Optional[str] = None
    python_code: Optional[str] = None
    plan_json: Optional[Dict[str, Any]] = None


class AgentDraft(BaseModel):
    """Structured output target for optional LLM query generation."""

    query_mode: Literal["plan", "sql", "chat"] = "plan"
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


class PythonDraft(BaseModel):
    """Structured python execution payload."""

    python_code: str
    assistant_message: str = "Executed Python analysis."

    @model_validator(mode="after")
    def _validate_python(self) -> "PythonDraft":
        if not self.python_code.strip():
            raise ValueError("python_code is required")
        return self


def _is_python_intent(message: str) -> bool:
    lowered = message.lower()
    python_markers = [
        "use pandas",
        "using pandas",
        "python dataframe",
        "in python",
        "with pandas",
        "python code",
    ]
    return any(marker in lowered for marker in python_markers)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    LOGGER.info(json.dumps(payload, default=str))


def _load_registry(settings: Settings) -> Dict[str, Any]:
    return load_registry(settings.datasets_dir)


def _dataset_by_id(registry: Dict[str, Any], dataset_id: str) -> Dict[str, Any]:
    return get_dataset_by_id(registry, dataset_id)


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
    return validate_sql_policy(sql)


def _normalize_sql_for_dataset(sql: str, dataset_id: str) -> str:
    return normalize_sql_for_dataset(sql, dataset_id)


def _init_capsule_db(db_path: str) -> None:
    init_capsule_db(db_path)


def _insert_capsule(db_path: str, capsule: Dict[str, Any]) -> None:
    insert_capsule(db_path, capsule)


def _get_capsule(db_path: str, run_id: str) -> Optional[Dict[str, Any]]:
    return get_capsule(db_path, run_id)


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


def _build_runner_payload(
    dataset: Dict[str, Any],
    sql: str,
    timeout_seconds: int,
    max_rows: int,
    query_type: str,
    python_code: Optional[str],
    max_output_bytes: int,
) -> Dict[str, Any]:
    files = []
    for entry in dataset.get("files", []):
        files.append(
            {
                "name": entry["name"],
                "path": f"/data/{entry['path']}",
            }
        )

    payload: Dict[str, Any] = {
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
    return payload


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
    history: Optional[list[dict[str, Any]]] = None,
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
    history_text = _format_history_text(history)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a careful data analyst. Choose query_mode='chat' when the user asks for "
                    "greetings, capabilities, clarification, or schema/metadata that can be answered "
                    "without running a query. Otherwise default to query_mode='plan' with a valid QueryPlan. "
                    "Only use query_mode='sql' when the user explicitly asks for SQL. "
                    "Always keep LIMIT <= {max_rows}."
                ),
            ),
            (
                "human",
                "Dataset schema: {schema}\n\nConversation history:\n{history}\n\nUser message: {message}",
            ),
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
            "history": history_text,
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


def _coerce_python_draft(raw: Any) -> Optional[PythonDraft]:
    if raw is None:
        return None
    if isinstance(raw, PythonDraft):
        return raw

    candidate: Any = raw
    if isinstance(raw, dict):
        if isinstance(raw.get("parsed"), PythonDraft):
            return raw["parsed"]
        if isinstance(raw.get("parsed"), dict):
            candidate = raw["parsed"]
        elif isinstance(raw.get("output"), dict):
            candidate = raw["output"]

    if isinstance(candidate, dict):
        try:
            return PythonDraft.model_validate(candidate)
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
            return PythonDraft.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None

    if hasattr(candidate, "model_dump"):
        try:
            return PythonDraft.model_validate(candidate.model_dump())
        except ValidationError:
            return None

    return None


def _generate_python_with_langchain(
    settings: Settings,
    dataset: Dict[str, Any],
    message: str,
    max_rows: int,
    history: Optional[list[dict[str, Any]]] = None,
) -> Optional[PythonDraft]:
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
    history_text = _format_history_text(history)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "Produce executable pandas code only in structured output. "
                    "Use provided table DataFrames by name (e.g. tickets, orders). "
                    "Set result_df or result. Keep output to <= {max_rows} rows."
                ),
            ),
            (
                "human",
                "Dataset schema: {schema}\n\nConversation history:\n{history}\n\nUser message: {message}",
            ),
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
            ).with_structured_output(PythonDraft)

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
            ).with_structured_output(PythonDraft)

    if model is None:
        return None

    chain = prompt | model
    raw = chain.invoke(
        {
            "schema": json.dumps(schema_summary),
            "history": history_text,
            "message": message,
            "max_rows": max_rows,
        }
    )
    return _coerce_python_draft(raw)


def _heuristic_python_from_message(
    message: str,
    dataset: Dict[str, Any],
    max_rows: int,
) -> Optional[str]:
    """Fallback python generator for simple 'group by X' requests."""
    lowered = message.lower()
    match = re.search(r"group(?:\s+\w+)*\s+by\s+([a-zA-Z_][a-zA-Z0-9_]*)", lowered)
    if not match:
        return None
    target_col = match.group(1).strip().rstrip("?.!,")

    for file in dataset.get("files", []):
        table = Path(file["name"]).stem
        schema_cols = {c.lower(): c for c in file.get("schema", {}).keys()}
        if target_col in schema_cols:
            col = schema_cols[target_col]
            return (
                f'result_df = {table}.groupby("{col}").size().reset_index(name="count")'
                '.sort_values("count", ascending=False).head('
                f"{max_rows})"
            )
    return None


def _generate_sql_rescue_with_langchain(
    settings: Settings,
    dataset: Dict[str, Any],
    message: str,
    max_rows: int,
    history: Optional[list[dict[str, Any]]] = None,
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
    history_text = _format_history_text(history)

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
            (
                "human",
                "Dataset schema: {schema}\n\nConversation history:\n{history}\n\nUser message: {message}",
            ),
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
            "history": history_text,
            "message": message,
            "max_rows": max_rows,
        }
    )
    return _coerce_sql_rescue_draft(raw)


def _format_history_text(history: Optional[list[dict[str, Any]]]) -> str:
    if not history:
        return "(no previous messages)"
    lines: list[str] = []
    for item in history:
        role = item.get("role", "unknown")
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(no previous messages)"


def _humanize_label(name: str) -> str:
    return name.replace("_", " ").strip()


def _summarize_result_for_user(
    *,
    question: str,
    query_mode: str,
    result: Dict[str, Any],
) -> str:
    if result.get("status") != "success":
        err = result.get("error", {}) or {}
        msg = err.get("message") or "Execution failed."
        return f"I couldn't execute that request successfully: {msg}"

    columns = result.get("columns", []) or []
    rows = result.get("rows", []) or []
    row_count = int(result.get("row_count", len(rows)) or 0)

    if row_count == 0:
        return "No rows matched your request."

    if len(columns) == 1 and len(rows) == 1:
        col = str(columns[0])
        value = rows[0][0]
        col_lower = col.lower()
        if col_lower.startswith("total_"):
            subject = _humanize_label(col_lower[6:])
            return f"There are {value} total {subject} in the dataset."
        if col_lower in {"count", "n", "total", "total_count", "row_count"}:
            return f"The result is {value}."
        return f"{_humanize_label(col)}: {value}."

    if len(rows) <= 5 and len(columns) <= 4:
        first = rows[0]
        pairs = ", ".join(
            f"{_humanize_label(str(col))}={first[i]}" for i, col in enumerate(columns) if i < len(first)
        )
        if len(rows) == 1:
            return f"I found one row: {pairs}. See Result for full details."
        return f"I found {len(rows)} rows. First row: {pairs}. See Result for full details."

    mode_hint = "Python analysis" if query_mode == "python" else "query"
    return (
        f"I ran the {mode_hint} and returned {row_count} rows across {len(columns)} columns. "
        "Please see the Result table for the full breakdown."
    )


@dataclass
class AppServices:
    settings: Settings
    runner_executor: Callable[..., Dict[str, Any]]
    compiler: QueryPlanCompiler
    message_store: MessageStore


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
        sandbox_provider=os.getenv("SANDBOX_PROVIDER", "docker"),
        msb_server_url=os.getenv("MSB_SERVER_URL", "http://127.0.0.1:5555/api/v1/rpc"),
        msb_api_key=os.getenv("MSB_API_KEY", ""),
        msb_namespace=os.getenv("MSB_NAMESPACE", "default"),
        msb_memory_mb=int(os.getenv("MSB_MEMORY_MB", "512")),
        msb_cpus=float(os.getenv("MSB_CPUS", "1.0")),
        storage_provider=os.getenv("STORAGE_PROVIDER", "sqlite"),
        thread_history_window=int(os.getenv("THREAD_HISTORY_WINDOW", "12")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    _init_capsule_db(settings.capsule_db_path)
    message_store = create_message_store(settings.storage_provider, settings.capsule_db_path)
    message_store.initialize()

    default_runner_callable: Callable[..., Dict[str, Any]]
    if settings.sandbox_provider == "docker":
        default_runner_callable = _default_runner_executor
    else:
        sandbox_executor = create_sandbox_executor(
            provider=settings.sandbox_provider,
            runner_image=settings.runner_image,
            datasets_dir=settings.datasets_dir,
            timeout_seconds=settings.run_timeout_seconds,
            max_rows=settings.max_rows,
            max_output_bytes=settings.max_output_bytes,
            msb_server_url=settings.msb_server_url,
            msb_api_key=settings.msb_api_key,
            msb_namespace=settings.msb_namespace,
            msb_memory_mb=settings.msb_memory_mb,
            msb_cpus=settings.msb_cpus,
        )

        def _provider_runner_executor(
            _settings: Settings,
            dataset: Dict[str, Any],
            sql: str,
            timeout_seconds: int,
            max_rows: int,
            query_type: str = "sql",
            python_code: Optional[str] = None,
            max_output_bytes: int = 65536,
        ) -> Dict[str, Any]:
            payload = _build_runner_payload(
                dataset=dataset,
                sql=sql,
                timeout_seconds=timeout_seconds,
                max_rows=max_rows,
                query_type=query_type,
                python_code=python_code,
                max_output_bytes=max_output_bytes,
            )
            out = sandbox_executor.submit_run(payload, query_type=query_type)
            return out.get("result", {})

        default_runner_callable = _provider_runner_executor

    app = FastAPI(title="CSV Analyst Agent Server")
    app.state.services = AppServices(
        settings=settings,
        runner_executor=runner_executor or default_runner_callable,
        compiler=QueryPlanCompiler(),
        message_store=message_store,
    )

    # Tool-style helpers used by chat flow and /runs endpoint.
    def tool_list_datasets() -> Dict[str, Any]:
        registry = _load_registry(app.state.services.settings)
        return {
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

    def tool_get_dataset_schema(dataset_id: str) -> Dict[str, Any]:
        registry = _load_registry(app.state.services.settings)
        ds = _dataset_by_id(registry, dataset_id)
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

    def tool_execute_sql(dataset: Dict[str, Any], sql: str) -> Dict[str, Any]:
        sql = _normalize_sql_for_dataset(sql, dataset["id"])
        policy_error = _validate_sql_policy(sql)
        if policy_error:
            return {
                "status": "rejected",
                "result": {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {"type": "SQL_POLICY_VIOLATION", "message": policy_error},
                },
                "compiled_sql": sql,
            }

        runner_result = app.state.services.runner_executor(
            app.state.services.settings,
            dataset,
            sql,
            app.state.services.settings.run_timeout_seconds,
            app.state.services.settings.max_rows,
            query_type="sql",
            python_code=None,
            max_output_bytes=app.state.services.settings.max_output_bytes,
        )
        return {"status": _normalize_runner_to_status(runner_result), "result": runner_result, "compiled_sql": sql}

    def tool_execute_query_plan(dataset: Dict[str, Any], plan_json: Dict[str, Any]) -> Dict[str, Any]:
        plan = QueryPlan.model_validate(plan_json)
        compiled_sql = app.state.services.compiler.compile(plan)
        outcome = tool_execute_sql(dataset, compiled_sql)
        outcome["plan_json"] = plan.model_dump()
        return outcome

    def tool_execute_python(dataset: Dict[str, Any], python_code: str) -> Dict[str, Any]:
        if not app.state.services.settings.enable_python_execution:
            return {
                "status": "rejected",
                "result": {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {"type": "FEATURE_DISABLED", "message": "Python execution mode is disabled."},
                },
            }
        runner_result = app.state.services.runner_executor(
            app.state.services.settings,
            dataset,
            "",
            app.state.services.settings.run_timeout_seconds,
            app.state.services.settings.max_rows,
            query_type="python",
            python_code=python_code,
            max_output_bytes=app.state.services.settings.max_output_bytes,
        )
        return {"status": _normalize_runner_to_status(runner_result), "result": runner_result}

    def tool_get_run_status(run_id: str) -> Dict[str, Any]:
        capsule = _get_capsule(app.state.services.settings.capsule_db_path, run_id)
        if not capsule:
            return {"run_id": run_id, "status": "not_found"}
        return {"run_id": run_id, "status": capsule.get("status")}

    def process_chat(
        request: ChatRequest,
        status_cb: Optional[Callable[[str], None]] = None,
    ) -> ChatResponse:
        services: AppServices = app.state.services
        registry = _load_registry(services.settings)
        dataset = _dataset_by_id(registry, request.dataset_id)
        run_id = str(uuid.uuid4())
        thread_id = request.thread_id or f"thread-{uuid.uuid4()}"
        status_cb = status_cb or (lambda *_: None)
        _log_event(
            "chat.request",
            run_id=run_id,
            thread_id=thread_id,
            dataset_id=request.dataset_id,
            sandbox_provider=services.settings.sandbox_provider,
            message=request.message,
        )

        history = services.message_store.get_messages(
            thread_id=thread_id,
            limit=max(1, services.settings.thread_history_window),
        )
        services.message_store.append_message(
            thread_id=thread_id,
            role="user",
            content=request.message,
            dataset_id=request.dataset_id,
            run_id=run_id,
        )

        def persist_capsule(
            *,
            response: ChatResponse,
            query_mode: str,
            plan_json: Optional[Dict[str, Any]],
            compiled_sql: Optional[str],
            python_code: Optional[str],
        ) -> None:
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
                    "compiled_sql": compiled_sql,
                    "python_code": python_code,
                    "status": response.status,
                    "result_json": response.result,
                    "error_json": response.result.get("error"),
                    "exec_time_ms": response.result.get("exec_time_ms", 0),
                },
            )

        def persist_assistant(content: str) -> None:
            services.message_store.append_message(
                thread_id=thread_id,
                role="assistant",
                content=content,
                dataset_id=request.dataset_id,
                run_id=run_id,
            )

        status_cb("planning")
        explicit_sql = request.message.strip().lower().startswith("sql:")
        explicit_python = request.message.strip().lower().startswith("python:")
        implicit_python = _is_python_intent(request.message) and not explicit_sql

        query_mode: Literal["sql", "plan", "python", "chat"] = "sql" if explicit_sql else "plan"
        assistant_message = "Executed query."
        plan_json = None
        compiled_sql = None
        python_code = None

        if explicit_python or implicit_python:
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
                    thread_id=thread_id,
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
                persist_capsule(
                    response=response,
                    query_mode="python",
                    plan_json=None,
                    compiled_sql=None,
                    python_code=None,
                )
                persist_assistant(response.assistant_message)
                _log_event(
                    "chat.rejected",
                    run_id=run_id,
                    reason="python_disabled",
                    sandbox_provider=services.settings.sandbox_provider,
                )
                return response
            query_mode = "python"
            if explicit_python:
                python_code = request.message.split(":", 1)[1].strip()
                assistant_message = "Executed Python analysis."
            else:
                generated = _generate_python_with_langchain(
                    settings=services.settings,
                    dataset=dataset,
                    message=request.message,
                    max_rows=services.settings.max_rows,
                    history=history,
                )
                if generated:
                    python_code = generated.python_code
                    assistant_message = generated.assistant_message
                else:
                    python_code = _heuristic_python_from_message(
                        message=request.message,
                        dataset=dataset,
                        max_rows=services.settings.max_rows,
                    )
                    if python_code:
                        assistant_message = "Generated pandas code from request and executed it."
                    else:
                        result = {
                            "columns": [],
                            "rows": [],
                            "row_count": 0,
                            "exec_time_ms": 0,
                            "error": {
                                "type": "VALIDATION_ERROR",
                                "message": (
                                    "Could not generate executable Python code. "
                                    "Use explicit 'PYTHON: ...' format."
                                ),
                            },
                        }
                        response = ChatResponse(
                            assistant_message=(
                                "I couldn't generate safe Python for that request. "
                                "Please provide explicit code with 'PYTHON: ...'."
                            ),
                            run_id=run_id,
                            thread_id=thread_id,
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
                        persist_capsule(
                            response=response,
                            query_mode="python",
                            plan_json=None,
                            compiled_sql=None,
                            python_code=None,
                        )
                        persist_assistant(response.assistant_message)
                        _log_event(
                            "chat.rejected",
                            run_id=run_id,
                            reason="python_generation_failed",
                            sandbox_provider=services.settings.sandbox_provider,
                        )
                        return response
            sql = ""
        elif explicit_sql:
            sql = request.message.split(":", 1)[1].strip()
        else:
            raw_draft = _generate_with_langchain(
                settings=services.settings,
                dataset=dataset,
                message=request.message,
                max_rows=services.settings.max_rows,
                history=history,
            )
            draft = _coerce_agent_draft(raw_draft)
            if draft:
                query_mode = draft.query_mode
                assistant_message = draft.assistant_message
                if query_mode == "chat":
                    response = ChatResponse(
                        assistant_message=assistant_message,
                        run_id=run_id,
                        thread_id=thread_id,
                        status="succeeded",
                        result={
                            "columns": [],
                            "rows": [],
                            "row_count": 0,
                            "exec_time_ms": 0,
                            "error": None,
                        },
                        details={
                            "dataset_id": request.dataset_id,
                            "query_mode": "chat",
                            "plan_json": None,
                            "compiled_sql": None,
                            "python_code": None,
                        },
                    )
                    persist_capsule(
                        response=response,
                        query_mode="chat",
                        plan_json=None,
                        compiled_sql=None,
                        python_code=None,
                    )
                    persist_assistant(response.assistant_message)
                    _log_event(
                        "chat.completed",
                        run_id=run_id,
                        status=response.status,
                        query_mode="chat",
                        sandbox_provider=services.settings.sandbox_provider,
                    )
                    return response
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
                    history=history,
                )
                if rescue:
                    query_mode = "sql"
                    assistant_message = rescue.assistant_message
                    sql = rescue.sql
                else:
                    response = ChatResponse(
                        assistant_message=(
                            "LLM service unavailable or returned an invalid response. "
                            "Please try again, or use explicit `SQL:` / `PYTHON:`."
                        ),
                        run_id=run_id,
                        thread_id=thread_id,
                        status="rejected",
                        result={
                            "columns": [],
                            "rows": [],
                            "row_count": 0,
                            "exec_time_ms": 0,
                            "error": {
                                "type": "LLM_UNAVAILABLE",
                                "message": "LLM service unavailable or returned invalid response.",
                            },
                        },
                        details={
                            "dataset_id": request.dataset_id,
                            "query_mode": "chat",
                            "plan_json": None,
                            "compiled_sql": None,
                            "python_code": None,
                        },
                    )
                    persist_capsule(
                        response=response,
                        query_mode="chat",
                        plan_json=None,
                        compiled_sql=None,
                        python_code=None,
                    )
                    persist_assistant(response.assistant_message)
                    _log_event(
                        "chat.rejected",
                        run_id=run_id,
                        reason="llm_unavailable_or_invalid",
                        sandbox_provider=services.settings.sandbox_provider,
                    )
                    return response

        if query_mode not in {"python", "chat"}:
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
                    thread_id=thread_id,
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
                persist_capsule(
                    response=response,
                    query_mode=query_mode,
                    plan_json=plan_json,
                    compiled_sql=compiled_sql or sql,
                    python_code=python_code,
                )
                persist_assistant(response.assistant_message)
                _log_event(
                    "chat.rejected",
                    run_id=run_id,
                    reason="sql_policy",
                    sandbox_provider=services.settings.sandbox_provider,
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
        final_message = _summarize_result_for_user(
            question=request.message,
            query_mode=query_mode,
            result=runner_result,
        )
        response = ChatResponse(
            assistant_message=final_message,
            run_id=run_id,
            thread_id=thread_id,
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

        persist_capsule(
            response=response,
            query_mode=query_mode,
            plan_json=plan_json,
            compiled_sql=compiled_sql or sql if query_mode != "python" else None,
            python_code=python_code,
        )
        persist_assistant(response.assistant_message)
        _log_event(
            "chat.completed",
            run_id=run_id,
            status=response.status,
            query_mode=query_mode,
            sandbox_provider=services.settings.sandbox_provider,
        )
        return response

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/datasets")
    async def list_datasets():
        return tool_list_datasets()

    @app.get("/datasets/{dataset_id}/schema")
    async def dataset_schema(dataset_id: str):
        try:
            return tool_get_dataset_schema(dataset_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Dataset not found")

    @app.post("/runs", response_model=ChatResponse)
    async def submit_run(request: RunSubmitRequest):
        services: AppServices = app.state.services
        registry = _load_registry(services.settings)
        try:
            dataset = _dataset_by_id(registry, request.dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        run_id = str(uuid.uuid4())
        created_at = _utc_now_iso()
        query_mode = request.query_type
        compiled_sql = None
        plan_json = request.plan_json
        python_code = request.python_code

        if request.query_type == "sql":
            if not request.sql:
                raise HTTPException(status_code=400, detail="sql is required for query_type=sql")
            outcome = tool_execute_sql(dataset, request.sql)
            compiled_sql = outcome.get("compiled_sql")
        elif request.query_type == "python":
            if not request.python_code:
                raise HTTPException(status_code=400, detail="python_code is required for query_type=python")
            outcome = tool_execute_python(dataset, request.python_code)
        else:
            if not request.plan_json:
                raise HTTPException(status_code=400, detail="plan_json is required for query_type=plan")
            try:
                outcome = tool_execute_query_plan(dataset, request.plan_json)
                plan_json = outcome.get("plan_json")
                compiled_sql = outcome.get("compiled_sql")
            except ValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        status = outcome.get("status", "failed")
        raw_result = outcome.get("result", {})
        response = ChatResponse(
            assistant_message="Run submitted and executed.",
            run_id=run_id,
            status=status if status in {"succeeded", "failed", "rejected"} else "failed",
            result={
                "columns": raw_result.get("columns", []),
                "rows": raw_result.get("rows", []),
                "row_count": raw_result.get("row_count", 0),
                "exec_time_ms": raw_result.get("exec_time_ms", 0),
                "error": raw_result.get("error"),
            },
            details={
                "dataset_id": request.dataset_id,
                "query_mode": query_mode,
                "plan_json": plan_json,
                "compiled_sql": compiled_sql,
                "python_code": python_code,
            },
        )
        _insert_capsule(
            services.settings.capsule_db_path,
            {
                "run_id": run_id,
                "created_at": created_at,
                "dataset_id": request.dataset_id,
                "dataset_version_hash": dataset.get("version_hash"),
                "question": None,
                "query_mode": query_mode,
                "plan_json": plan_json,
                "compiled_sql": compiled_sql,
                "python_code": python_code,
                "status": response.status,
                "result_json": response.result,
                "error_json": response.result.get("error"),
                "exec_time_ms": response.result.get("exec_time_ms", 0),
            },
        )
        return response

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

    @app.get("/runs/{run_id}/status")
    async def get_run_status(run_id: str):
        return tool_get_run_status(run_id)

    @app.get("/threads/{thread_id}/messages")
    async def get_thread_messages(thread_id: str, limit: int = 50):
        capped = min(max(limit, 1), 200)
        return {
            "thread_id": thread_id,
            "messages": app.state.services.message_store.get_messages(
                thread_id=thread_id,
                limit=capped,
            ),
        }

    _STATIC_DIR = Path(__file__).resolve().parent / "static"

    @app.get("/")
    async def home():
        return FileResponse(_STATIC_DIR / "index.html")

    return app


app = create_app()
