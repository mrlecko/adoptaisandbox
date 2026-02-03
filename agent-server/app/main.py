"""
FastAPI agent server for CSV Analyst Chat.

Entry points:
  - create_app(settings, llm, executor) — factory used by production and tests
  - module-level `app = create_app()` — picked up by uvicorn
"""

from __future__ import annotations

import csv
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field, model_validator

from .agent import AgentSession, build_agent
from .datasets import get_dataset_by_id, load_registry
from .executors import create_sandbox_executor
from .llm import create_llm
from .storage import create_message_store
from .storage.capsules import get_capsule, init_capsule_db, insert_capsule
from .tools import create_tools
from .validators.compiler import QueryPlanCompiler
from .validators.sql_policy import normalize_sql_for_dataset, validate_sql_policy

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


LOGGER = logging.getLogger("csv-analyst-agent-server")


# ── Settings ──────────────────────────────────────────────────────────────


class Settings(BaseModel):
    """Runtime configuration for the server."""

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
    mlflow_tracking_uri: Optional[str] = Field(default=None)
    mlflow_experiment_name: str = Field(default="CSV Analyst Agent")
    mlflow_openai_autolog: bool = Field(default=False)
    log_level: str = Field(default="info")

    @model_validator(mode="after")
    def _validate_provider_config(self) -> "Settings":
        if self.sandbox_provider == "microsandbox" and not self.msb_server_url.strip():
            raise ValueError(
                "msb_server_url is required when sandbox_provider=microsandbox"
            )
        if self.msb_memory_mb <= 0:
            raise ValueError("msb_memory_mb must be > 0")
        if self.msb_cpus <= 0:
            raise ValueError("msb_cpus must be > 0")
        return self


# ── API Models ────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    dataset_id: str
    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    assistant_message: str
    run_id: str
    thread_id: Optional[str] = None
    status: Literal["succeeded", "failed", "rejected", "timed_out"]
    result: Dict[str, Any]
    details: Dict[str, Any]


class StreamRequest(ChatRequest):
    pass


class RunSubmitRequest(BaseModel):
    dataset_id: str
    query_type: Literal["sql", "python", "plan"] = "sql"
    sql: Optional[str] = None
    python_code: Optional[str] = None
    plan_json: Optional[Dict[str, Any]] = None


# ── Helpers ───────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_mlflow_tracing(settings: Settings) -> None:
    """Enable MLflow GenAI tracing for OpenAI calls when configured."""
    if not settings.mlflow_openai_autolog:
        return
    if not settings.mlflow_tracking_uri:
        LOGGER.warning(
            "MLflow autolog requested but MLFLOW_TRACKING_URI is not set; tracing disabled."
        )
        return

    try:
        import mlflow
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("MLflow is unavailable; tracing disabled (%s).", exc)
        return

    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment_name)
        mlflow.openai.autolog()
        LOGGER.info(
            "MLflow OpenAI autolog enabled (uri=%s, experiment=%s).",
            settings.mlflow_tracking_uri,
            settings.mlflow_experiment_name,
        )
    except Exception as exc:
        LOGGER.warning(
            "Failed to enable MLflow tracing; continuing without it (%s).", exc
        )


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


