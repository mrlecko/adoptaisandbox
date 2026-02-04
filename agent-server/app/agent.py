"""
LangGraph agent: build, run, stream, and capsule extraction.

Key design points:
- create_react_agent wraps the LLM + tools into a runnable graph.
- _extract_capsule_data filters result_json to execution tools only
  (execute_sql, execute_query_plan, execute_python).
- AgentSession owns history ↔ messages conversion and persistence.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from .datasets import get_dataset_by_id, load_registry
from .storage import MessageStore
from .storage.capsules import get_capsule, insert_capsule
from .tools import EXECUTION_TOOL_NAMES

LOGGER = logging.getLogger("csv-analyst-agent-server")

SYSTEM_PROMPT_TEMPLATE = (
    "You are a careful data analyst assistant. You have access to tools that let you "
    "discover datasets and run queries against them.\n\n"
    "Rules:\n"
    "- Default to execute_sql for data questions.\n"
    "- Use execute_query_plan only when you want structured query plans.\n"
    "- Use execute_python only when the user explicitly asks for pandas/Python.\n"
    "- If a user asks for any value derived from the dataset (count, top, max/min, trend, date, aggregate), "
    "you MUST execute an execution tool before answering.\n"
    "- Prefer using exact table and column names from schema context/tool output. Do not invent table names.\n"
    "- Never describe a query you would run without actually running it.\n"
    "- If execute_sql returns a missing table/column error, call get_dataset_schema(dataset_id) and retry once with corrected SQL.\n"
    "- Do not claim data is unavailable unless schema inspection confirms required fields are absent.\n"
    "- After you receive a successful execution result that answers the user, STOP calling tools and provide the final answer.\n"
    "- For follow-up requests that refine prior results (e.g., 'those again but with name'), reuse prior run context and execute one focused query.\n"
    "- For greetings, capability questions, or schema questions you can answer "
    "from tool output — reply in text without executing a query.\n"
    "- Always keep result sets to <= {max_rows} rows.\n"
    "- Never suggest or generate DDL/DML (DROP, INSERT, etc.).\n"
)


def build_agent(
    tools: List[Any],
    max_rows: int,
    llm: BaseChatModel,
) -> Any:
    """Return a LangGraph react agent graph."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(max_rows=max_rows)
    return create_react_agent(model=llm, tools=tools, prompt=system_prompt)


def _history_to_messages(history: List[Dict[str, Any]]) -> List[BaseMessage]:
    """Convert stored {role, content} dicts to LangChain message objects."""
    out: List[BaseMessage] = []
    for item in history:
        role = item.get("role", "user")
        content = str(item.get("content", ""))
        if role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _extract_capsule_data(
    messages: List[BaseMessage],
    dataset_id: str,
    question: str,
) -> Dict[str, Any]:
    """Walk the agent's output messages and build capsule metadata.

    Only ToolMessages whose tool_call_id maps to an *execution* tool name
    (execute_sql, execute_query_plan, execute_python) contribute to result_json.
    """
    # Phase 1: build tool_call_id → tool_name mapping from AIMessages
    tool_call_map: Dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls"):
            for tc in msg.tool_calls or []:
                tool_call_map[tc["id"]] = tc["name"]

    # Phase 2: walk messages collecting data
    result_json: Optional[Dict[str, Any]] = None
    compiled_sql: Optional[str] = None
    plan_json: Optional[Dict[str, Any]] = None
    python_code: Optional[str] = None
    query_mode = "chat"
    last_error: Optional[Dict[str, Any]] = None
    assistant_message = ""

    for msg in messages:
        if isinstance(msg, AIMessage):
            # Track tool inputs for extraction
            for tc in getattr(msg, "tool_calls", None) or []:
                name = tc.get("name", "")
                inp = tc.get("args", tc.get("input", {}))
                if name == "execute_sql":
                    compiled_sql = inp.get("sql")
                    query_mode = "sql"
                elif name == "execute_query_plan":
                    plan_json_raw = inp.get("plan")
                    if plan_json_raw:
                        try:
                            plan_json = (
                                json.loads(plan_json_raw)
                                if isinstance(plan_json_raw, str)
                                else plan_json_raw
                            )
                        except (json.JSONDecodeError, TypeError):
                            plan_json = None
                    query_mode = "plan"
                elif name == "execute_python":
                    python_code = inp.get("python_code")
                    query_mode = "python"

            # Track the last meaningful text response (no tool_calls)
            if msg.content and not (getattr(msg, "tool_calls", None)):
                assistant_message = str(msg.content)

        elif isinstance(msg, ToolMessage):
            tool_name = tool_call_map.get(msg.tool_call_id, "")
            if tool_name in EXECUTION_TOOL_NAMES:
                try:
                    parsed = (
                        json.loads(msg.content)
                        if isinstance(msg.content, str)
                        else msg.content
                    )
                    result_json = parsed
                    if parsed.get("status") == "error":
                        last_error = parsed.get("error")
                except (json.JSONDecodeError, TypeError):
                    pass

    # Derive status
    if query_mode == "chat":
        status = "succeeded"
    elif result_json is not None:
        if result_json.get("status") == "success":
            status = "succeeded"
        elif result_json.get("status") == "timeout" or (
            last_error and last_error.get("type") == "TIMEOUT"
        ):
            status = "timed_out"
        elif last_error and last_error.get("type") in (
            "SQL_POLICY_VIOLATION",
            "FEATURE_DISABLED",
        ):
            status = "rejected"
        else:
            status = "failed"
    else:
        status = "succeeded"  # chat-only, no execution

    return {
        "dataset_id": dataset_id,
        "question": question,
        "query_mode": query_mode,
        "compiled_sql": compiled_sql,
        "plan_json": plan_json,
        "python_code": python_code,
        "status": status,
        "result_json": result_json,
        "assistant_message": assistant_message or "Done.",
    }


