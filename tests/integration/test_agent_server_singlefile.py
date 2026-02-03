"""
Integration tests for the single-file FastAPI agent server.

All tests use FakeExecutor + MockLLM — no Docker, no API keys required.
"""

import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.base import Executor  # noqa: E402
from app.main import Settings, create_app  # noqa: E402


# ── Shared test harness ───────────────────────────────────────────────────


class FakeExecutor(Executor):
    """Executor stub that returns canned results and records calls.

    Pass `results` to queue multiple return values (popped in order);
    `default_result` is used when the queue is empty.
    """

    def __init__(self, results=None, default_result=None):
        self.calls: list[dict] = []
        self._results = list(results) if results else []
        self._default = default_result or {
            "run_id": "fake-run",
            "status": "succeeded",
            "result": {
                "status": "success",
                "columns": ["n"],
                "rows": [[42]],
                "row_count": 1,
                "exec_time_ms": 12,
                "error": None,
            },
        }

    def submit_run(self, payload, query_type="sql"):
        self.calls.append({"payload": payload, "query_type": query_type})
        if self._results:
            return self._results.pop(0)
        return self._default

    def get_status(self, run_id):
        return {"run_id": run_id, "status": "succeeded"}

    def get_result(self, run_id):
        return self._default.get("result")

    def cleanup(self, run_id):
        pass


class MockLLM(BaseChatModel):
    """Scripted LLM — pops responses from a queue."""

    responses: list = []

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self.responses.pop(0) if self.responses else AIMessage(content="(empty)")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self  # no-op; tool_calls are scripted


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _make_client(
    tmp_path,
    mock_responses=None,
    fake_result=None,
    fake_results_queue=None,
    settings_overrides=None,
):
    """Build an httpx async client wired to a fully-mocked app."""
    datasets_dir = Path(__file__).parent.parent.parent / "datasets"
    db_path = tmp_path / "capsules.db"

    executor = FakeExecutor(
        results=fake_results_queue,
        default_result=fake_result,
    )
    llm = MockLLM(responses=mock_responses or [AIMessage(content="OK")])

    settings = Settings(
        datasets_dir=str(datasets_dir),
        capsule_db_path=str(db_path),
        anthropic_api_key=None,
        runner_image="csv-analyst-runner:test",
        run_timeout_seconds=5,
        max_rows=200,
        log_level="info",
        **(settings_overrides or {}),
    )

    app = create_app(settings=settings, llm=llm, executor=executor)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return client, executor


def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        data_line = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.replace("event: ", "", 1).strip()
            elif line.startswith("data: "):
                data_line = line.replace("data: ", "", 1).strip()
        if event_name and data_line:
            events.append((event_name, json.loads(data_line)))
    return events


# ── Discovery / static endpoints ──────────────────────────────────────────