def _execute_direct(
    executor: Any,
    settings: Settings,
    message_store: Any,
    capsule_db_path: str,
    request: ChatRequest,
    query_type: str,
    sql: str = "",
    python_code: str = "",
) -> Dict[str, Any]:
    """Fast-path execution for explicit SQL:/PYTHON: messages — no LLM involved."""
    registry = load_registry(settings.datasets_dir)
    dataset = get_dataset_by_id(registry, request.dataset_id)
    run_id = str(uuid.uuid4())
    thread_id = request.thread_id or f"thread-{uuid.uuid4()}"

    # Persist user message
    message_store.append_message(
        thread_id=thread_id,
        role="user",
        content=request.message,
        dataset_id=request.dataset_id,
        run_id=run_id,
    )

    compiled_sql: Optional[str] = None
    plan_json: Optional[Dict[str, Any]] = None
    status: str = "succeeded"
    result_payload: Dict[str, Any] = {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "exec_time_ms": 0,
        "error": None,
    }
    assistant_message = "Executed query."

    if query_type == "sql":
        # Normalize + policy check
        sql = normalize_sql_for_dataset(sql, request.dataset_id)
        compiled_sql = sql
        policy_error = validate_sql_policy(sql)
        if policy_error:
            status = "rejected"
            assistant_message = "Query rejected by SQL policy."
            result_payload = {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "error": {"type": "SQL_POLICY_VIOLATION", "message": policy_error},
            }
        else:
            # Build payload and submit
            files = [
                {"name": e["name"], "path": f"/data/{e['path']}"}
                for e in dataset.get("files", [])
            ]
            payload = {
                "dataset_id": dataset["id"],
                "files": files,
                "query_type": "sql",
                "timeout_seconds": settings.run_timeout_seconds,
                "max_rows": settings.max_rows,
                "max_output_bytes": settings.max_output_bytes,
                "sql": sql,
            }
            raw = executor.submit_run(payload, query_type="sql")
            runner_result = raw.get("result", raw)
            status = _map_runner_status(runner_result)
            result_payload = {
                "columns": runner_result.get("columns", []),
                "rows": runner_result.get("rows", []),
                "row_count": runner_result.get("row_count", 0),
                "exec_time_ms": runner_result.get("exec_time_ms", 0),
                "error": runner_result.get("error"),
            }
            assistant_message = _summarize_result(
                request.message, "sql", result_payload
            )

    elif query_type == "python":
        if not settings.enable_python_execution:
            status = "rejected"
            assistant_message = "Query rejected: Python execution is disabled."
            result_payload = {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "error": {
                    "type": "FEATURE_DISABLED",
                    "message": "Python execution mode is disabled.",
                },
            }
        else:
            files = [
                {"name": e["name"], "path": f"/data/{e['path']}"}
                for e in dataset.get("files", [])
            ]
            payload = {
                "dataset_id": dataset["id"],
                "files": files,
                "query_type": "python",
                "timeout_seconds": settings.run_timeout_seconds,
                "max_rows": settings.max_rows,
                "max_output_bytes": settings.max_output_bytes,
                "python_code": python_code,
            }
            raw = executor.submit_run(payload, query_type="python")
            runner_result = raw.get("result", raw)
            status = _map_runner_status(runner_result)
            result_payload = {
                "columns": runner_result.get("columns", []),
                "rows": runner_result.get("rows", []),
                "row_count": runner_result.get("row_count", 0),
                "exec_time_ms": runner_result.get("exec_time_ms", 0),
                "error": runner_result.get("error"),
            }
            assistant_message = _summarize_result(
                request.message, "python", result_payload
            )

    # Persist capsule
    insert_capsule(
        capsule_db_path,
        {
            "run_id": run_id,
            "created_at": _utc_now_iso(),
            "dataset_id": request.dataset_id,
            "dataset_version_hash": dataset.get("version_hash"),
            "question": request.message,
            "query_mode": query_type,
            "plan_json": plan_json,
            "compiled_sql": compiled_sql,
            "python_code": python_code if query_type == "python" else None,
            "status": status,
            "result_json": result_payload,
            "error_json": result_payload.get("error"),
            "exec_time_ms": result_payload.get("exec_time_ms", 0),
        },
    )

    # Persist assistant message
    message_store.append_message(
        thread_id=thread_id,
        role="assistant",
        content=assistant_message,
        dataset_id=request.dataset_id,
        run_id=run_id,
    )

    return {
        "assistant_message": assistant_message,
        "run_id": run_id,
        "thread_id": thread_id,
        "status": status,
        "result": result_payload,
        "details": {
            "dataset_id": request.dataset_id,
            "query_mode": query_type,
            "plan_json": plan_json,
            "compiled_sql": compiled_sql,
            "python_code": python_code if query_type == "python" else None,
        },
    }