def _last_successful_run_context(
    history: List[Dict[str, Any]],
    dataset_id: str,
    capsule_db_path: str,
) -> Optional[str]:
    """Build compact follow-up context from the latest successful run in-thread."""
    seen_run_ids: set[str] = set()
    for msg in reversed(history):
        run_id = msg.get("run_id")
        if not run_id or run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)
        capsule = get_capsule(capsule_db_path, run_id)
        if not capsule:
            continue
        if capsule.get("dataset_id") != dataset_id:
            continue
        if capsule.get("status") != "succeeded":
            continue

        query_mode = capsule.get("query_mode")
        if query_mode not in {"sql", "plan", "python"}:
            continue

        result_json = capsule.get("result_json") or {}
        columns = result_json.get("columns") or []
        row_count = result_json.get("row_count", 0)
        compiled_sql = (capsule.get("compiled_sql") or "").strip()
        python_code = (capsule.get("python_code") or "").strip()

        sql_snippet = compiled_sql[:500] + ("..." if len(compiled_sql) > 500 else "")
        py_snippet = python_code[:500] + ("..." if len(python_code) > 500 else "")
        cols_preview = columns[:15]
        return (
            "Previous successful run context:\n"
            f"- query_mode: {query_mode}\n"
            f"- row_count: {row_count}\n"
            f"- columns: {json.dumps(cols_preview)}\n"
            f"- compiled_sql: {sql_snippet or 'N/A'}\n"
            f"- python_code: {py_snippet or 'N/A'}\n"
            "Use this only when the current user request is a follow-up that refers to prior results."
        )
    return None


def _dataset_schema_context(dataset_id: str, datasets_dir: str) -> Optional[str]:
    """Build compact schema grounding context for the current dataset."""
    try:
        registry = load_registry(datasets_dir)
        dataset = get_dataset_by_id(registry, dataset_id)
    except Exception:
        return None

    lines = [
        "Dataset schema context (use these exact table/column names):",
        f"- dataset_id: {dataset_id}",
    ]
    for file_info in dataset.get("files", []):
        raw_name = str(file_info.get("name", "")).strip()
        table_name = Path(raw_name).stem if raw_name else raw_name
        schema = file_info.get("schema", {}) or {}
        columns = list(schema.keys())
        preview = ", ".join(columns[:30]) if columns else "(schema unavailable)"
        lines.append(f"- table {table_name}: {preview}")

    return "\n".join(lines)


