# AGENTIFY UPGRADE

Comprehensive plan to rewrite the agent-server from a single-turn LLM request-router
into a true LangChain/LangGraph tool-calling agent with genuine multi-step reasoning,
real streaming, and proper tool definitions.

---

## Table of Contents

1. [Current State — What Is Wrong](#1-current-state--what-is-wrong)
2. [Target Architecture](#2-target-architecture)
3. [New File Layout](#3-new-file-layout)
4. [Dependency Changes](#4-dependency-changes)
5. [New Module: `llm.py` — LLM Factory](#5-new-module-llmpy--llm-factory)
6. [New Module: `tools.py` — Tool Definitions](#6-new-module-toolspy--tool-definitions)
7. [New Module: `agent.py` — LangGraph Agent](#7-new-module-agentpy--langgraph-agent)
8. [main.py Rewrite](#8-mainpy-rewrite)
9. [Executor Wiring Fix](#9-executor-wiring-fix)
10. [Streaming Redesign](#10-streaming-redesign)
11. [Memory & Thread Persistence](#11-memory--thread-persistence)
12. [Capsule Persistence](#12-capsule-persistence)
13. [Fast-Path Bypass (Explicit `SQL:` / `PYTHON:`)](#13-fast-path-bypass-explicit-sql--python)
14. [Phased Migration Plan](#14-phased-migration-plan)
15. [Test Strategy](#15-test-strategy)
16. [Rollback Plan](#16-rollback-plan)

---

## 1. Current State — What Is Wrong

### 1.1 Not an agent — it is a request router

`process_chat` (main.py:1027) makes routing decisions with hardcoded `if/elif` logic.
The LLM is called at most twice (primary structured-output attempt + SQL rescue fallback).
It never sees query results. It never iterates. It cannot decide to run a second query
based on what the first one returned.

```
Current flow:
  message → if/elif routing → LLM (0 or 1 call) → deterministic execute → template response
                                        │
                                        └─ rescue LLM call if first parse fails

Target flow:
  message → agent loop → LLM sees tools + history → calls tool → result fed back
                              ↑                                        │
                              └────────── loop continues ◄─────────────┘
                                          until LLM produces final text
```

### 1.2 LangChain usage is superficial

What is actually used from LangChain:
- `ChatPromptTemplate` — prompt construction
- `ChatOpenAI` / `ChatAnthropic` — LLM clients
- `.with_structured_output(PydanticModel)` — forces JSON output
- `prompt | model` (LCEL pipe) — single-step chain

What is NOT used (but should be, for an agent):
- No `@tool` decorator or `Tool`/`StructuredTool` registration
- No agent (`create_react_agent`, `AgentExecutor`, or LangGraph graph)
- No tool-calling by the LLM (the LLM outputs a static JSON payload; it does not
  invoke tools, observe results, or reason about them)
- No LangChain memory or conversation management
- No streaming primitives (`astream_events`, token-level streaming)

### 1.3 Duplicated code (five distinct duplications)

| Duplication | Locations | Lines |
|---|---|---|
| LLM provider selection (OpenAI → Anthropic fallback) | `_generate_with_langchain`, `_generate_python_with_langchain`, `_generate_sql_rescue_with_langchain` | 411–437, 611–638, 724–750 |
| Output coercion (unwrap `parsed`/`output`/`model_dump`/code-block) | `_coerce_agent_draft`, `_coerce_sql_rescue_draft`, `_coerce_python_draft` | 453–566 |
| Docker subprocess command construction | `_default_runner_executor` in main.py, `DockerExecutor.submit_run` in docker_executor.py | main.py:255–287, docker_executor.py:68–100 |
| Runner payload assembly | `_default_runner_executor` (inline), `_build_runner_payload` (extracted but only called by microsandbox path) | main.py:233–253, main.py:322–352 |
| Empty-result error response literal | Repeated 6+ times in `process_chat` and tool functions | Throughout 1105–1333 |

### 1.4 Streaming does not actually stream

`/chat/stream` (main.py:1537) calls `process_chat` **synchronously**. The `status_cb`
collects stage names into a list. The async generator then yields all collected statuses
followed by the final result in a single burst. The client receives everything at once.

### 1.5 DockerExecutor class is bypassed on the docker path

`factory.py` already handles `provider == "docker"` and returns a `DockerExecutor`
instance (factory.py:27–34). But `create_app` (main.py:880) short-circuits:

```python
if settings.sandbox_provider == "docker":
    default_runner_callable = _default_runner_executor   # ← inline, bypasses factory
```

`DockerExecutor` is only ever instantiated when the provider is NOT docker — which
never happens through the factory because the factory's docker branch is dead code
from main.py's perspective.

### 1.6 One-line wrapper functions that add nothing

`_validate_sql_policy`, `_normalize_sql_for_dataset`, `_init_capsule_db`,
`_insert_capsule`, `_get_capsule` (main.py:203–220) each forward a single call to
the already-imported function. No additional logic. Pure indirection.

### 1.7 Result summarisation is a hardcoded template

`_summarize_result_for_user` (main.py:784) generates the assistant's response using
`if/elif` on column counts and row counts. The LLM plays no role in crafting the
response the user sees. Scalar results get "The result is {value}." Multi-row results
get "I found N rows. First row: ...". The LLM never sees the data.

---

## 2. Target Architecture

### 2.1 Conceptual diagram

```
┌──────────┐  HTTP POST   ┌─────────────────────────────────────────┐
│  Browser │ ──────────►  │  FastAPI Routes (main.py)               │
│    UI    │  SSE stream  │    /chat        → agent.run_agent()     │
│          │ ◄────────── │    /chat/stream → agent.stream_agent()  │
└──────────┘              │    /runs        → tools directly        │
                          └───────────┬─────────────────────────────┘
                                      │
                          ┌───────────▼─────────────────────────────┐
                          │  agent.py — LangGraph React Agent       │
                          │                                         │
                          │  ┌─────────┐    ┌────────────┐          │
                          │  │   LLM   │◄──►│ Tool Node  │          │
                          │  │  node   │    │ (executes  │          │
                          │  │         │    │  tools)    │          │
                          │  └────┬────┘    └─────┬──────┘          │
                          │       │ final         │ tool results    │
                          │       ▼ response      ▼ fed back        │
                          │  ┌─────────┐    ┌────────────┐          │
                          │  │ capsule │    │ MessageStore│          │
                          │  │ persist │    │   sync     │          │
                          │  └─────────┘    └────────────┘          │
                          └─────────────────────────────────────────┘
                                      │
                          ┌───────────▼─────────────────────────────┐
                          │  tools.py — Tool Definitions            │
                          │    • list_datasets                      │
                          │    • get_dataset_schema                 │
                          │    • execute_sql                        │
                          │    • execute_query_plan                 │
                          │    • execute_python                     │
                          └───────────┬─────────────────────────────┘
                                      │
                          ┌───────────▼─────────────────────────────┐
                          │  executors/  (unchanged interface)      │
                          │    DockerExecutor / MicroSandboxExecutor│
                          └─────────────────────────────────────────┘
```

### 2.2 Agent loop mechanics

LangGraph's `create_react_agent` implements this loop automatically:

1. User message enters as a `HumanMessage` in the agent's message list.
2. **LLM node**: The LLM receives all messages (system prompt + history + user message)
   and the tool schemas. It either:
   - Returns an `AIMessage` with one or more `tool_calls` → go to step 3.
   - Returns an `AIMessage` with only text (no tool calls) → this is the final
     response. Loop ends.
3. **Tool node**: Each `tool_call` is dispatched to the matching tool function.
   The tool executes (validate SQL, run sandbox, etc.) and returns a result string.
   A `ToolMessage` containing the result is appended to the message list.
4. Control returns to step 2 (LLM node). The LLM now sees the tool results and
   decides whether to call more tools or produce a final response.

This is genuine multi-step reasoning. The LLM can:
- Call `get_dataset_schema` first, then `execute_sql` with a query informed by the schema.
- See a query error, correct it, and retry.
- Run one query, examine the results, and run a follow-up query.
- Produce a response that references the actual data it observed.

### 2.3 Tool contract

Each tool is a plain Python function decorated with `@tool`. The decorator extracts
the function's docstring as the tool's description and the type-annotated parameters
as the tool's input schema. Both are sent to the LLM so it knows what tools exist,
what they do, and what arguments they take.

Tools return strings. Tool results are inserted into the conversation as `ToolMessage`
objects. The LLM reads them as text.

Tools do NOT return structured Pydantic objects to the LLM. They return human-readable
strings (JSON-formatted where appropriate). This keeps the LLM's view of results
simple and robust.

### 2.4 Streaming model

LangGraph's `astream_events(version="v2")` yields granular events as they happen:

| LangGraph event | What it means | SSE event we emit |
|---|---|---|
| `on_chat_model_stream` | LLM is generating tokens | `token` |
| `on_tool_start` | A tool is about to run | `tool_call` (name + input) |
| `on_tool_end` | A tool finished | `tool_result` (output) |
| `on_chain_end` (root) | The agent loop completed | `result` (full ChatResponse) |

This replaces the current fake streaming (collect-then-burst) with genuine progressive
delivery. The UI can show the LLM's thinking, tool invocations as they happen, and
stream the final response text token by token.

### 2.5 Memory model

Thread history is loaded from `MessageStore` (SQLite) at the start of each request.
Rows are converted from `{role, content}` dicts into LangChain `BaseMessage` objects
and prepended to the agent's input message list. After the agent completes, the final
user message and the assistant's final text response are written back to `MessageStore`.
Intermediate tool-call / tool-result messages are NOT persisted to `MessageStore`
(they are ephemeral per-request reasoning steps) but ARE captured in the run capsule
for audit purposes.

---

## 3. New File Layout

```
agent-server/app/
├── main.py              # FastAPI app + routes ONLY. No LLM, no tools, no generation logic.
├── llm.py               # NEW: single LLM factory function. Replaces 3× duplicated provider blocks.
├── tools.py             # NEW: all @tool definitions. Replaces tool_* functions in main.py.
├── agent.py             # NEW: LangGraph agent graph, run_agent(), stream_agent().
├── datasets.py          # KEEP unchanged.
├── executors/           # KEEP unchanged. Factory now used for ALL providers including docker.
│   ├── __init__.py
│   ├── base.py
│   ├── docker_executor.py
│   ├── microsandbox_executor.py
│   └── factory.py
├── models/              # KEEP unchanged.
│   ├── __init__.py
│   └── query_plan.py
├── storage/             # KEEP unchanged.
│   ├── __init__.py
│   ├── capsules.py
│   └── messages.py
├── validators/          # KEEP unchanged.
│   ├── compiler.py
│   └── sql_policy.py
└── static/
    └── index.html       # UI changes tracked separately; see Section 10.4.
```

### What gets deleted from main.py

| Lines (current) | Symbol | Reason |
|---|---|---|
| 160–170 | `_is_python_intent` | Becomes irrelevant — the LLM decides intent |
| 203–220 | `_validate_sql_policy` wrapper, `_normalize_sql_for_dataset` wrapper, capsule wrappers | One-line pass-throughs; call originals directly |
| 223–319 | `_default_runner_executor` | Replaced by `DockerExecutor` via factory |
| 322–352 | `_build_runner_payload` | Moves into `tools.py` |
| 355–363 | `_fallback_plan` | Irrelevant — LLM generates plans itself |
| 366–450 | `_generate_with_langchain` | Replaced by agent loop |
| 453–566 | `_coerce_agent_draft`, `_coerce_sql_rescue_draft`, `_coerce_python_draft` | Replaced by agent loop (structured output is handled by tool invocation, not coercion) |
| 569–652 | `_generate_python_with_langchain` | Replaced by agent loop |
| 655–677 | `_heuristic_python_from_message` | Replaced by agent loop |
| 680–764 | `_generate_sql_rescue_with_langchain` | Replaced by agent loop |
| 767–777 | `_format_history_text` | Replaced by LangChain message objects |
| 780–826 | `_summarize_result_for_user` | Replaced by LLM-generated response |
| 117–158 | `AgentDraft`, `SqlRescueDraft`, `PythonDraft` models | Replaced by tool input schemas |
| 929–1025 | `tool_list_datasets` … `tool_get_run_status` | Move to `tools.py` as real tools |
| 1027–1437 | `process_chat` | Replaced by `agent.run_agent()` |

### What stays in main.py

- `Settings` model (all config)
- `ChatRequest`, `ChatResponse`, `StreamRequest`, `RunSubmitRequest` (API schemas)
- `AppServices` dataclass (wires dependencies)
- `create_app()` — slimmed to: env loading, executor factory, tool creation, agent
  construction, route registration
- All route handlers (`/healthz`, `/datasets`, `/datasets/{id}/schema`, `/chat`,
  `/chat/stream`, `/runs`, `/runs/{id}`, `/runs/{id}/status`,
  `/threads/{id}/messages`, `/`)

---

## 4. Dependency Changes

### Add to `agent-server/requirements.txt`

```
langgraph==0.1.63          # Agent graph runtime. Compatible with langchain-core 0.1.x.
langgraph-checkpoint==0.0.22  # Checkpoint support (needed by create_react_agent).
```

### Version compatibility note

Current pins: `langchain-core==0.1.52`, `langchain==0.1.20`.
`langgraph 0.1.x` is compatible with `langchain-core >= 0.1.40`.
If integration tests surface incompatibilities, bump `langchain-core` to `0.1.58`
and `langchain` to `0.1.30` — both are backward-compatible within the 0.1 line.

### No removals

`langchain`, `langchain-core`, `langchain-openai`, `langchain-anthropic` all stay.
They are used by LangGraph internally and by our LLM factory.

---

## 5. New Module: `llm.py` — LLM Factory

Consolidates the provider-selection logic that is currently duplicated three times.

```python
# agent-server/app/llm.py

from __future__ import annotations
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

if TYPE_CHECKING:
    from .main import Settings


def create_llm(settings: Settings) -> BaseChatModel:
    """Instantiate the configured LLM provider.

    Resolution order when llm_provider == "auto":
        1. OpenAI  (if OPENAI_API_KEY is set)
        2. Anthropic (if ANTHROPIC_API_KEY is set)

    Raises ValueError if no provider can be initialised.
    """
    if settings.llm_provider in ("auto", "openai") and settings.openai_api_key:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key,
        )

    if settings.llm_provider in ("auto", "anthropic") and settings.anthropic_api_key:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.anthropic_model,
            temperature=0,
            api_key=settings.anthropic_api_key,
        )

    raise ValueError(
        "No LLM provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY, "
        "and optionally LLM_PROVIDER=openai|anthropic."
    )
```

**All three** `_generate_*_with_langchain` functions and their duplicated provider
blocks are deleted. `llm.py` is the single source of truth.

---

## 6. New Module: `tools.py` — Tool Definitions

### 6.1 Injection pattern

Tools need access to runtime dependencies: the sandbox executor, the QueryPlan
compiler, dataset registry path, and policy functions. These are not globals.

Solution: a **factory function** that captures dependencies in closure scope and
returns the list of decorated tool functions.

```python
def create_tools(
    executor: Executor,
    compiler: QueryPlanCompiler,
    datasets_dir: str,
    max_rows: int,
    max_output_bytes: int,
    enable_python_execution: bool,
) -> list:
    # ... tool definitions here, closed over the parameters above ...
    return [list_datasets, get_dataset_schema, execute_sql, execute_query_plan, execute_python]
```

`create_app()` calls `create_tools(...)` once at startup and passes the resulting list
to the agent constructor.

### 6.2 Tool definitions — complete specifications

Each tool has:
- A **name** (the function name) — this is what the LLM emits in `tool_calls`.
- A **docstring** — sent to the LLM as the tool description. Must be precise.
- **Type-annotated parameters** — become the JSON schema the LLM fills in.
- A **return value** (str) — becomes the `ToolMessage` content.

```python
# agent-server/app/tools.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool

from .datasets import get_dataset_by_id, load_registry
from .executors.base import Executor
from .validators.compiler import QueryPlanCompiler
from .validators.sql_policy import normalize_sql_for_dataset, validate_sql_policy


def create_tools(
    executor: Executor,
    compiler: QueryPlanCompiler,
    datasets_dir: str,
    max_rows: int,
    max_output_bytes: int,
    enable_python_execution: bool,
) -> list:
    """Factory: creates all tool functions with dependencies bound via closure."""

    # ── helpers ──────────────────────────────────────────────────────────────
    def _load_reg() -> Dict[str, Any]:
        return load_registry(datasets_dir)

    def _get_ds(dataset_id: str) -> Dict[str, Any]:
        return get_dataset_by_id(_load_reg(), dataset_id)

    def _sample_rows(csv_path: Path, n: int = 5) -> list[dict[str, Any]]:
        import csv as _csv
        rows: list[dict[str, Any]] = []
        if not csv_path.exists():
            return rows
        with csv_path.open(newline="", encoding="utf-8") as f:
            for i, row in enumerate(_csv.DictReader(f)):
                if i >= n:
                    break
                rows.append(row)
        return rows

    def _run_sandbox(dataset: Dict[str, Any], sql: str, query_type: str = "sql",
                     python_code: str | None = None) -> Dict[str, Any]:
        """Build payload and submit to executor. Returns raw runner response."""
        files = [{"name": e["name"], "path": f"/data/{e['path']}"} for e in dataset.get("files", [])]
        payload: Dict[str, Any] = {
            "dataset_id": dataset["id"],
            "files": files,
            "query_type": query_type,
            "timeout_seconds": 10,          # driven by executor defaults
            "max_rows": max_rows,
            "max_output_bytes": max_output_bytes,
        }
        if query_type == "python":
            payload["python_code"] = python_code or ""
        else:
            payload["sql"] = sql
        return executor.submit_run(payload, query_type=query_type).get("result", {})

    # ── tool: list_datasets ──────────────────────────────────────────────────
    @tool
    def list_datasets() -> str:
        """List all available CSV datasets with their names, descriptions,
        and example prompts. Call this first if you are unsure which dataset
        the user is asking about."""
        reg = _load_reg()
        summary = [
            {
                "id": ds["id"],
                "name": ds["name"],
                "description": ds.get("description", ""),
                "example_prompts": ds.get("prompts", [])[:3],
            }
            for ds in reg.get("datasets", [])
        ]
        return json.dumps(summary, indent=2)

    # ── tool: get_dataset_schema ─────────────────────────────────────────────
    @tool
    def get_dataset_schema(dataset_id: str) -> str:
        """Retrieve the full schema (column names and types) and up to 3 sample
        rows for every CSV file in a dataset.  Call this before writing a query
        so you know the exact column names and data formats.

        Args:
            dataset_id: Identifier of the dataset (e.g. 'ecommerce').
        """
        ds = _get_ds(dataset_id)
        files = []
        for f in ds.get("files", []):
            abs_path = Path(datasets_dir) / f["path"]
            files.append({
                "name": f["name"],
                "table_name": Path(f["name"]).stem,   # this is how to reference it in SQL
                "schema": f.get("schema", {}),
                "sample_rows": _sample_rows(abs_path, 3),
            })
        return json.dumps({"dataset_id": ds["id"], "files": files}, indent=2)

    # ── tool: execute_sql ────────────────────────────────────────────────────
    @tool
    def execute_sql(dataset_id: str, sql: str) -> str:
        """Execute a SQL query against a CSV dataset using DuckDB.

        Rules enforced before execution:
        - Query must be a single SELECT or WITH statement.
        - DROP, DELETE, INSERT, UPDATE, CREATE, ALTER, ATTACH and other
          mutating/system operations are blocked.
        - Results are capped at the configured row limit.

        If the query violates policy the tool returns an error — do NOT retry
        the same query.  If the query fails due to a syntax or schema error,
        examine the error message and correct the SQL before retrying.

        Args:
            dataset_id: Dataset to query (e.g. 'ecommerce').
            sql: A DuckDB-compatible SELECT or WITH query.  Reference tables by
                 their CSV filename without the .csv extension
                 (e.g. SELECT * FROM orders LIMIT 10).
        """
        try:
            ds = _get_ds(dataset_id)
        except KeyError as e:
            return json.dumps({"error": str(e)})

        sql = normalize_sql_for_dataset(sql, dataset_id)
        policy_err = validate_sql_policy(sql)
        if policy_err:
            return json.dumps({"error": "SQL_POLICY_VIOLATION", "message": policy_err})

        result = _run_sandbox(ds, sql, query_type="sql")
        return json.dumps(result, default=str)

    # ── tool: execute_query_plan ─────────────────────────────────────────────
    @tool
    def execute_query_plan(dataset_id: str, plan: dict) -> str:
        """Execute a structured QueryPlan against a dataset.  The plan is
        compiled to SQL deterministically, then executed.  Use this when you
        want precise, reproducible queries with explicit filters and
        aggregations.

        The plan object must conform to:
            {
                "dataset_id": str,
                "table": str,                          # e.g. "orders"
                "select": [                            # columns or aggregations
                    {"column": "order_id"}             # plain column
                    {"function": "count", "column": "*", "alias": "total"}  # aggregation
                ],
                "filters": [                           # optional
                    {"column": "status", "operator": "=", "value": "completed"}
                ],
                "group_by": ["status"],                # optional
                "order_by": [{"column": "total", "direction": "desc"}],  # optional
                "limit": 50                            # optional, default 200
            }

        Args:
            dataset_id: Dataset to query.
            plan: A QueryPlan JSON object as described above.
        """
        try:
            ds = _get_ds(dataset_id)
        except KeyError as e:
            return json.dumps({"error": str(e)})

        from .models.query_plan import QueryPlan
        try:
            query_plan = QueryPlan.model_validate({"dataset_id": dataset_id, **plan})
        except Exception as e:
            return json.dumps({"error": "PLAN_VALIDATION_ERROR", "message": str(e)})

        compiled_sql = compiler.compile(query_plan)
        # Re-use execute_sql's validation + execution (call the inner helper directly)
        compiled_sql = normalize_sql_for_dataset(compiled_sql, dataset_id)
        policy_err = validate_sql_policy(compiled_sql)
        if policy_err:
            return json.dumps({"error": "SQL_POLICY_VIOLATION", "message": policy_err,
                               "compiled_sql": compiled_sql})

        result = _run_sandbox(ds, compiled_sql, query_type="sql")
        result["compiled_sql"] = compiled_sql
        result["plan"] = plan
        return json.dumps(result, default=str)

    # ── tool: execute_python ─────────────────────────────────────────────────
    @tool
    def execute_python(dataset_id: str, python_code: str) -> str:
        """Execute Python / pandas code against a dataset in an isolated
        sandbox.  Each CSV file is loaded as a pandas DataFrame named after
        the file (without .csv), e.g. ``orders``, ``tickets``.

        To return results, assign a DataFrame or list to ``result_df``.
        Output is capped at the configured row limit.

        Security: the sandbox has no network access, no filesystem write
        access outside /tmp, and a strict import policy.  Attempts to import
        ``subprocess``, ``os``, ``socket``, or similar modules will be rejected
        at runtime.

        Args:
            dataset_id: Dataset to use.
            python_code: Python source code to execute.  Must set ``result_df``.
        """
        if not enable_python_execution:
            return json.dumps({"error": "FEATURE_DISABLED",
                               "message": "Python execution is currently disabled."})
        try:
            ds = _get_ds(dataset_id)
        except KeyError as e:
            return json.dumps({"error": str(e)})

        result = _run_sandbox(ds, "", query_type="python", python_code=python_code)
        return json.dumps(result, default=str)

    # ── return all tools ─────────────────────────────────────────────────────
    return [list_datasets, get_dataset_schema, execute_sql, execute_query_plan, execute_python]
```

### 6.3 Tool design decisions

| Decision | Rationale |
|---|---|
| Tools return JSON strings, not dicts | The LLM reads tool results as text. JSON strings are unambiguous and round-trip cleanly through `ToolMessage`. |
| `execute_sql` does its own policy validation | The tool is the last gate before the sandbox. Validation must happen here regardless of how the tool was invoked. |
| `execute_query_plan` compiles then delegates to the same sandbox path as `execute_sql` | Single execution path. No divergence. |
| `get_dataset_schema` includes `table_name` field | Tells the LLM the exact identifier to use in SQL — removes a common source of LLM errors. |
| `list_datasets` is a tool, not baked into the prompt | Keeps the system prompt short. The LLM discovers datasets on demand. Works correctly if datasets are added or removed at runtime. |

---

## 7. New Module: `agent.py` — LangGraph Agent

### 7.1 State

LangGraph's `create_react_agent` uses a built-in state schema: a `messages` list of
`BaseMessage` objects. No custom state class is needed for this use case.

### 7.2 System prompt

The system prompt is injected as the first message (`SystemMessage`) in the agent's
input. It describes the agent's role and behavioural constraints.

```python
SYSTEM_PROMPT = """You are a helpful data analyst assistant. You help users explore
and query CSV datasets using SQL or Python/pandas.

You have access to tools for discovering datasets, examining schemas, and executing
queries. Follow this workflow:

1. If the user asks about available data, call list_datasets.
2. Before writing a query, call get_dataset_schema to confirm column names and formats.
   Getting column names wrong is the most common source of query failures.
3. For straightforward questions, use execute_sql with a SELECT query.
4. For complex transformations that SQL cannot express cleanly, use execute_python.
5. For precise, reproducible queries with explicit filters, use execute_query_plan.
6. If a query fails, read the error carefully, correct the issue, and retry.
   Do not retry the exact same query.
7. After executing a query, summarise the results clearly for the user.
   Reference specific values from the data in your response.

Constraints:
- All SQL queries must be SELECT or WITH statements. No mutations.
- Results are capped at {max_rows} rows. Use LIMIT or .head() accordingly.
- Python code runs in a sandbox with no network or filesystem access.
- Never fabricate data. Only report what the tools return.
"""
```

`{max_rows}` is interpolated at agent construction time from `Settings.max_rows`.

### 7.3 Graph construction

```python
# agent-server/app/agent.py

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from .llm import create_llm
from .storage.capsules import insert_capsule
from .storage import MessageStore


SYSTEM_PROMPT_TEMPLATE = """You are a helpful data analyst assistant. You help users
explore and query CSV datasets using SQL or Python/pandas.

You have access to tools for discovering datasets, examining schemas, and executing
queries. Follow this workflow:

1. If the user asks about available data, call list_datasets.
2. Before writing a query, call get_dataset_schema to confirm column names and formats.
   Getting column names wrong is the most common source of query failures.
3. For straightforward questions, use execute_sql with a SELECT query.
4. For complex transformations that SQL cannot express cleanly, use execute_python.
5. For precise, reproducible queries with explicit filters, use execute_query_plan.
6. If a query fails, read the error carefully, correct the issue, and retry.
   Do not retry the exact same query.
7. After executing a query, summarise the results clearly for the user.
   Reference specific values from the data in your response.

Constraints:
- All SQL queries must be SELECT or WITH statements. No mutations.
- Results are capped at {max_rows} rows. Use LIMIT or .head() accordingly.
- Python code runs in a sandbox with no network or filesystem access.
- Never fabricate data. Only report what the tools return.
"""


def build_agent(tools: list, max_rows: int, llm):
    """Construct the LangGraph react agent."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(max_rows=max_rows)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,           # injected as SystemMessage
    )


# ── history ◄──────────────────────────────────────────────────────────────────
def _history_to_messages(history: List[Dict[str, Any]]) -> List[BaseMessage]:
    """Convert MessageStore rows to LangChain BaseMessage objects."""
    msgs: List[BaseMessage] = []
    for row in history:
        role = row.get("role", "")
        content = row.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
        # tool / system rows in history are skipped — they are ephemeral
    return msgs


# ── capsule extraction ◄──────────────────────────────────────────────────────
def _extract_capsule_data(messages: List[BaseMessage], dataset_id: str, question: str) -> Dict[str, Any]:
    """Walk the agent's final message list and extract audit data for the capsule."""
    query_mode = "chat"          # default if no tools were called
    compiled_sql: Optional[str] = None
    plan_json: Optional[Dict[str, Any]] = None
    python_code: Optional[str] = None
    result_json: Optional[Dict[str, Any]] = None
    error_json: Optional[Dict[str, Any]] = None
    exec_time_ms = 0

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name", "")
                inp = tc.get("input", {})
                if name == "execute_sql":
                    query_mode = "sql"
                    compiled_sql = inp.get("sql")
                elif name == "execute_query_plan":
                    query_mode = "plan"
                    plan_json = inp.get("plan")
                elif name == "execute_python":
                    query_mode = "python"
                    python_code = inp.get("python_code")

        if isinstance(msg, ToolMessage):
            # Last tool result wins for result_json
            try:
                parsed = json.loads(msg.content)
                if "error" in parsed and parsed.get("status") != "success":
                    error_json = {"type": parsed.get("error"), "message": parsed.get("message", "")}
                result_json = parsed
                exec_time_ms = parsed.get("exec_time_ms", 0)
            except (json.JSONDecodeError, TypeError):
                pass

    # Final assistant text
    assistant_message = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            assistant_message = msg.content
            break

    status = "succeeded" if (result_json and result_json.get("status") == "success") else (
        "rejected" if error_json else "succeeded" if query_mode == "chat" else "failed"
    )

    return {
        "assistant_message": assistant_message,
        "status": status,
        "query_mode": query_mode,
        "compiled_sql": compiled_sql,
        "plan_json": plan_json,
        "python_code": python_code,
        "result_json": result_json or {},
        "error_json": error_json,
        "exec_time_ms": exec_time_ms,
    }


# ── public API ◄───────────────────────────────────────────────────────────────

class AgentSession:
    """Holds the constructed agent and all dependencies for run/stream."""

    def __init__(self, agent, message_store: MessageStore, capsule_db_path: str):
        self.agent = agent
        self.message_store = message_store
        self.capsule_db_path = capsule_db_path

    # ── synchronous run ───────────────────────────────────────────────────────
    def run_agent(
        self,
        *,
        dataset_id: str,
        message: str,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the agent to completion. Returns a ChatResponse-compatible dict."""
        thread_id = thread_id or f"thread-{uuid.uuid4()}"
        run_id   = str(uuid.uuid4())

        # 1. Load thread history, persist incoming user message
        history = self.message_store.get_messages(thread_id=thread_id, limit=12)
        self.message_store.append_message(
            thread_id=thread_id, role="user", content=message,
            dataset_id=dataset_id, run_id=run_id,
        )

        # 2. Build input messages: system (handled by agent) + history + new user msg
        input_messages: List[BaseMessage] = _history_to_messages(history)
        input_messages.append(HumanMessage(content=f"[dataset: {dataset_id}]\n{message}"))

        # 3. Invoke agent
        final_state = self.agent.invoke({"messages": input_messages})
        all_messages: List[BaseMessage] = final_state["messages"]

        # 4. Extract results
        capsule_data = _extract_capsule_data(all_messages, dataset_id, message)

        # 5. Persist assistant message to thread
        self.message_store.append_message(
            thread_id=thread_id, role="assistant",
            content=capsule_data["assistant_message"],
            dataset_id=dataset_id, run_id=run_id,
        )

        # 6. Persist capsule
        insert_capsule(self.capsule_db_path, {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_id": dataset_id,
            "question": message,
            **capsule_data,
        })

        # 7. Return response
        result = capsule_data.get("result_json") or {}
        return {
            "assistant_message": capsule_data["assistant_message"],
            "run_id": run_id,
            "thread_id": thread_id,
            "status": capsule_data["status"],
            "result": {
                "columns":     result.get("columns", []),
                "rows":        result.get("rows", []),
                "row_count":   result.get("row_count", 0),
                "exec_time_ms": result.get("exec_time_ms", 0),
                "error":       capsule_data.get("error_json"),
            },
            "details": {
                "dataset_id":   dataset_id,
                "query_mode":   capsule_data["query_mode"],
                "plan_json":    capsule_data["plan_json"],
                "compiled_sql": capsule_data["compiled_sql"],
                "python_code":  capsule_data["python_code"],
            },
        }

    # ── streaming run ─────────────────────────────────────────────────────────
    async def stream_agent(
        self,
        *,
        dataset_id: str,
        message: str,
        thread_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Async generator that yields SSE-ready event dicts as the agent runs.

        Yielded event shapes:
            {"event": "token",       "data": {"text": "..."}}
            {"event": "tool_call",   "data": {"name": "execute_sql", "input": {...}}}
            {"event": "tool_result", "data": {"name": "execute_sql", "output": "..."}}
            {"event": "result",      "data": <full ChatResponse dict>}
            {"event": "done",        "data": {"run_id": "..."}}
        """
        thread_id = thread_id or f"thread-{uuid.uuid4()}"
        run_id   = str(uuid.uuid4())

        # 1. History + persist user message (same as run_agent)
        history = self.message_store.get_messages(thread_id=thread_id, limit=12)
        self.message_store.append_message(
            thread_id=thread_id, role="user", content=message,
            dataset_id=dataset_id, run_id=run_id,
        )
        input_messages = _history_to_messages(history)
        input_messages.append(HumanMessage(content=f"[dataset: {dataset_id}]\n{message}"))

        # 2. Stream events via astream_events
        final_messages: List[BaseMessage] = []
        async for event in self.agent.astream_events(
            {"messages": input_messages}, version="v2"
        ):
            kind = event.get("event", "")
            name = event.get("name", "")

            if kind == "on_chat_model_stream":
                # Token-level streaming from LLM
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {"event": "token", "data": {"text": str(chunk.content)}}

            elif kind == "on_tool_start":
                # Tool is about to execute
                inp = event.get("data", {}).get("input", {})
                yield {"event": "tool_call", "data": {"name": name, "input": inp}}

            elif kind == "on_tool_end":
                # Tool finished
                output = event.get("data", {}).get("output", "")
                yield {"event": "tool_result", "data": {"name": name, "output": str(output)}}

            elif kind == "on_chain_end" and name == "":
                # Root chain completed — final state available
                final_messages = event.get("data", {}).get("output", {}).get("messages", [])

        # 3. Post-stream: extract, persist, yield final result (same as run_agent steps 4-7)
        capsule_data = _extract_capsule_data(final_messages, dataset_id, message)
        self.message_store.append_message(
            thread_id=thread_id, role="assistant",
            content=capsule_data["assistant_message"],
            dataset_id=dataset_id, run_id=run_id,
        )
        insert_capsule(self.capsule_db_path, {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset_id": dataset_id,
            "question": message,
            **capsule_data,
        })
        result = capsule_data.get("result_json") or {}
        response = {
            "assistant_message": capsule_data["assistant_message"],
            "run_id": run_id,
            "thread_id": thread_id,
            "status": capsule_data["status"],
            "result": {
                "columns":     result.get("columns", []),
                "rows":        result.get("rows", []),
                "row_count":   result.get("row_count", 0),
                "exec_time_ms": result.get("exec_time_ms", 0),
                "error":       capsule_data.get("error_json"),
            },
            "details": {
                "dataset_id":   dataset_id,
                "query_mode":   capsule_data["query_mode"],
                "plan_json":    capsule_data["plan_json"],
                "compiled_sql": capsule_data["compiled_sql"],
                "python_code":  capsule_data["python_code"],
            },
        }
        yield {"event": "result", "data": response}
        yield {"event": "done",   "data": {"run_id": run_id}}
```

### 7.4 Why `create_react_agent` and not a hand-rolled graph

`create_react_agent` implements the standard ReAct (Reasoning + Acting) loop.
It handles:
- Binding tools to the LLM
- Dispatching tool calls to a `ToolNode`
- Looping until the LLM stops calling tools
- Proper error propagation from tools back to the LLM

A hand-rolled graph would only be needed if we required custom loop logic (e.g.,
a maximum tool-call budget, custom retry logic, or interleaved human-in-the-loop
steps). None of those apply here. Use `create_react_agent`.

---

## 8. main.py Rewrite

### 8.1 Skeleton after rewrite

```python
"""
FastAPI routes for CSV Analyst Chat.

This module owns HTTP concerns only:
- Request/response models
- Route registration
- SSE formatting

All agent logic lives in agent.py.  All tools live in tools.py.
"""

from __future__ import annotations
import json, os, uuid
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

# Internal
from .datasets import get_dataset_by_id, load_registry
from .executors import create_sandbox_executor
from .llm import create_llm
from .tools import create_tools
from .agent import AgentSession, build_agent
from .storage import create_message_store
from .storage.capsules import get_capsule, init_capsule_db

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


# ── Settings (unchanged) ──────────────────────────────────────────────────────
class Settings(BaseModel):
    # ... (keep as-is) ...


# ── API models (keep ChatRequest, ChatResponse, StreamRequest, RunSubmitRequest) ─
# ... (unchanged) ...


# ── App factory ───────────────────────────────────────────────────────────────
def create_app(settings: Optional[Settings] = None) -> FastAPI:
    # env loading (keep)
    # Settings construction from env (keep)

    # 1. Executor — NOW uses factory for ALL providers (docker included)
    executor = create_sandbox_executor(
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

    # 2. Tools
    tools = create_tools(
        executor=executor,
        compiler=QueryPlanCompiler(),
        datasets_dir=settings.datasets_dir,
        max_rows=settings.max_rows,
        max_output_bytes=settings.max_output_bytes,
        enable_python_execution=settings.enable_python_execution,
    )

    # 3. LLM  (may raise ValueError if no key configured — that's intentional)
    llm = create_llm(settings)

    # 4. Agent
    agent_graph = build_agent(tools=tools, max_rows=settings.max_rows, llm=llm)

    # 5. Storage
    init_capsule_db(settings.capsule_db_path)
    message_store = create_message_store(settings.storage_provider, settings.capsule_db_path)
    message_store.initialize()

    # 6. Session (ties agent + storage together)
    session = AgentSession(
        agent=agent_graph,
        message_store=message_store,
        capsule_db_path=settings.capsule_db_path,
    )

    # 7. FastAPI app + routes
    app = FastAPI(title="CSV Analyst Agent Server")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/datasets")
    async def list_datasets_route():
        reg = load_registry(settings.datasets_dir)
        return {"datasets": [
            {"id": ds["id"], "name": ds["name"],
             "description": ds.get("description"),
             "prompts": ds.get("prompts", []),
             "version_hash": ds.get("version_hash")}
            for ds in reg.get("datasets", [])
        ]}

    @app.get("/datasets/{dataset_id}/schema")
    async def dataset_schema(dataset_id: str):
        # ... (keep existing logic, but call load_registry + get_dataset_by_id directly) ...

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        try:
            result = session.run_agent(
                dataset_id=request.dataset_id,
                message=request.message,
                thread_id=request.thread_id,
            )
            return ChatResponse(**result)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/chat/stream")
    async def chat_stream(request: StreamRequest):
        async def sse_stream():
            async for evt in session.stream_agent(
                dataset_id=request.dataset_id,
                message=request.message,
                thread_id=request.thread_id,
            ):
                yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'])}\n\n"
        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    @app.post("/runs", response_model=ChatResponse)
    async def submit_run(request: RunSubmitRequest):
        # Direct execution without LLM reasoning.
        # Calls tools directly via the same executor.
        # ... (see Section 13 for implementation) ...

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        capsule = get_capsule(settings.capsule_db_path, run_id)
        if not capsule:
            raise HTTPException(status_code=404, detail="Run not found")
        return capsule

    @app.get("/runs/{run_id}/status")
    async def get_run_status(run_id: str):
        capsule = get_capsule(settings.capsule_db_path, run_id)
        return {"run_id": run_id, "status": capsule["status"] if capsule else "not_found"}

    @app.get("/threads/{thread_id}/messages")
    async def get_thread_messages(thread_id: str, limit: int = 50):
        capped = min(max(limit, 1), 200)
        return {
            "thread_id": thread_id,
            "messages": message_store.get_messages(thread_id=thread_id, limit=capped),
        }

    _STATIC_DIR = Path(__file__).resolve().parent / "static"

    @app.get("/")
    async def home():
        return FileResponse(_STATIC_DIR / "index.html")

    return app


app = create_app()
```

### 8.2 What shrinks

| Before | After |
|---|---|
| ~1597 lines | ~250–300 lines (routes + settings + models only) |
| 3 LLM generation functions | 0 (in `agent.py` via LangGraph) |
| 3 coercion functions | 0 (tool invocation handles this) |
| 6 tool_* functions | 0 (in `tools.py`) |
| 1 massive `process_chat` | 0 (in `agent.py`) |
| 1 inline Docker executor | 0 (factory handles it) |
| 5 one-line wrappers | 0 (call originals directly) |

---

## 9. Executor Wiring Fix

### Current bug

`main.py` line 880 short-circuits the factory for docker:
```python
if settings.sandbox_provider == "docker":
    default_runner_callable = _default_runner_executor   # inline function
```

`factory.py` line 27 already handles docker correctly:
```python
if normalized == "docker":
    return DockerExecutor(...)
```

### Fix

Delete `_default_runner_executor` from main.py entirely. Call `create_sandbox_executor`
unconditionally for all providers. The factory returns `DockerExecutor` or
`MicroSandboxExecutor` based on `settings.sandbox_provider`. Done.

`DockerExecutor.submit_run` is the single Docker execution path from this point forward.

---

## 10. Streaming Redesign

### 10.1 Current problem (restated)

`process_chat` is synchronous. `status_cb` appends to a list. The async generator
yields all collected statuses then the result. Everything arrives in one burst.

### 10.2 How LangGraph streaming works

`agent.astream_events(input, version="v2")` is an async generator that yields events
as they occur inside the agent graph:

- **`on_chat_model_stream`** — emitted per-token as the LLM generates. Contains a
  partial `AIMessage` chunk.
- **`on_tool_start`** — emitted when a tool node begins executing. Contains the tool
  name and input arguments.
- **`on_tool_end`** — emitted when a tool node finishes. Contains the tool output.
- **`on_chain_end`** (root) — emitted once when the full agent loop completes.
  Contains the final state.

These events fire in real time as the agent runs. No collect-then-burst.

### 10.3 New SSE event schema

The UI currently expects `status`, `result`, `done`, `error` events.
The new schema adds richer progressive events:

| Event | When | Payload |
|---|---|---|
| `token` | Each LLM output token | `{"text": "..."}` |
| `tool_call` | Tool is about to run | `{"name": "execute_sql", "input": {"dataset_id": "...", "sql": "..."}}` |
| `tool_result` | Tool finished | `{"name": "execute_sql", "output": "{\"status\":\"success\",...}"}` |
| `result` | Agent loop done | Full `ChatResponse` dict (same shape as `/chat` response) |
| `done` | Stream end | `{"run_id": "..."}` |
| `error` | Unhandled exception | `{"type": "...", "message": "..."}` |

`token` events are new and enable the UI to show the LLM's response character by
character. `tool_call` and `tool_result` replace the old `status` event and give the
UI concrete information about what the agent is doing.

### 10.4 UI changes required

The UI (`static/index.html`) currently handles `status`, `result`, `done`, `error`.
It needs to be updated to:
- Accumulate `token` events into a streaming assistant bubble.
- Optionally display `tool_call` / `tool_result` events as inline activity indicators
  (e.g., a small badge: "Running execute_sql…" → "Done").
- Continue handling `result` and `done` as before.

This is a UI-layer change tracked separately from the agent rewrite. The agent rewrite
can ship first; the UI can be updated incrementally. The `result` event payload shape
is unchanged, so the existing UI will continue to work (it just won't show
`token`/`tool_call`/`tool_result` until updated).

---

## 11. Memory & Thread Persistence

### 11.1 What is stored vs what is ephemeral

| Message type | Stored in MessageStore? | Stored in capsule? | Sent to LLM? |
|---|---|---|---|
| User message | Yes | Yes (as `question`) | Yes |
| History (prior user + assistant) | Already there | No | Yes (as context) |
| AIMessage with tool_calls | No | Implicitly (tool calls extracted) | Yes (generated by LLM) |
| ToolMessage (tool result) | No | Yes (as `result_json`) | Yes (fed back to LLM) |
| Final AIMessage (response text) | Yes | Yes (as `assistant_message`) | Yes (generated by LLM) |

### 11.2 Loading history

`MessageStore.get_messages(thread_id, limit)` returns `[{role, content, ...}, ...]`.
`_history_to_messages()` converts these to `[HumanMessage, AIMessage, ...]`.
These are prepended to the agent's input. The LLM sees prior turns as conversation
context.

### 11.3 Why tool messages are not persisted to MessageStore

Tool messages are reasoning steps within a single agent invocation. They are not
part of the user-visible conversation. Persisting them would bloat the thread history
and confuse the history-loading logic (which currently expects alternating
user/assistant pairs). The capsule captures all tool interactions for audit.

### 11.4 Thread history window

`Settings.thread_history_window` (default 12) controls how many prior messages are
loaded. This is unchanged. The agent sees the N most recent messages as context.

---

## 12. Capsule Persistence

### 12.1 Extraction from agent output

After the agent completes (both `run_agent` and `stream_agent`), `_extract_capsule_data()`
walks the final message list:

- **AIMessages with `tool_calls`** → extract `query_mode`, `compiled_sql`,
  `plan_json`, `python_code` from the tool call inputs.
- **ToolMessages** → parse JSON content to extract `result_json`, `error_json`,
  `exec_time_ms`. Last tool result wins (covers the common case of schema-check →
  query — we want the query result, not the schema).
- **Final AIMessage without tool_calls** → this is `assistant_message`.
- **Status** → derived: `succeeded` if the last tool result has `status: success`,
  `rejected` if there is an error with a policy type, `failed` otherwise. If no
  tools were called (chat-only), status is `succeeded`.

### 12.2 Capsule schema compatibility

The existing `run_capsules` table schema is unchanged. All fields map cleanly:

| Capsule field | Source |
|---|---|
| `run_id` | Generated at entry |
| `dataset_id` | From request |
| `question` | From request (`message`) |
| `query_mode` | Extracted from tool calls |
| `plan_json` | From `execute_query_plan` input |
| `compiled_sql` | From `execute_sql` input (or compiled inside `execute_query_plan`) |
| `python_code` | From `execute_python` input |
| `status` | Derived |
| `result_json` | From last ToolMessage |
| `error_json` | From last ToolMessage if error |
| `exec_time_ms` | From result |

No database migration is required.

---

## 13. Fast-Path Bypass (Explicit `SQL:` / `PYTHON:`)

### 13.1 Rationale

When a user writes `SQL: SELECT * FROM orders LIMIT 5`, they have already written
the query. Routing this through the agent adds an unnecessary LLM round-trip (latency)
and risks the LLM modifying the user's explicit query.

A fast path that directly executes the user's SQL (with validation) and returns
results is strictly better for this case. The same applies to `PYTHON:`.

### 13.2 Implementation

The `/runs` endpoint already serves this purpose — it accepts `query_type` + raw
`sql` or `python_code` and executes directly. The fast path in `/chat` and
`/chat/stream` can detect the prefix, strip it, and delegate to the same execution
path that `/runs` uses, bypassing the agent entirely.

```python
# In the /chat route handler, BEFORE calling session.run_agent():

stripped = request.message.strip()
if stripped.lower().startswith("sql:"):
    sql = stripped.split(":", 1)[1].strip()
    return _execute_direct(session, executor, request, "sql", sql=sql)
if stripped.lower().startswith("python:"):
    code = stripped.split(":", 1)[1].strip()
    return _execute_direct(session, executor, request, "python", python_code=code)
# else: fall through to agent
```

`_execute_direct` validates, runs the sandbox, persists the capsule, and returns
a `ChatResponse`. It does NOT call the LLM at all.

The streaming endpoint does the same prefix check. For fast-path requests, the
stream emits `tool_call` → `tool_result` → `result` → `done` without any `token`
events (there is no LLM involved).

### 13.3 Why not just let the agent handle it

Debatable. Letting the agent handle explicit SQL keeps the architecture cleaner
(one code path). But it adds 1–3 seconds of LLM latency to what should be an
instant operation, and risks the LLM "helpfully" rewriting the user's query.
The fast path is the better tradeoff for a data analysis tool where users iterate
quickly.

---

## 14. Phased Migration Plan

Each phase is a discrete, testable unit. The system should be runnable (with
degraded capability) at the end of every phase. No phase requires a big-bang
cutover.

### Phase A — Dependencies & scaffolding

**Goal**: The project installs and imports cleanly with the new dependencies.

- [ ] Add `langgraph` and `langgraph-checkpoint` to `agent-server/requirements.txt`
- [ ] Create empty `llm.py`, `tools.py`, `agent.py` with module docstrings
- [ ] `pip install` and verify no import errors
- [ ] No functional changes yet. Existing code continues to work.

### Phase B — LLM factory

**Goal**: Consolidate provider selection. Verify both providers work.

- [ ] Implement `llm.py` (`create_llm` function)
- [ ] Write unit test: `test_llm.py` — verify factory returns correct type for each
  provider config, raises `ValueError` when no key is set
- [ ] Do NOT wire it into anything yet. Just the module + tests.

### Phase C — Tool definitions

**Goal**: All five tools are defined, injected, and independently testable.

- [ ] Implement `tools.py` — `create_tools` factory + all 5 tool functions
- [ ] Write unit tests: `test_tools.py` — mock the executor, call each tool,
  verify output shape and error handling
- [ ] Verify `@tool` decorator correctly exposes name, docstring, and input schema
  (print `tool.schema` in a test)
- [ ] Do NOT wire into agent yet.

### Phase D — Agent construction

**Goal**: The agent graph is built and can be invoked with a mock LLM.

- [ ] Implement `agent.py` — `build_agent`, `AgentSession`, `_history_to_messages`,
  `_extract_capsule_data`
- [ ] Write unit test: `test_agent.py` — construct agent with real tools but a
  **mocked LLM** that returns scripted tool calls. Verify:
  - Tool calls are dispatched correctly
  - Tool results are fed back
  - Final response is extracted
  - Capsule data is extracted correctly
- [ ] Do NOT touch main.py yet.

### Phase E — main.py rewire

**Goal**: The FastAPI routes use the new agent. The old code is removed.

- [ ] Rewrite `create_app()` per Section 8
- [ ] Delete all functions listed in Section 3 "What gets deleted"
- [ ] Fix executor wiring (Section 9): remove `_default_runner_executor`, call
  factory unconditionally
- [ ] Implement fast-path bypass (Section 13)
- [ ] Run existing integration tests — they exercise the HTTP endpoints.
  Update assertions where response shapes change.
- [ ] Manual smoke test: start server, hit `/chat` with a simple question.

### Phase F — Streaming

**Goal**: `/chat/stream` delivers events progressively, not in a burst.

- [ ] Update `stream_agent` in `agent.py` to use `astream_events`
- [ ] Update `/chat/stream` route to consume the async generator
- [ ] Write integration test: connect to `/chat/stream`, verify events arrive
  in correct order (`tool_call` before `tool_result` before `result`)
- [ ] Update UI to handle new event types (can be incremental — `result` shape
  is unchanged so existing UI still works)

### Phase G — Memory integration

**Goal**: Thread history is loaded and persisted correctly through the agent.

- [ ] Verify `run_agent` and `stream_agent` load history and persist messages
- [ ] Integration test: send two messages on the same `thread_id`, verify the
  second invocation receives the first message as context (check via
  `/threads/{id}/messages`)
- [ ] Verify capsule persistence end-to-end via `/runs/{run_id}`

### Phase H — Validation & cutover

**Goal**: Everything works end-to-end. The old code is fully gone.

- [ ] Run the full test suite (`make test`)
- [ ] Run golden queries from the use-case specs against each dataset
- [ ] Verify streaming in a browser (open `/`, type a question, watch events)
- [ ] Verify explicit `SQL:` and `PYTHON:` fast paths still work
- [ ] Verify error cases: bad SQL, unknown dataset, missing LLM key
- [ ] Update `CHANGELOG.md`
- [ ] Update `CLAUDE.md` with new module layout and development notes

---

## 15. Test Strategy

### Unit tests (no Docker, no LLM API calls)

| Test file | What it tests |
|---|---|
| `tests/unit/test_llm.py` | `create_llm` — provider selection, error on missing key |
| `tests/unit/test_tools.py` | Each tool function with a mocked executor. Input validation, error paths, output shape |
| `tests/unit/test_agent.py` | Agent loop with mocked LLM. Tool dispatch, result extraction, capsule extraction |
| `tests/unit/test_query_plan.py` | KEEP — unchanged |
| `tests/unit/test_compiler.py` | KEEP — unchanged |

### Integration tests (Docker required, no LLM API calls)

| Test file | What it tests |
|---|---|
| `tests/integration/test_agent_server.py` | Full HTTP round-trips against a running FastAPI app with a mocked LLM. Covers `/chat`, `/chat/stream`, `/runs`, `/threads`. |
| `tests/integration/test_docker_executor.py` | KEEP — unchanged |
| `tests/integration/test_microsandbox_executor.py` | KEEP — unchanged |

### Mocking the LLM

For unit and integration tests, the LLM is replaced with a deterministic mock:

```python
class MockLLM(BaseChatModel):
    """Returns pre-scripted AIMessages with tool_calls or text."""
    responses: list  # queue of AIMessage objects

    def _generate(self, messages, **kwargs):
        msg = self.responses.pop(0)
        return ChatGeneration(message=msg)
```

This lets us test the agent loop, tool dispatch, streaming, and capsule extraction
without hitting any API. The mock can be configured per test to return different
sequences of tool calls.

### What the golden-query tests verify

Each use-case spec defines 6 golden queries per dataset. An integration test sends
each golden query through `/chat` (with a real LLM if `OPENAI_API_KEY` or
`ANTHROPIC_API_KEY` is set, or skipped otherwise) and asserts:
- Status is `succeeded`
- `row_count > 0`
- `columns` contains expected column names
- No `error` in result

---

## 16. Rollback Plan

Each phase leaves the system in a runnable state. Rollback strategy per phase:

| Phase | Rollback |
|---|---|
| A | Remove the two new deps from requirements.txt, delete empty stub files. |
| B | Delete `llm.py` and its test. Nothing else references it yet. |
| C | Delete `tools.py` and its test. Nothing else references it yet. |
| D | Delete `agent.py` and its test. Nothing else references it yet. |
| E | This is the big one. **Git stash or branch before starting.** If `/chat` is broken after rewire, revert main.py from the previous commit. Phases A–D artifacts (llm.py, tools.py, agent.py) can coexist with the old main.py — they are not imported until main.py references them. |
| F | Revert `stream_agent` to the synchronous `run_agent` + collect-and-burst pattern from the pre-F commit. The `/chat/stream` route can fall back to calling `run_agent` and yielding all events at once. |
| G | Memory loading/persistence failures are non-fatal. If history loading breaks, start the agent with an empty history (empty message list). Persist failures can be caught and logged without failing the request. |
| H | No code changes in this phase. If golden queries fail, the issue is in the agent behaviour (prompt tuning) not in the wiring. Adjust the system prompt or tool docstrings. |

---

*Last updated: 2026-02-02*
*Status: Draft — pending review before implementation begins*