def _summarize_result(question: str, query_mode: str, result: Dict[str, Any]) -> str:
    """Produce a human-readable summary of a query result."""
    if result.get("error"):
        msg = result["error"].get("message", "Execution failed.")
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
            subject = col_lower[6:].replace("_", " ").strip()
            return f"There are {value} total {subject} in the dataset."
        if col_lower in {"count", "n", "total", "total_count", "row_count"}:
            return f"The result is {value}."
        return f"{col.replace('_', ' ').strip()}: {value}."

    if len(rows) <= 5 and len(columns) <= 4:
        first = rows[0]
        pairs = ", ".join(
            f"{str(col).replace('_', ' ').strip()}={first[i]}"
            for i, col in enumerate(columns)
            if i < len(first)
        )
        if len(rows) == 1:
            return f"I found one row: {pairs}. See Result for full details."
        return f"I found {len(rows)} rows. First row: {pairs}. See Result for full details."

    mode_hint = "Python analysis" if query_mode == "python" else "query"
    return (
        f"I ran the {mode_hint} and returned {row_count} rows across {len(columns)} columns. "
        "Please see the Result table for the full breakdown."
    )


def _map_runner_status(
    runner_result: Dict[str, Any],
) -> Literal["succeeded", "failed", "timed_out"]:
    status = runner_result.get("status")
    error_type = (runner_result.get("error") or {}).get("type")
    if status == "timeout" or error_type == "TIMEOUT":
        return "timed_out"
    if status == "success":
        return "succeeded"
    return "failed"


# ── App Factory ───────────────────────────────────────────────────────────


