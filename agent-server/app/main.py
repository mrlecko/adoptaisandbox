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
from time import perf_counter
from typing import Any, Dict, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field, model_validator

from .agent import AgentSession, build_agent
from .datasets import get_dataset_by_id, load_registry
from .executors import create_sandbox_executor
from .llm import create_llm
from .storage import create_message_store
from .storage.capsules import get_capsule, init_capsule_db, insert_capsule
from .tools import create_tools
from .execution import execute_in_sandbox
from .validators.compiler import QueryPlanCompiler
from .validators.sql_policy import normalize_sql_for_dataset, validate_sql_policy

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )
except Exception:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = None
    Histogram = None
    generate_latest = None


LOGGER = logging.getLogger("csv-analyst-agent-server")

HTTP_REQUESTS_TOTAL = (
    Counter(
        "csv_analyst_http_requests_total",
        "Total HTTP requests by method, endpoint, and status code.",
        ["method", "endpoint", "status"],
    )
    if Counter
    else None
)
HTTP_REQUEST_DURATION_SECONDS = (
    Histogram(
        "csv_analyst_http_request_duration_seconds",
        "HTTP request duration in seconds by method and endpoint.",
        ["method", "endpoint"],
    )
    if Histogram
    else None
)
AGENT_TURNS_TOTAL = (
    Counter(
        "csv_analyst_agent_turns_total",
        "Completed chat turns by endpoint, input mode, and status.",
        ["endpoint", "input_mode", "status"],
    )
    if Counter
    else None
)
SANDBOX_RUNS_TOTAL = (
    Counter(
        "csv_analyst_sandbox_runs_total",
        "Sandbox execution attempts by provider, query mode, and status.",
        ["provider", "query_mode", "status"],
    )
    if Counter
    else None
)


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
    sandbox_provider: Literal["docker", "microsandbox", "k8s"] = Field(default="docker")
    msb_server_url: str = Field(default="http://127.0.0.1:5555/api/v1/rpc")
    msb_api_key: str = Field(default="")
    msb_namespace: str = Field(default="default")
    msb_memory_mb: int = Field(default=512)
    msb_cpus: float = Field(default=1.0)
    k8s_namespace: str = Field(default="default")
    k8s_service_account_name: str = Field(default="")
    k8s_image_pull_policy: str = Field(default="IfNotPresent")
    k8s_cpu_limit: str = Field(default="500m")
    k8s_memory_limit: str = Field(default="512Mi")
    k8s_datasets_pvc: str = Field(default="")
    k8s_job_ttl_seconds: int = Field(default=300)
    k8s_poll_interval_seconds: float = Field(default=0.25)
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
        if self.sandbox_provider == "k8s" and not self.k8s_namespace.strip():
            raise ValueError("k8s_namespace is required when sandbox_provider=k8s")
        if self.msb_memory_mb <= 0:
            raise ValueError("msb_memory_mb must be > 0")
        if self.msb_cpus <= 0:
            raise ValueError("msb_cpus must be > 0")
        if self.k8s_job_ttl_seconds < 0:
            raise ValueError("k8s_job_ttl_seconds must be >= 0")
        if self.k8s_poll_interval_seconds <= 0:
            raise ValueError("k8s_poll_interval_seconds must be > 0")
        return self


# ── API Models ────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    dataset_id: str
    message: str
    thread_id: Optional[str] = None
    user_id: Optional[str] = None


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


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _endpoint_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def _metric_inc(counter: Any, **labels: str) -> None:
    if counter is None:
        return
    try:
        counter.labels(**labels).inc()
    except Exception:  # pragma: no cover
        pass


def _metric_observe(histogram: Any, value: float, **labels: str) -> None:
    if histogram is None:
        return
    try:
        histogram.labels(**labels).observe(value)
    except Exception:  # pragma: no cover
        pass