@pytest.mark.anyio
async def test_get_datasets_returns_registry_entries(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.get("/datasets")
        assert response.status_code == 200
        ids = {d["id"] for d in response.json()["datasets"]}
        assert ids == {"ecommerce", "support", "sensors"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_get_dataset_schema_returns_schema(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.get("/datasets/ecommerce/schema")
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == "ecommerce"
        assert len(payload["files"]) >= 1
        assert "schema" in payload["files"][0]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_home_serves_static_ui(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.get("/")
        assert response.status_code == 200
        body = response.text
        assert "CSV Analysis Agent" in body
        assert 'id="dataset"' in body
        assert 'id="messages"' in body
        assert "/chat/stream" in body
        assert 'id="prompts"' in body
    finally:
        await client.aclose()


# ── SQL: fast path ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_sql_happy_path_creates_capsule(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT COUNT(*) AS n FROM tickets",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "sql"
        assert payload["result"]["rows"] == [[42]]

        # Capsule persisted
        run_id = payload["run_id"]
        run_response = await client.get(f"/runs/{run_id}")
        assert run_response.status_code == 200
        assert run_response.json()["run_id"] == run_id
        assert run_response.json()["status"] == "succeeded"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_sql_policy_violation_rejected(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: DROP TABLE tickets",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "rejected"
        assert payload["result"]["error"]["type"] == "SQL_POLICY_VIOLATION"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_sql_timeout_maps_timed_out(tmp_path):
    fake_result = {
        "run_id": "fake-run-timeout",
        "status": "succeeded",
        "result": {
            "status": "timeout",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 1000,
            "error": {"type": "TIMEOUT", "message": "Execution timed out."},
        },
    }
    client, _ = await _make_client(tmp_path, fake_result=fake_result)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT COUNT(*) AS n FROM tickets",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "timed_out"
        assert payload["result"]["error"]["type"] == "TIMEOUT"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_sql_created_at_not_false_positive(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT MAX(created_at) AS last_ticket_added FROM tickets",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["compiled_sql"].lower().startswith("select")
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_sql_normalizes_dataset_qualified(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT MAX(created_at) AS last_ticket_added FROM support.tickets",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "support.tickets" not in payload["details"]["compiled_sql"].lower()
        assert "from tickets" in payload["details"]["compiled_sql"].lower()
    finally:
        await client.aclose()


# ── PYTHON: fast path ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_python_happy_path(tmp_path):
    client, executor = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "PYTHON: result = len(tickets)",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "python"
        assert payload["details"]["python_code"] == "result = len(tickets)"
        assert payload["details"]["compiled_sql"] is None
        # Verify executor was called with python
        assert len(executor.calls) == 1
        assert executor.calls[0]["query_type"] == "python"
        assert executor.calls[0]["payload"]["python_code"] == "result = len(tickets)"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_python_rejected_when_disabled(tmp_path):
    client, _ = await _make_client(
        tmp_path, settings_overrides={"enable_python_execution": False}
    )
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "PYTHON: result = len(tickets)",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "rejected"
        assert payload["result"]["error"]["type"] == "FEATURE_DISABLED"
    finally:
        await client.aclose()


# ── /runs endpoint ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_post_runs_sql_executes_and_persists(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/runs",
            json={
                "dataset_id": "support",
                "query_type": "sql",
                "sql": "SELECT COUNT(*) AS n FROM tickets",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "sql"

        run_id = payload["run_id"]
        run_response = await client.get(f"/runs/{run_id}")
        assert run_response.status_code == 200
        assert run_response.json()["query_mode"] == "sql"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_post_runs_python_executes_and_persists(tmp_path):
    client, executor = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/runs",
            json={
                "dataset_id": "support",
                "query_type": "python",
                "python_code": "result = 1",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "python"
        assert executor.calls[0]["query_type"] == "python"
        assert executor.calls[0]["payload"]["python_code"] == "result = 1"

        run_id = payload["run_id"]
        run_payload = (await client.get(f"/runs/{run_id}")).json()
        assert run_payload["python_code"] == "result = 1"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_get_run_status_endpoint(tmp_path):
    client, _ = await _make_client(tmp_path)
    try:
        # Create a run via SQL: fast path
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT COUNT(*) AS n FROM tickets",
            },
        )
        run_id = response.json()["run_id"]

        status_response = await client.get(f"/runs/{run_id}/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "succeeded"
    finally:
        await client.aclose()


# ── Agent path — chat-only (no execution) ────────────────────────────────


@pytest.mark.anyio
async def test_chat_greeting_no_execution(tmp_path):
    """Greeting → MockLLM returns text only → chat mode, no executor call."""
    client, executor = await _make_client(
        tmp_path,
        mock_responses=[AIMessage(content="Hello! I can help you analyze data.")],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "Hi"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "hello" in payload["assistant_message"].lower()
        assert len(executor.calls) == 0  # no sandbox invocation
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_schema_question_no_execution(tmp_path):
    """Schema question answered by LLM text → no execution."""
    client, executor = await _make_client(
        tmp_path,
        mock_responses=[
            AIMessage(
                content="The dataset has the following columns: ticket_id, priority, status."
            )
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "What columns are in this dataset?",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "columns" in payload["assistant_message"].lower()
        assert len(executor.calls) == 0
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_llm_chat_response(tmp_path):
    """LLM returns a clarification question — no execution."""
    client, executor = await _make_client(
        tmp_path,
        mock_responses=[
            AIMessage(
                content="Could you be more specific about what you're looking for?"
            )
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "Show me something interesting"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "specific" in payload["assistant_message"].lower()
        assert len(executor.calls) == 0
    finally:
        await client.aclose()


# ── Agent path — with tool calls ──────────────────────────────────────────

# Helper: build an AIMessage with a scripted tool_call for execute_sql


def _sql_tool_call_msg(sql: str, dataset_id: str = "support", tc_id: str = "tc-1"):
    """AIMessage with a scripted execute_sql tool call."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_sql",
                "args": {"dataset_id": dataset_id, "sql": sql},
            }
        ],
    )


def _python_tool_call_msg(code: str, dataset_id: str = "support", tc_id: str = "tc-py"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "name": "execute_python",
                "args": {"dataset_id": dataset_id, "python_code": code},
            }
        ],
    )


@pytest.mark.anyio
async def test_chat_scalar_result_summarized(tmp_path):
    """Agent calls execute_sql → scalar result → LLM summarizes."""
    fake_result = {
        "run_id": "fake-run",
        "status": "succeeded",
        "result": {
            "status": "success",
            "columns": ["total_orders"],
            "rows": [[4018]],
            "row_count": 1,
            "exec_time_ms": 8,
            "error": None,
        },
    }
    client, _ = await _make_client(
        tmp_path,
        fake_result=fake_result,
        mock_responses=[
            _sql_tool_call_msg(
                "SELECT COUNT(*) AS total_orders FROM orders", "ecommerce"
            ),
            AIMessage(content="There are 4018 total orders."),
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "ecommerce", "message": "How many orders?"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "4018" in payload["assistant_message"]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_complex_result_summary(tmp_path):
    """Agent calls execute_sql → multi-row result → LLM says see table."""
    fake_result = {
        "run_id": "fake-run",
        "status": "succeeded",
        "result": {
            "status": "success",
            "columns": ["priority", "count", "avg_csat"],
            "rows": [[f"p{i}", i, 4.5] for i in range(10)],
            "row_count": 10,
            "exec_time_ms": 12,
            "error": None,
        },
    }
    client, _ = await _make_client(
        tmp_path,
        fake_result=fake_result,
        mock_responses=[
            _sql_tool_call_msg(
                "SELECT priority, COUNT(*) AS count, AVG(csat_score) AS avg_csat FROM tickets GROUP BY priority"
            ),
            AIMessage(
                content="Here are the results — please see the result table for the full breakdown."
            ),
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "Break down tickets by priority"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "result table" in payload["assistant_message"].lower()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_llm_generates_sql(tmp_path):
    """LLM generates a tool_call for execute_sql, then a text response."""
    client, executor = await _make_client(
        tmp_path,
        mock_responses=[
            _sql_tool_call_msg("SELECT COUNT(*) AS n FROM tickets"),
            AIMessage(content="42 tickets in the dataset."),
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "How many tickets are there?"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "42" in payload["assistant_message"]
        assert len(executor.calls) == 1
        assert executor.calls[0]["query_type"] == "sql"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_llm_retries_after_sql_error(tmp_path):
    """First execute_sql returns error, second succeeds. Agent retries."""
    error_result = {
        "run_id": "err",
        "status": "failed",
        "result": {
            "status": "error",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 1,
            "error": {"type": "RUNNER_ERROR", "message": "table not found"},
        },
    }
    success_result = {
        "run_id": "ok",
        "status": "succeeded",
        "result": {
            "status": "success",
            "columns": ["n"],
            "rows": [[42]],
            "row_count": 1,
            "exec_time_ms": 5,
            "error": None,
        },
    }
    client, executor = await _make_client(
        tmp_path,
        fake_results_queue=[error_result, success_result],
        mock_responses=[
            _sql_tool_call_msg("SELECT * FROM wrong_table", tc_id="tc-1"),
            _sql_tool_call_msg("SELECT COUNT(*) AS n FROM tickets", tc_id="tc-2"),
            AIMessage(content="Done — found 42 tickets."),
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "count tickets please"},
        )
        assert response.status_code == 200
        payload = response.json()
        # The last execution succeeded
        assert payload["status"] == "succeeded"
        assert "42" in payload["assistant_message"]
        assert len(executor.calls) == 2
    finally:
        await client.aclose()


# ── Thread / memory tests ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_stateful_memory_thread(tmp_path):
    """Two messages on same thread — history persists, /threads endpoint works."""
    client, _ = await _make_client(
        tmp_path,
        mock_responses=[
            AIMessage(content="Nice to meet you, Dave!"),
            AIMessage(content="Your name is Dave."),
        ],
    )
    try:
        thread_id = "thread-memory-dave"

        first = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "thread_id": thread_id,
                "message": "my name is dave, remember this",
            },
        )
        assert first.status_code == 200
        assert "dave" in first.json()["assistant_message"].lower()

        second = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "thread_id": thread_id,
                "message": "what is my name",
            },
        )
        assert second.status_code == 200
        assert "dave" in second.json()["assistant_message"].lower()

        # Thread history should have 4 messages (2 user + 2 assistant)
        history_res = await client.get(f"/threads/{thread_id}/messages?limit=20")
        assert history_res.status_code == 200
        messages = history_res.json()["messages"]
        assert len(messages) >= 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_thread_isolation(tmp_path):
    """Different thread_ids don't share history."""
    client, _ = await _make_client(
        tmp_path,
        mock_responses=[
            AIMessage(content="Noted."),
            AIMessage(content="I don't know your name."),
        ],
    )
    try:
        # Thread A: introduce name
        await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "thread_id": "thread-a",
                "message": "my name is dave, remember this",
            },
        )

        # Thread B: ask name — should NOT know
        isolated = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "thread_id": "thread-b",
                "message": "what is my name",
            },
        )
        assert isolated.status_code == 200
        # MockLLM returns scripted "I don't know your name." for thread B
        assert "don't know" in isolated.json()["assistant_message"].lower()
    finally:
        await client.aclose()


# ── Streaming ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_stream_events(tmp_path):
    """SQL: fast path stream emits status + result + done events in order."""
    client, _ = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat/stream",
            json={
                "dataset_id": "ecommerce",
                "message": "SQL: SELECT COUNT(*) AS n FROM orders",
            },
        )
        assert response.status_code == 200
        body = response.text

        # Verify event ordering
        assert "event: status" in body
        assert "planning" in body
        assert "executing" in body
        assert "event: result" in body
        assert "event: done" in body

        # result comes after status events, done comes last
        result_pos = body.index("event: result")
        done_pos = body.index("event: done")
        assert result_pos < done_pos
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_stream_agent_tool_path_serializes_events(tmp_path):
    """Non-fast-path streaming should complete and return a structured result event."""
    client, _ = await _make_client(
        tmp_path,
        mock_responses=[
            _sql_tool_call_msg("SELECT COUNT(*) AS n FROM tickets"),
            AIMessage(content="There are 42 tickets."),
        ],
    )
    try:
        response = await asyncio.wait_for(
            client.post(
                "/chat/stream",
                json={
                    "dataset_id": "support",
                    "message": "How many tickets are there?",
                },
            ),
            timeout=8,
        )
        assert response.status_code == 200
        body = response.text
        events = _parse_sse_events(body)
        result_payload = next(data for event, data in events if event == "result")
        assert "event: result" in body
        assert "event: done" in body
        assert "event: error" not in body
        assert "ToolMessage is not JSON serializable" not in body
        assert result_payload["result"]["rows"] == [[42]]
    finally:
        await client.aclose()


# ── Python via agent ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_implicit_python_via_agent(tmp_path):
    """Agent calls execute_python via tool_call."""
    client, executor = await _make_client(
        tmp_path,
        mock_responses=[
            _python_tool_call_msg(
                'result_df = tickets.groupby("priority").size().reset_index(name="n")'
            ),
            AIMessage(content="Analysis complete."),
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "use pandas to group tickets by priority",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "analysis complete" in payload["assistant_message"].lower()
        assert len(executor.calls) == 1
        assert executor.calls[0]["query_type"] == "python"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_llm_calls_execute_python(tmp_path):
    """LLM explicitly calls execute_python tool."""
    client, executor = await _make_client(
        tmp_path,
        mock_responses=[
            _python_tool_call_msg("result = len(tickets)"),
            AIMessage(content="Done — computed the length."),
        ],
    )
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "run some python"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "done" in payload["assistant_message"].lower()
        assert executor.calls[0]["payload"]["python_code"] == "result = len(tickets)"
    finally:
        await client.aclose()