def create_app(
    settings: Optional[Settings] = None,
    llm: Optional[Any] = None,
    executor: Optional[Any] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Override Settings (constructed from env if None).
        llm:      Injected LLM — skips create_llm() when provided (used by tests).
        executor: Injected Executor — skips factory when provided (used by tests).
    """
    # ── env + settings ──────────────────────────────────────────────────
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
        enable_python_execution=os.getenv("ENABLE_PYTHON_EXECUTION", "true").lower()
        == "true",
        sandbox_provider=os.getenv("SANDBOX_PROVIDER", "docker"),
        msb_server_url=os.getenv("MSB_SERVER_URL", "http://127.0.0.1:5555/api/v1/rpc"),
        msb_api_key=os.getenv("MSB_API_KEY", ""),
        msb_namespace=os.getenv("MSB_NAMESPACE", "default"),
        msb_memory_mb=int(os.getenv("MSB_MEMORY_MB", "512")),
        msb_cpus=float(os.getenv("MSB_CPUS", "1.0")),
        storage_provider=os.getenv("STORAGE_PROVIDER", "sqlite"),
        thread_history_window=int(os.getenv("THREAD_HISTORY_WINDOW", "12")),
        mlflow_tracking_uri=os.getenv("MLFLOW_TRACKING_URI"),
        mlflow_experiment_name=os.getenv("MLFLOW_EXPERIMENT_NAME", "CSV Analyst Agent"),
        mlflow_openai_autolog=os.getenv("MLFLOW_OPENAI_AUTOLOG", "false").lower()
        == "true",
        log_level=os.getenv("LOG_LEVEL", "info"),
    )

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    _configure_mlflow_tracing(settings)

    # ── storage ─────────────────────────────────────────────────────────
    init_capsule_db(settings.capsule_db_path)
    message_store = create_message_store(
        settings.storage_provider, settings.capsule_db_path
    )
    message_store.initialize()

    # ── executor (sandbox backend) ──────────────────────────────────────
    # ALL providers go through the factory now — docker is no longer special-cased.
    sandbox_executor = executor or create_sandbox_executor(
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

    # ── tools + LLM + agent ─────────────────────────────────────────────
    compiler = QueryPlanCompiler()
    tools = create_tools(
        executor=sandbox_executor,
        compiler=compiler,
        datasets_dir=settings.datasets_dir,
        max_rows=settings.max_rows,
        max_output_bytes=settings.max_output_bytes,
        timeout_seconds=settings.run_timeout_seconds,
        enable_python_execution=settings.enable_python_execution,
    )

    resolved_llm = llm or create_llm(settings)
    agent_graph = build_agent(tools, settings.max_rows, resolved_llm)

    session = AgentSession(
        agent_graph,
        message_store,
        settings.capsule_db_path,
        history_window=settings.thread_history_window,
    )

    # ── FastAPI app ─────────────────────────────────────────────────────
    app = FastAPI(title="CSV Analyst Agent Server")

    # ── routes ──────────────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/datasets")
    async def list_datasets():
        registry = load_registry(settings.datasets_dir)
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

    @app.get("/datasets/{dataset_id}/schema")
    async def dataset_schema(dataset_id: str):
        registry = load_registry(settings.datasets_dir)
        try:
            ds = get_dataset_by_id(registry, dataset_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Dataset not found")
        files = []
        for f in ds.get("files", []):
            abs_path = Path(settings.datasets_dir) / f["path"]
            files.append(
                {
                    "name": f["name"],
                    "path": f["path"],
                    "schema": f.get("schema", {}),
                    "sample_rows": _sample_rows(abs_path, max_rows=3),
                }
            )
        return {"id": ds["id"], "name": ds["name"], "files": files}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        msg = request.message.strip()
        # Fast paths: explicit SQL: or PYTHON: prefix
        if msg.lower().startswith("sql:"):
            sql = msg.split(":", 1)[1].strip()
            return _execute_direct(
                sandbox_executor,
                settings,
                message_store,
                settings.capsule_db_path,
                request,
                "sql",
                sql=sql,
            )
        if msg.lower().startswith("python:"):
            code = msg.split(":", 1)[1].strip()
            return _execute_direct(
                sandbox_executor,
                settings,
                message_store,
                settings.capsule_db_path,
                request,
                "python",
                python_code=code,
            )
        # Agent path
        thread_id = request.thread_id or f"thread-{uuid.uuid4()}"
        try:
            return session.run_agent(request.dataset_id, request.message, thread_id)
        except GraphRecursionError:
            # Defensive guard; AgentSession already handles this path.
            return {
                "assistant_message": (
                    "I hit an internal reasoning limit while refining that request. "
                    "Please rephrase with explicit fields/tables."
                ),
                "run_id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "status": "failed",
                "result": {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {
                        "type": "AGENT_RECURSION_LIMIT",
                        "message": "Agent reached recursion limit before completion.",
                    },
                },
                "details": {
                    "dataset_id": request.dataset_id,
                    "query_mode": "chat",
                    "plan_json": None,
                    "compiled_sql": None,
                    "python_code": None,
                },
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/chat/stream")
    async def chat_stream(request: StreamRequest):
        def sse(event: str, payload: Dict[str, Any]) -> str:
            # LangGraph event payloads can include non-JSON-native objects
            # (e.g., ToolMessage instances). Convert unknown objects to strings
            # so streaming never fails mid-run.
            return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"

        msg = request.message.strip()
        thread_id = request.thread_id or f"thread-{uuid.uuid4()}"

        # Fast paths emit synthetic events
        if msg.lower().startswith("sql:") or msg.lower().startswith("python:"):

            async def fast_stream():
                if msg.lower().startswith("sql:"):
                    sql = msg.split(":", 1)[1].strip()
                    resp = _execute_direct(
                        sandbox_executor,
                        settings,
                        message_store,
                        settings.capsule_db_path,
                        request,
                        "sql",
                        sql=sql,
                    )
                else:
                    code = msg.split(":", 1)[1].strip()
                    resp = _execute_direct(
                        sandbox_executor,
                        settings,
                        message_store,
                        settings.capsule_db_path,
                        request,
                        "python",
                        python_code=code,
                    )
                yield sse("status", {"stage": "planning"})
                yield sse("status", {"stage": "executing"})
                yield sse("result", resp)
                yield sse("done", {"run_id": resp["run_id"]})

            return StreamingResponse(fast_stream(), media_type="text/event-stream")

        # Agent streaming path
        async def agent_stream():
            try:
                # Tactical reliability path: run the agent call in a worker thread
                # and stream status/result events without hanging the request.
                yield sse("status", {"stage": "planning"})
                response = await anyio.to_thread.run_sync(
                    session.run_agent,
                    request.dataset_id,
                    request.message,
                    thread_id,
                )
                yield sse("status", {"stage": "executing"})
                yield sse("result", response)
                yield sse("done", {"run_id": response["run_id"]})
            except GraphRecursionError as exc:
                LOGGER.warning(
                    "Graph recursion limit hit during stream (thread=%s dataset=%s): %s",
                    thread_id,
                    request.dataset_id,
                    exc,
                )
                yield sse(
                    "error",
                    {
                        "type": "AGENT_RECURSION_LIMIT",
                        "message": (
                            "I hit an internal reasoning limit while refining that request. "
                            "Please retry with explicit fields/tables."
                        ),
                    },
                )
                yield sse("done", {})
            except KeyError as exc:
                yield sse("error", {"type": "NOT_FOUND", "message": str(exc)})
                yield sse("done", {})
            except Exception as exc:  # pragma: no cover
                LOGGER.exception(
                    "Unhandled stream error (thread=%s dataset=%s)",
                    thread_id,
                    request.dataset_id,
                )
                yield sse("error", {"type": "AGENT_ERROR", "message": str(exc)})
                yield sse("done", {})

        return StreamingResponse(agent_stream(), media_type="text/event-stream")

    @app.post("/runs", response_model=ChatResponse)
    async def submit_run(request: RunSubmitRequest):
        registry = load_registry(settings.datasets_dir)
        try:
            dataset = get_dataset_by_id(registry, request.dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        run_id = str(uuid.uuid4())
        created_at = _utc_now_iso()
        query_mode = request.query_type
        compiled_sql: Optional[str] = None
        plan_json = request.plan_json
        python_code_val = request.python_code

        files = [
            {"name": e["name"], "path": f"/data/{e['path']}"}
            for e in dataset.get("files", [])
        ]

        if request.query_type == "sql":
            if not request.sql:
                raise HTTPException(
                    status_code=400, detail="sql is required for query_type=sql"
                )
            sql = normalize_sql_for_dataset(request.sql, request.dataset_id)
            compiled_sql = sql
            policy_error = validate_sql_policy(sql)
            if policy_error:
                # Rejected — persist and return
                result_payload: Dict[str, Any] = {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {"type": "SQL_POLICY_VIOLATION", "message": policy_error},
                }
                status = "rejected"
            else:
                payload = {
                    "dataset_id": dataset["id"],
                    "files": files,
                    "query_type": "sql",
                    "timeout_seconds": settings.run_timeout_seconds,
                    "max_rows": settings.max_rows,
                    "max_output_bytes": settings.max_output_bytes,
                    "sql": sql,
                }
                raw = sandbox_executor.submit_run(payload, query_type="sql")
                runner_result = raw.get("result", raw)
                status = _map_runner_status(runner_result)
                result_payload = {
                    "columns": runner_result.get("columns", []),
                    "rows": runner_result.get("rows", []),
                    "row_count": runner_result.get("row_count", 0),
                    "exec_time_ms": runner_result.get("exec_time_ms", 0),
                    "error": runner_result.get("error"),
                }

        elif request.query_type == "python":
            if not request.python_code:
                raise HTTPException(
                    status_code=400,
                    detail="python_code is required for query_type=python",
                )
            if not settings.enable_python_execution:
                result_payload = {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {
                        "type": "FEATURE_DISABLED",
                        "message": "Python execution mode is disabled.",
                    },
                }
                status = "rejected"
            else:
                payload = {
                    "dataset_id": dataset["id"],
                    "files": files,
                    "query_type": "python",
                    "timeout_seconds": settings.run_timeout_seconds,
                    "max_rows": settings.max_rows,
                    "max_output_bytes": settings.max_output_bytes,
                    "python_code": request.python_code,
                }
                raw = sandbox_executor.submit_run(payload, query_type="python")
                runner_result = raw.get("result", raw)
                status = _map_runner_status(runner_result)
                result_payload = {
                    "columns": runner_result.get("columns", []),
                    "rows": runner_result.get("rows", []),
                    "row_count": runner_result.get("row_count", 0),
                    "exec_time_ms": runner_result.get("exec_time_ms", 0),
                    "error": runner_result.get("error"),
                }

        else:  # plan
            if not request.plan_json:
                raise HTTPException(
                    status_code=400, detail="plan_json is required for query_type=plan"
                )
            from .models.query_plan import QueryPlan

            try:
                plan = QueryPlan.model_validate(
                    {**request.plan_json, "dataset_id": request.dataset_id}
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            plan_json = plan.model_dump()
            compiled_sql = compiler.compile(plan)
            sql = normalize_sql_for_dataset(compiled_sql, request.dataset_id)
            compiled_sql = sql

            policy_error = validate_sql_policy(sql)
            if policy_error:
                result_payload = {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "error": {"type": "SQL_POLICY_VIOLATION", "message": policy_error},
                }
                status = "rejected"
            else:
                payload = {
                    "dataset_id": dataset["id"],
                    "files": files,
                    "query_type": "sql",
                    "timeout_seconds": settings.run_timeout_seconds,
                    "max_rows": settings.max_rows,
                    "max_output_bytes": settings.max_output_bytes,
                    "sql": sql,
                }
                raw = sandbox_executor.submit_run(payload, query_type="sql")
                runner_result = raw.get("result", raw)
                status = _map_runner_status(runner_result)
                result_payload = {
                    "columns": runner_result.get("columns", []),
                    "rows": runner_result.get("rows", []),
                    "row_count": runner_result.get("row_count", 0),
                    "exec_time_ms": runner_result.get("exec_time_ms", 0),
                    "error": runner_result.get("error"),
                }

        response = ChatResponse(
            assistant_message="Run submitted and executed.",
            run_id=run_id,
            status=(
                status
                if status in {"succeeded", "failed", "rejected", "timed_out"}
                else "failed"
            ),
            result=result_payload,
            details={
                "dataset_id": request.dataset_id,
                "query_mode": query_mode,
                "plan_json": plan_json,
                "compiled_sql": compiled_sql,
                "python_code": python_code_val,
            },
        )

        insert_capsule(
            settings.capsule_db_path,
            {
                "run_id": run_id,
                "created_at": created_at,
                "dataset_id": request.dataset_id,
                "dataset_version_hash": dataset.get("version_hash"),
                "question": None,
                "query_mode": query_mode,
                "plan_json": plan_json,
                "compiled_sql": compiled_sql,
                "python_code": python_code_val,
                "status": response.status,
                "result_json": response.result,
                "error_json": response.result.get("error"),
                "exec_time_ms": response.result.get("exec_time_ms", 0),
            },
        )
        return response

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        capsule = get_capsule(settings.capsule_db_path, run_id)
        if not capsule:
            raise HTTPException(status_code=404, detail="Run not found")
        return capsule

    @app.get("/runs/{run_id}/status")
    async def get_run_status(run_id: str):
        capsule = get_capsule(settings.capsule_db_path, run_id)
        if not capsule:
            return {"run_id": run_id, "status": "not_found"}
        return {"run_id": run_id, "status": capsule.get("status")}

    @app.get("/threads/{thread_id}/messages")
    async def get_thread_messages(thread_id: str, limit: int = 50):
        capped = min(max(limit, 1), 200)
        return {
            "thread_id": thread_id,
            "messages": message_store.get_messages(
                thread_id=thread_id,
                limit=capped,
            ),
        }

    _STATIC_DIR = Path(__file__).resolve().parent / "static"
    _INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/")
    async def home():
        return HTMLResponse(content=_INDEX_HTML)

    return app


# Module-level app instance for uvicorn; guarded so test imports don't fail
# when no LLM key is configured or provider packages are incompatible.
try:
    app = create_app()
except Exception:  # pragma: no cover
    app = None  # type: ignore[assignment]