def _log_structured(level: int, event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {"event": event, **fields}
    LOGGER.log(level, json.dumps(payload, default=str, sort_keys=True))


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


def _run_with_mlflow_session_trace(
    *,
    settings: Settings,
    span_name: str,
    user_id: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]],
    trace_input: Optional[Dict[str, Any]],
    fn: Any,
) -> Any:
    """Execute `fn` inside an MLflow trace and attach user/session metadata."""
    if not settings.mlflow_tracking_uri:
        return fn()

    try:
        import mlflow
    except Exception:
        return fn()

    trace_metadata: Dict[str, Any] = {
        "mlflow.trace.user": user_id or "anonymous",
        "mlflow.trace.session": session_id,
    }
    if metadata:
        trace_metadata.update(metadata)

    @mlflow.trace(name=span_name)
    def _wrapped(input_payload: Optional[Dict[str, Any]] = None):
        try:
            mlflow.update_current_trace(metadata=trace_metadata)
        except Exception:
            # Do not fail request handling due to tracing metadata updates.
            pass
        _ = input_payload  # Input is carried for tracing capture only.
        return fn()

    return _wrapped(trace_input)


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
            raw = execute_in_sandbox(
                executor, dataset,
                query_type="sql", sql=sql,
                timeout_seconds=settings.run_timeout_seconds,
                max_rows=settings.max_rows,
                max_output_bytes=settings.max_output_bytes,
            )
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
            raw = execute_in_sandbox(
                executor, dataset,
                query_type="python", python_code=python_code,
                timeout_seconds=settings.run_timeout_seconds,
                max_rows=settings.max_rows,
                max_output_bytes=settings.max_output_bytes,
            )
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
        k8s_namespace=os.getenv("K8S_NAMESPACE", "default"),
        k8s_service_account_name=os.getenv("K8S_SERVICE_ACCOUNT_NAME", ""),
        k8s_image_pull_policy=os.getenv("K8S_IMAGE_PULL_POLICY", "IfNotPresent"),
        k8s_cpu_limit=os.getenv("K8S_CPU_LIMIT", "500m"),
        k8s_memory_limit=os.getenv("K8S_MEMORY_LIMIT", "512Mi"),
        k8s_datasets_pvc=os.getenv("K8S_DATASETS_PVC", ""),
        k8s_job_ttl_seconds=int(os.getenv("K8S_JOB_TTL_SECONDS", "300")),
        k8s_poll_interval_seconds=float(os.getenv("K8S_POLL_INTERVAL_SECONDS", "0.25")),
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
        k8s_namespace=settings.k8s_namespace,
        k8s_service_account_name=settings.k8s_service_account_name,
        k8s_image_pull_policy=settings.k8s_image_pull_policy,
        k8s_cpu_limit=settings.k8s_cpu_limit,
        k8s_memory_limit=settings.k8s_memory_limit,
        k8s_datasets_pvc=settings.k8s_datasets_pvc,
        k8s_job_ttl_seconds=settings.k8s_job_ttl_seconds,
        k8s_poll_interval_seconds=settings.k8s_poll_interval_seconds,
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

    @app.middleware("http")
    async def telemetry_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4()}"
        request.state.request_id = request_id
        start = perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            duration_seconds = perf_counter() - start
            endpoint = _endpoint_label(request)
            _metric_inc(
                HTTP_REQUESTS_TOTAL,
                method=request.method,
                endpoint=endpoint,
                status=str(status_code),
            )
            _metric_observe(
                HTTP_REQUEST_DURATION_SECONDS,
                duration_seconds,
                method=request.method,
                endpoint=endpoint,
            )
            _log_structured(
                logging.ERROR,
                "http.request.exception",
                request_id=request_id,
                thread_id=None,
                run_id=None,
                method=request.method,
                endpoint=endpoint,
                status_code=status_code,
                duration_ms=int(duration_seconds * 1000),
                error=str(exc),
            )
            raise

        duration_seconds = perf_counter() - start
        endpoint = _endpoint_label(request)
        _metric_inc(
            HTTP_REQUESTS_TOTAL,
            method=request.method,
            endpoint=endpoint,
            status=str(status_code),
        )
        _metric_observe(
            HTTP_REQUEST_DURATION_SECONDS,
            duration_seconds,
            method=request.method,
            endpoint=endpoint,
        )
        response.headers["x-request-id"] = request_id
        _log_structured(
            logging.INFO,
            "http.request.completed",
            request_id=request_id,
            thread_id=None,
            run_id=None,
            method=request.method,
            endpoint=endpoint,
            status_code=status_code,
            duration_ms=int(duration_seconds * 1000),
        )
        return response

    # ── routes ──────────────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics():
        if generate_latest is None:
            raise HTTPException(
                status_code=503, detail="Prometheus metrics unavailable"
            )
        return PlainTextResponse(
            content=generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )

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
    async def chat(request: ChatRequest, raw_request: Request):
        msg = request.message.strip()
        thread_id = request.thread_id or f"thread-{uuid.uuid4()}"
        user_id = request.user_id or "anonymous"
        trace_meta = {
            "dataset_id": request.dataset_id,
            "endpoint": "/chat",
            "input_mode": (
                "sql"
                if msg.lower().startswith("sql:")
                else "python" if msg.lower().startswith("python:") else "agent"
            ),
        }
        request_scoped = request.model_copy(update={"thread_id": thread_id})
        req_id = _request_id(raw_request)
        _log_structured(
            logging.INFO,
            "chat.request.received",
            request_id=req_id,
            dataset_id=request.dataset_id,
            thread_id=thread_id,
            input_mode=trace_meta["input_mode"],
        )

        def _finalize(resp: Dict[str, Any]) -> Dict[str, Any]:
            _metric_inc(
                AGENT_TURNS_TOTAL,
                endpoint="/chat",
                input_mode=trace_meta["input_mode"],
                status=str(resp.get("status", "failed")),
            )
            _log_structured(
                logging.INFO,
                "chat.request.completed",
                request_id=req_id,
                dataset_id=request.dataset_id,
                thread_id=resp.get("thread_id", thread_id),
                run_id=resp.get("run_id"),
                input_mode=trace_meta["input_mode"],
                status=resp.get("status"),
            )
            return resp

        # Fast paths: explicit SQL: or PYTHON: prefix
        if msg.lower().startswith("sql:"):
            sql = msg.split(":", 1)[1].strip()
            return _finalize(
                _run_with_mlflow_session_trace(
                    settings=settings,
                    span_name="chat.turn",
                    user_id=user_id,
                    session_id=thread_id,
                    metadata=trace_meta,
                    trace_input={
                        "dataset_id": request.dataset_id,
                        "message": request.message,
                        "thread_id": thread_id,
                        "input_mode": trace_meta["input_mode"],
                    },
                    fn=lambda: _execute_direct(
                        sandbox_executor,
                        settings,
                        message_store,
                        settings.capsule_db_path,
                        request_scoped,
                        "sql",
                        sql=sql,
                    ),
                )
            )
        if msg.lower().startswith("python:"):
            code = msg.split(":", 1)[1].strip()
            return _finalize(
                _run_with_mlflow_session_trace(
                    settings=settings,
                    span_name="chat.turn",
                    user_id=user_id,
                    session_id=thread_id,
                    metadata=trace_meta,
                    trace_input={
                        "dataset_id": request.dataset_id,
                        "message": request.message,
                        "thread_id": thread_id,
                        "input_mode": trace_meta["input_mode"],
                    },
                    fn=lambda: _execute_direct(
                        sandbox_executor,
                        settings,
                        message_store,
                        settings.capsule_db_path,
                        request_scoped,
                        "python",
                        python_code=code,
                    ),
                )
            )
        # Agent path
        try:
            return _finalize(
                _run_with_mlflow_session_trace(
                    settings=settings,
                    span_name="chat.turn",
                    user_id=user_id,
                    session_id=thread_id,
                    metadata=trace_meta,
                    trace_input={
                        "dataset_id": request.dataset_id,
                        "message": request.message,
                        "thread_id": thread_id,
                        "input_mode": trace_meta["input_mode"],
                    },
                    fn=lambda: session.run_agent(
                        request.dataset_id, request.message, thread_id
                    ),
                )
            )
        except GraphRecursionError:
            # Defensive guard; AgentSession already handles this path.
            return _finalize(
                {
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
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/chat/stream")
    async def chat_stream(request: StreamRequest, raw_request: Request):
        def sse(event: str, payload: Dict[str, Any]) -> str:
            # LangGraph event payloads can include non-JSON-native objects
            # (e.g., ToolMessage instances). Convert unknown objects to strings
            # so streaming never fails mid-run.
            return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"

        msg = request.message.strip()
        thread_id = request.thread_id or f"thread-{uuid.uuid4()}"
        user_id = request.user_id or "anonymous"
        trace_meta = {
            "dataset_id": request.dataset_id,
            "endpoint": "/chat/stream",
            "input_mode": (
                "sql"
                if msg.lower().startswith("sql:")
                else "python" if msg.lower().startswith("python:") else "agent"
            ),
        }
        request_scoped = request.model_copy(update={"thread_id": thread_id})
        req_id = _request_id(raw_request)
        _log_structured(
            logging.INFO,
            "chat.stream.request.received",
            request_id=req_id,
            dataset_id=request.dataset_id,
            thread_id=thread_id,
            input_mode=trace_meta["input_mode"],
        )

        # Fast paths emit synthetic events
        if msg.lower().startswith("sql:") or msg.lower().startswith("python:"):

            async def fast_stream():
                if msg.lower().startswith("sql:"):
                    sql = msg.split(":", 1)[1].strip()
                    resp = _run_with_mlflow_session_trace(
                        settings=settings,
                        span_name="chat.stream.turn",
                        user_id=user_id,
                        session_id=thread_id,
                        metadata=trace_meta,
                        trace_input={
                            "dataset_id": request.dataset_id,
                            "message": request.message,
                            "thread_id": thread_id,
                            "input_mode": trace_meta["input_mode"],
                        },
                        fn=lambda: _execute_direct(
                            sandbox_executor,
                            settings,
                            message_store,
                            settings.capsule_db_path,
                            request_scoped,
                            "sql",
                            sql=sql,
                        ),
                    )
                else:
                    code = msg.split(":", 1)[1].strip()
                    resp = _run_with_mlflow_session_trace(
                        settings=settings,
                        span_name="chat.stream.turn",
                        user_id=user_id,
                        session_id=thread_id,
                        metadata=trace_meta,
                        trace_input={
                            "dataset_id": request.dataset_id,
                            "message": request.message,
                            "thread_id": thread_id,
                            "input_mode": trace_meta["input_mode"],
                        },
                        fn=lambda: _execute_direct(
                            sandbox_executor,
                            settings,
                            message_store,
                            settings.capsule_db_path,
                            request_scoped,
                            "python",
                            python_code=code,
                        ),
                    )
                _metric_inc(
                    AGENT_TURNS_TOTAL,
                    endpoint="/chat/stream",
                    input_mode=trace_meta["input_mode"],
                    status=str(resp.get("status", "failed")),
                )
                _log_structured(
                    logging.INFO,
                    "chat.stream.request.completed",
                    request_id=req_id,
                    dataset_id=request.dataset_id,
                    thread_id=resp.get("thread_id", thread_id),
                    run_id=resp.get("run_id"),
                    input_mode=trace_meta["input_mode"],
                    status=resp.get("status"),
                )
                yield sse("status", {"stage": "planning"})
                yield sse("status", {"stage": "executing"})
                yield sse("result", resp)
                yield sse("done", {"run_id": resp["run_id"]})

            return StreamingResponse(fast_stream(), media_type="text/event-stream")

        # Agent streaming path
        async def agent_stream():
            response: Optional[Dict[str, Any]] = None
            try:
                yield sse("status", {"stage": "planning"})
                async for event in session.stream_agent(
                    request.dataset_id, request.message, thread_id
                ):
                    if event["event"] == "result":
                        response = event["data"]
                    yield sse(event["event"], event["data"])
            except KeyError as exc:
                _metric_inc(
                    AGENT_TURNS_TOTAL,
                    endpoint="/chat/stream",
                    input_mode=trace_meta["input_mode"],
                    status="failed",
                )
                yield sse("error", {"type": "NOT_FOUND", "message": str(exc)})
                yield sse("done", {})
                return
            except Exception as exc:  # pragma: no cover
                _metric_inc(
                    AGENT_TURNS_TOTAL,
                    endpoint="/chat/stream",
                    input_mode=trace_meta["input_mode"],
                    status="failed",
                )
                LOGGER.exception(
                    "Unhandled stream error (thread=%s dataset=%s)",
                    thread_id,
                    request.dataset_id,
                )
                yield sse("error", {"type": "AGENT_ERROR", "message": str(exc)})
                yield sse("done", {})
                return

            _metric_inc(
                AGENT_TURNS_TOTAL,
                endpoint="/chat/stream",
                input_mode=trace_meta["input_mode"],
                status=str(response.get("status", "failed")) if response else "failed",
            )
            _log_structured(
                logging.INFO,
                "chat.stream.request.completed",
                request_id=req_id,
                dataset_id=request.dataset_id,
                thread_id=response.get("thread_id", thread_id) if response else thread_id,
                run_id=response.get("run_id") if response else None,
                input_mode=trace_meta["input_mode"],
                status=response.get("status") if response else "failed",
            )

        return StreamingResponse(agent_stream(), media_type="text/event-stream")

    @app.post("/runs", response_model=ChatResponse)
    async def submit_run(request: RunSubmitRequest, raw_request: Request):
        req_id = _request_id(raw_request)
        _log_structured(
            logging.INFO,
            "runs.request.received",
            request_id=req_id,
            dataset_id=request.dataset_id,
            query_type=request.query_type,
        )
        registry = load_registry(settings.datasets_dir)
        try:
            dataset = get_dataset_by_id(registry, request.dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        run_id = str(uuid.uuid4())
        execution_run_id: Optional[str] = None
        created_at = _utc_now_iso()
        query_mode = request.query_type
        compiled_sql: Optional[str] = None
        plan_json = request.plan_json
        python_code_val = request.python_code

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
                raw = execute_in_sandbox(
                    sandbox_executor, dataset,
                    query_type="sql", sql=sql,
                    timeout_seconds=settings.run_timeout_seconds,
                    max_rows=settings.max_rows,
                    max_output_bytes=settings.max_output_bytes,
                )
                execution_run_id = raw.get("run_id")
                runner_result = raw.get("result", raw)
                status = _map_runner_status(runner_result)
                result_payload = {
                    "columns": runner_result.get("columns", []),
                    "rows": runner_result.get("rows", []),
                    "row_count": runner_result.get("row_count", 0),
                    "exec_time_ms": runner_result.get("exec_time_ms", 0),
                    "stdout_trunc": runner_result.get("stdout_trunc", ""),
                    "stderr_trunc": runner_result.get("stderr_trunc", ""),
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
                raw = execute_in_sandbox(
                    sandbox_executor, dataset,
                    query_type="python", python_code=request.python_code,
                    timeout_seconds=settings.run_timeout_seconds,
                    max_rows=settings.max_rows,
                    max_output_bytes=settings.max_output_bytes,
                )
                execution_run_id = raw.get("run_id")
                runner_result = raw.get("result", raw)
                status = _map_runner_status(runner_result)
                result_payload = {
                    "columns": runner_result.get("columns", []),
                    "rows": runner_result.get("rows", []),
                    "row_count": runner_result.get("row_count", 0),
                    "exec_time_ms": runner_result.get("exec_time_ms", 0),
                    "stdout_trunc": runner_result.get("stdout_trunc", ""),
                    "stderr_trunc": runner_result.get("stderr_trunc", ""),
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
                raw = execute_in_sandbox(
                    sandbox_executor, dataset,
                    query_type="sql", sql=sql,
                    timeout_seconds=settings.run_timeout_seconds,
                    max_rows=settings.max_rows,
                    max_output_bytes=settings.max_output_bytes,
                )
                execution_run_id = raw.get("run_id")
                runner_result = raw.get("result", raw)
                status = _map_runner_status(runner_result)
                result_payload = {
                    "columns": runner_result.get("columns", []),
                    "rows": runner_result.get("rows", []),
                    "row_count": runner_result.get("row_count", 0),
                    "exec_time_ms": runner_result.get("exec_time_ms", 0),
                    "stdout_trunc": runner_result.get("stdout_trunc", ""),
                    "stderr_trunc": runner_result.get("stderr_trunc", ""),
                    "error": runner_result.get("error"),
                }

        response = ChatResponse(
            assistant_message="Run submitted and executed.",
            run_id=execution_run_id or run_id,
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
                "run_id": response.run_id,
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
        _metric_inc(
            SANDBOX_RUNS_TOTAL,
            provider=settings.sandbox_provider,
            query_mode=query_mode,
            status=response.status,
        )
        _log_structured(
            logging.INFO,
            "runs.request.completed",
            request_id=req_id,
            run_id=response.run_id,
            dataset_id=request.dataset_id,
            query_mode=query_mode,
            status=response.status,
            sandbox_provider=settings.sandbox_provider,
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


# Module-level app instance for uvicorn. On initialization failure, emit an
# explicit error log and expose a deterministic 500 health response.
try:
    app = create_app()
except Exception as exc:  # pragma: no cover
    logging.basicConfig(level=logging.ERROR)
    LOGGER.exception("Application startup failed: %s", exc)

    app = FastAPI(title="CSV Analyst Agent Server (Startup Error)")

    @app.get("/healthz")
    async def healthz_startup_failure():
        return PlainTextResponse(
            "startup_error: application failed to initialize",
            status_code=500,
        )
