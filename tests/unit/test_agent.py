"""Unit tests for app.agent — capsule extraction, MockLLM, agent loop."""

from pathlib import Path
import json
import sys
import uuid

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphRecursionError

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.agent import (  # noqa: E402
    AgentSession,
    _extract_capsule_data,
    _history_to_messages,
    build_agent,
)
from app.storage import create_message_store  # noqa: E402
from app.storage.capsules import init_capsule_db, insert_capsule  # noqa: E402


class MockLLM(BaseChatModel):
    """Scripted LLM — pops responses from a queue."""

    responses: list

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self.responses.pop(0) if self.responses else AIMessage(content="(empty)")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self  # no-op; tool_calls are scripted


# ── _history_to_messages ──────────────────────────────────────────────────


def test_history_to_messages_converts_roles():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "how are you"},
    ]
    msgs = _history_to_messages(history)
    assert len(msgs) == 3
    assert isinstance(msgs[0], HumanMessage)
    assert isinstance(msgs[1], AIMessage)
    assert isinstance(msgs[2], HumanMessage)
    assert msgs[0].content == "hello"
    assert msgs[1].content == "hi there"


def test_history_to_messages_empty():
    assert _history_to_messages([]) == []


def test_history_to_messages_unknown_role_becomes_human():
    msgs = _history_to_messages([{"role": "system", "content": "x"}])
    assert isinstance(msgs[0], HumanMessage)


# ── _extract_capsule_data ─────────────────────────────────────────────────


def _make_tool_call_id():
    return str(uuid.uuid4())


def test_extract_capsule_chat_only():
    """No tool calls → query_mode=chat, status=succeeded."""
    messages = [
        HumanMessage(content="Hi"),
        AIMessage(content="Hello! I can help you analyze data."),
    ]
    result = _extract_capsule_data(messages, "support", "Hi")
    assert result["query_mode"] == "chat"
    assert result["status"] == "succeeded"
    assert result["result_json"] is None
    assert result["assistant_message"] == "Hello! I can help you analyze data."


def test_extract_capsule_sql_execution():
    """execute_sql tool call → result_json captured, query_mode=sql."""
    tc_id = _make_tool_call_id()
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_sql",
                "args": {"dataset_id": "support", "sql": "SELECT 1 AS n"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content=json.dumps(
            {
                "status": "success",
                "columns": ["n"],
                "rows": [[1]],
                "row_count": 1,
                "compiled_sql": "SELECT 1 AS n",
            }
        ),
        tool_call_id=tc_id,
    )
    final_ai = AIMessage(content="The answer is 1.")

    messages = [HumanMessage(content="run it"), ai_msg, tool_msg, final_ai]
    result = _extract_capsule_data(messages, "support", "run it")

    assert result["query_mode"] == "sql"
    assert result["status"] == "succeeded"
    assert result["result_json"]["rows"] == [[1]]
    assert result["compiled_sql"] == "SELECT 1 AS n"
    assert result["assistant_message"] == "The answer is 1."


def test_extract_capsule_ignores_discovery_tool_results():
    """get_dataset_schema result should NOT become result_json if execute_sql follows."""
    schema_tc_id = _make_tool_call_id()
    exec_tc_id = _make_tool_call_id()

    ai1 = AIMessage(
        content="",
        tool_calls=[
            {
                "id": schema_tc_id,
                "name": "get_dataset_schema",
                "args": {"dataset_id": "support"},
            }
        ],
    )
    tool1 = ToolMessage(
        content=json.dumps({"id": "support", "files": []}),
        tool_call_id=schema_tc_id,
    )
    ai2 = AIMessage(
        content="",
        tool_calls=[
            {
                "id": exec_tc_id,
                "name": "execute_sql",
                "args": {
                    "dataset_id": "support",
                    "sql": "SELECT COUNT(*) AS n FROM tickets",
                },
            }
        ],
    )
    tool2 = ToolMessage(
        content=json.dumps(
            {
                "status": "success",
                "columns": ["n"],
                "rows": [[42]],
                "row_count": 1,
                "compiled_sql": "SELECT COUNT(*) AS n FROM tickets",
            }
        ),
        tool_call_id=exec_tc_id,
    )
    final_ai = AIMessage(content="There are 42 tickets.")

    messages = [HumanMessage(content="count"), ai1, tool1, ai2, tool2, final_ai]
    result = _extract_capsule_data(messages, "support", "count")

    # result_json should be from execute_sql, NOT get_dataset_schema
    assert result["result_json"]["rows"] == [[42]]
    assert result["query_mode"] == "sql"


def test_extract_capsule_python_execution():
    """execute_python tool call → python_code captured."""
    tc_id = _make_tool_call_id()
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_python",
                "args": {"dataset_id": "support", "python_code": "result = 7"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content=json.dumps(
            {"status": "success", "columns": ["value"], "rows": [[7]], "row_count": 1}
        ),
        tool_call_id=tc_id,
    )
    final_ai = AIMessage(content="Done.")

    messages = [HumanMessage(content="run python"), ai_msg, tool_msg, final_ai]
    result = _extract_capsule_data(messages, "support", "run python")

    assert result["query_mode"] == "python"
    assert result["python_code"] == "result = 7"
    assert result["result_json"]["rows"] == [[7]]