class AgentSession:
    """Stateful session that wires history, invocation, persistence."""

    def __init__(
        self,
        agent_graph: Any,
        message_store: MessageStore,
        capsule_db_path: str,
        history_window: int = 12,
        datasets_dir: Optional[str] = None,
    ):
        self.agent_graph = agent_graph
        self.message_store = message_store
        self.capsule_db_path = capsule_db_path
        self.history_window = max(1, history_window)
        self.datasets_dir = datasets_dir

    def run_agent(
        self,
        dataset_id: str,
        message: str,
        thread_id: str,
    ) -> Dict[str, Any]:
        """Invoke the agent synchronously, persist results, return ChatResponse dict."""
        run_id = str(uuid.uuid4())

        # Load + persist user message
        history = self.message_store.get_messages(
            thread_id=thread_id,
            limit=self.history_window,
        )
        self.message_store.append_message(
            thread_id=thread_id,
            role="user",
            content=message,
            dataset_id=dataset_id,
            run_id=run_id,
        )

        # Build input messages: history + new user message
        input_messages = _history_to_messages(history)
        if self.datasets_dir:
            schema_context = _dataset_schema_context(dataset_id, self.datasets_dir)
            if schema_context:
                input_messages.append(SystemMessage(content=schema_context))
        prior_context = _last_successful_run_context(
            history,
            dataset_id,
            self.capsule_db_path,
        )
        if prior_context:
            input_messages.append(SystemMessage(content=prior_context))
        input_messages.append(HumanMessage(content=message))

        # Invoke agent
        try:
            result = self.agent_graph.invoke({"messages": input_messages})
        except GraphRecursionError as exc:
            LOGGER.warning(
                "Agent recursion limit hit (thread=%s, dataset=%s): %s",
                thread_id,
                dataset_id,
                exc,
            )
            assistant_message = (
                "I hit an internal reasoning limit while refining that request. "
                "Please rephrase it with explicit fields/tables (for example: "
                "'top 10 products by revenue including inventory.name')."
            )
            result_payload = {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "error": {
                    "type": "AGENT_RECURSION_LIMIT",
                    "message": "Agent reached recursion limit before completion.",
                },
            }
            self.message_store.append_message(
                thread_id=thread_id,
                role="assistant",
                content=assistant_message,
                dataset_id=dataset_id,
                run_id=run_id,
            )
            insert_capsule(
                self.capsule_db_path,
                {
                    "run_id": run_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "dataset_id": dataset_id,
                    "dataset_version_hash": None,
                    "question": message,
                    "query_mode": "chat",
                    "plan_json": None,
                    "compiled_sql": None,
                    "python_code": None,
                    "status": "failed",
                    "result_json": result_payload,
                    "error_json": result_payload.get("error"),
                    "exec_time_ms": 0,
                },
            )
            return {
                "assistant_message": assistant_message,
                "run_id": run_id,
                "thread_id": thread_id,
                "status": "failed",
                "result": result_payload,
                "details": {
                    "dataset_id": dataset_id,
                    "query_mode": "chat",
                    "plan_json": None,
                    "compiled_sql": None,
                    "python_code": None,
                },
            }
        output_messages: List[BaseMessage] = result.get("messages", [])

        # Extract capsule data
        capsule_data = _extract_capsule_data(output_messages, dataset_id, message)

        # Persist assistant message
        self.message_store.append_message(
            thread_id=thread_id,
            role="assistant",
            content=capsule_data["assistant_message"],
            dataset_id=dataset_id,
            run_id=run_id,
        )

        # Build result payload (same shape as ChatResponse)
        result_payload = capsule_data.get("result_json") or {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 0,
            "error": None,
        }

        # Persist capsule
        insert_capsule(
            self.capsule_db_path,
            {
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "dataset_id": dataset_id,
                "dataset_version_hash": None,
                "question": message,
                "query_mode": capsule_data["query_mode"],
                "plan_json": capsule_data["plan_json"],
                "compiled_sql": capsule_data["compiled_sql"],
                "python_code": capsule_data["python_code"],
                "status": capsule_data["status"],
                "result_json": result_payload,
                "error_json": result_payload.get("error"),
                "exec_time_ms": result_payload.get("exec_time_ms", 0),
            },
        )

        return {
            "assistant_message": capsule_data["assistant_message"],
            "run_id": run_id,
            "thread_id": thread_id,
            "status": capsule_data["status"],
            "result": {
                "columns": result_payload.get("columns", []),
                "rows": result_payload.get("rows", []),
                "row_count": result_payload.get("row_count", 0),
                "exec_time_ms": result_payload.get("exec_time_ms", 0),
                "error": result_payload.get("error"),
            },
            "details": {
                "dataset_id": dataset_id,
                "query_mode": capsule_data["query_mode"],
                "plan_json": capsule_data["plan_json"],
                "compiled_sql": capsule_data["compiled_sql"],
                "python_code": capsule_data["python_code"],
            },
        }

    async def stream_agent(
        self,
        dataset_id: str,
        message: str,
        thread_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Async generator yielding SSE-compatible event dicts.

        Yields dicts with keys: event (str), data (dict).
        Events: token, tool_call, tool_result, result, done.
        """
        run_id = str(uuid.uuid4())

        history = self.message_store.get_messages(
            thread_id=thread_id,
            limit=self.history_window,
        )
        self.message_store.append_message(
            thread_id=thread_id,
            role="user",
            content=message,
            dataset_id=dataset_id,
            run_id=run_id,
        )

        input_messages = _history_to_messages(history)
        if self.datasets_dir:
            schema_context = _dataset_schema_context(dataset_id, self.datasets_dir)
            if schema_context:
                input_messages.append(SystemMessage(content=schema_context))
        prior_context = _last_successful_run_context(
            history,
            dataset_id,
            self.capsule_db_path,
        )
        if prior_context:
            input_messages.append(SystemMessage(content=prior_context))
        input_messages.append(HumanMessage(content=message))

        all_messages: List[BaseMessage] = []

        try:
            # Stream events via astream_events v2
            async for event in self.agent_graph.astream_events(
                {"messages": input_messages}, version="v2"
            ):
                kind = event.get("event", "")
                data = event.get("data", {})

                if kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {
                            "event": "token",
                            "data": {"content": str(chunk.content)},
                        }

                elif kind == "on_tool_start":
                    yield {
                        "event": "tool_call",
                        "data": {
                            "name": data.get("input", {}).get(
                                "name", event.get("name", "")
                            ),
                            "input": data.get("input", {}),
                        },
                    }

                elif kind == "on_tool_end":
                    yield {
                        "event": "tool_result",
                        "data": {"output": data.get("output", "")},
                    }

                elif kind == "on_chain_end":
                    output = data.get("output", {})
                    if isinstance(output, dict) and isinstance(
                        output.get("messages"), list
                    ):
                        all_messages = output["messages"]

        except GraphRecursionError as exc:
            LOGGER.warning(
                "Agent recursion limit hit during stream (thread=%s, dataset=%s): %s",
                thread_id,
                dataset_id,
                exc,
            )
            assistant_message = (
                "I hit an internal reasoning limit while refining that request. "
                "Please rephrase it with explicit fields/tables (for example: "
                "'top 10 products by revenue including inventory.name')."
            )
            self.message_store.append_message(
                thread_id=thread_id,
                role="assistant",
                content=assistant_message,
                dataset_id=dataset_id,
                run_id=run_id,
            )
            insert_capsule(
                self.capsule_db_path,
                {
                    "run_id": run_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "dataset_id": dataset_id,
                    "dataset_version_hash": None,
                    "question": message,
                    "query_mode": "chat",
                    "plan_json": None,
                    "compiled_sql": None,
                    "python_code": None,
                    "status": "failed",
                    "result_json": {
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "exec_time_ms": 0,
                        "error": {
                            "type": "AGENT_RECURSION_LIMIT",
                            "message": "Agent reached recursion limit before completion.",
                        },
                    },
                    "error_json": {
                        "type": "AGENT_RECURSION_LIMIT",
                        "message": "Agent reached recursion limit before completion.",
                    },
                    "exec_time_ms": 0,
                },
            )
            yield {
                "event": "error",
                "data": {
                    "type": "AGENT_RECURSION_LIMIT",
                    "message": (
                        "I hit an internal reasoning limit while refining that request. "
                        "Please retry with explicit fields/tables."
                    ),
                },
            }
            yield {"event": "done", "data": {"run_id": run_id}}
            return

        # Extract capsule and persist
        capsule_data = _extract_capsule_data(all_messages, dataset_id, message)

        self.message_store.append_message(
            thread_id=thread_id,
            role="assistant",
            content=capsule_data["assistant_message"],
            dataset_id=dataset_id,
            run_id=run_id,
        )

        result_payload = capsule_data.get("result_json") or {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 0,
            "error": None,
        }

        insert_capsule(
            self.capsule_db_path,
            {
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "dataset_id": dataset_id,
                "dataset_version_hash": None,
                "question": message,
                "query_mode": capsule_data["query_mode"],
                "plan_json": capsule_data["plan_json"],
                "compiled_sql": capsule_data["compiled_sql"],
                "python_code": capsule_data["python_code"],
                "status": capsule_data["status"],
                "result_json": result_payload,
                "error_json": result_payload.get("error"),
                "exec_time_ms": result_payload.get("exec_time_ms", 0),
            },
        )

        chat_response = {
            "assistant_message": capsule_data["assistant_message"],
            "run_id": run_id,
            "thread_id": thread_id,
            "status": capsule_data["status"],
            "result": {
                "columns": result_payload.get("columns", []),
                "rows": result_payload.get("rows", []),
                "row_count": result_payload.get("row_count", 0),
                "exec_time_ms": result_payload.get("exec_time_ms", 0),
                "error": result_payload.get("error"),
            },
            "details": {
                "dataset_id": dataset_id,
                "query_mode": capsule_data["query_mode"],
                "plan_json": capsule_data["plan_json"],
                "compiled_sql": capsule_data["compiled_sql"],
                "python_code": capsule_data["python_code"],
            },
        }

        yield {"event": "result", "data": chat_response}
        yield {"event": "done", "data": {"run_id": run_id}}