def test_extract_capsule_policy_rejection_status():
    """SQL policy violation → status=rejected."""
    tc_id = _make_tool_call_id()
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_sql",
                "args": {"dataset_id": "support", "sql": "DROP TABLE tickets"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content=json.dumps(
            {
                "status": "error",
                "error": {
                    "type": "SQL_POLICY_VIOLATION",
                    "message": "SQL contains blocked token: drop",
                },
                "columns": [],
                "rows": [],
                "row_count": 0,
            }
        ),
        tool_call_id=tc_id,
    )
    final_ai = AIMessage(content="That query was rejected.")

    messages = [HumanMessage(content="drop it"), ai_msg, tool_msg, final_ai]
    result = _extract_capsule_data(messages, "support", "drop it")

    assert result["status"] == "rejected"
    assert result["result_json"]["error"]["type"] == "SQL_POLICY_VIOLATION"


def test_extract_capsule_timeout_status():
    """Runner timeout should map to timed_out."""
    tc_id = _make_tool_call_id()
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_sql",
                "args": {"dataset_id": "support", "sql": "SELECT * FROM tickets"},
            }
        ],
    )
    tool_msg = ToolMessage(
        content=json.dumps(
            {
                "status": "timeout",
                "error": {"type": "TIMEOUT", "message": "Execution timed out."},
                "columns": [],
                "rows": [],
                "row_count": 0,
            }
        ),
        tool_call_id=tc_id,
    )
    final_ai = AIMessage(content="The query timed out.")

    messages = [HumanMessage(content="run it"), ai_msg, tool_msg, final_ai]
    result = _extract_capsule_data(messages, "support", "run it")

    assert result["status"] == "timed_out"
    assert result["result_json"]["error"]["type"] == "TIMEOUT"


def test_extract_capsule_query_plan():
    """execute_query_plan → plan_json captured from tool input."""
    tc_id = _make_tool_call_id()
    plan = {
        "dataset_id": "support",
        "table": "tickets",
        "select": [{"column": "priority"}],
        "limit": 5,
    }
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_query_plan",
                "args": {"dataset_id": "support", "plan": json.dumps(plan)},
            }
        ],
    )
    tool_msg = ToolMessage(
        content=json.dumps(
            {
                "status": "success",
                "columns": ["priority"],
                "rows": [["High"]],
                "row_count": 1,
                "compiled_sql": "SELECT ...",
                "plan_json": plan,
            }
        ),
        tool_call_id=tc_id,
    )
    final_ai = AIMessage(content="Here are the results.")

    messages = [HumanMessage(content="plan"), ai_msg, tool_msg, final_ai]
    result = _extract_capsule_data(messages, "support", "plan")

    assert result["query_mode"] == "plan"
    assert result["plan_json"] == plan


# ── build_agent smoke ─────────────────────────────────────────────────────


def test_build_agent_returns_runnable():
    """build_agent with MockLLM should return a graph that can be invoked."""
    mock = MockLLM(responses=[AIMessage(content="Hello!")])
    # Empty tools list — just verifies graph is built without error
    agent = build_agent(tools=[], max_rows=200, llm=mock)
    assert agent is not None
    # Invoke with a simple message
    result = agent.invoke({"messages": [HumanMessage(content="hi")]})
    assert "messages" in result
    # Last message should be the mocked response
    last = result["messages"][-1]
    assert last.content == "Hello!"


class _SpyGraph:
    def __init__(self):
        self.last_payload = None

    def invoke(self, payload):
        self.last_payload = payload
        return {"messages": [AIMessage(content="Done.")]}


def test_run_agent_injects_last_successful_run_context(tmp_path):
    db_path = tmp_path / "capsules.db"
    init_capsule_db(str(db_path))
    store = create_message_store("sqlite", str(db_path))
    store.initialize()

    prior_run = "prior-run-1"
    insert_capsule(
        str(db_path),
        {
            "run_id": prior_run,
            "created_at": "2026-02-03T00:00:00+00:00",
            "dataset_id": "support",
            "dataset_version_hash": None,
            "question": "How many tickets?",
            "query_mode": "sql",
            "plan_json": None,
            "compiled_sql": "SELECT COUNT(*) AS n FROM tickets",
            "python_code": None,
            "status": "succeeded",
            "result_json": {
                "columns": ["n"],
                "rows": [[42]],
                "row_count": 1,
                "exec_time_ms": 10,
                "error": None,
            },
            "error_json": None,
            "exec_time_ms": 10,
        },
    )
    store.append_message(
        thread_id="t1",
        role="user",
        content="How many tickets?",
        dataset_id="support",
        run_id=prior_run,
    )
    store.append_message(
        thread_id="t1",
        role="assistant",
        content="There are 42 tickets.",
        dataset_id="support",
        run_id=prior_run,
    )

    graph = _SpyGraph()
    session = AgentSession(graph, store, str(db_path), history_window=12)
    response = session.run_agent("support", "give me those again with names", "t1")

    assert response["status"] == "succeeded"
    messages = graph.last_payload["messages"]
    assert any(
        isinstance(msg, SystemMessage)
        and "Previous successful run context" in str(msg.content)
        and "SELECT COUNT(*) AS n FROM tickets" in str(msg.content)
        for msg in messages
    )


class _RecursingGraph:
    def invoke(self, payload):
        raise GraphRecursionError("Recursion limit reached")


def test_run_agent_handles_graph_recursion_gracefully(tmp_path):
    db_path = tmp_path / "capsules.db"
    init_capsule_db(str(db_path))
    store = create_message_store("sqlite", str(db_path))
    store.initialize()

    session = AgentSession(_RecursingGraph(), store, str(db_path), history_window=12)
    response = session.run_agent("support", "join in product names", "t-rec")

    assert response["status"] == "failed"
    assert response["result"]["error"]["type"] == "AGENT_RECURSION_LIMIT"
    assert "reasoning limit" in response["assistant_message"].lower()

    history = store.get_messages(thread_id="t-rec", limit=10)
    assert history[-1]["role"] == "assistant"
