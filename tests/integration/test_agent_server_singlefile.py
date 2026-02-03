"""
Integration tests for the single-file FastAPI agent server.
"""

from pathlib import Path
import sys

import httpx
import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.main import create_app, Settings  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _make_client(tmp_path, runner_result=None, runner_executor=None, settings_overrides=None):
    datasets_dir = Path(__file__).parent.parent.parent / "datasets"
    db_path = tmp_path / "capsules.db"

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

    def fake_runner(*_, **__):
        return runner_result or {
            "status": "success",
            "columns": ["n"],
            "rows": [[42]],
            "row_count": 1,
            "exec_time_ms": 12,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    app = create_app(settings=settings, runner_executor=runner_executor or fake_runner)
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client


@pytest.mark.anyio
async def test_get_datasets_returns_registry_entries(tmp_path):
    client = await _make_client(tmp_path)
    try:
        response = await client.get("/datasets")

        assert response.status_code == 200
        payload = response.json()
        ids = {d["id"] for d in payload["datasets"]}
        assert ids == {"ecommerce", "support", "sensors"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_get_dataset_schema_returns_schema(tmp_path):
    client = await _make_client(tmp_path)
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
    client = await _make_client(tmp_path)
    try:
        response = await client.get("/")
        assert response.status_code == 200
        body = response.text
        assert "CSV Analysis Agent" in body
        assert "id=\"dataset\"" in body
        assert "id=\"messages\"" in body
        assert "/chat/stream" in body
        assert "id=\"prompts\"" in body
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_sql_happy_path_creates_capsule(tmp_path):
    client = await _make_client(tmp_path)
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
        run_id = payload["run_id"]

        run_response = await client.get(f"/runs/{run_id}")
        assert run_response.status_code == 200
        run_payload = run_response.json()
        assert run_payload["run_id"] == run_id
        assert run_payload["status"] == "succeeded"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_scalar_result_is_summarized_in_assistant_message(tmp_path):
    def fake_runner(*_, **__):
        return {
            "status": "success",
            "columns": ["total_orders"],
            "rows": [[4018]],
            "row_count": 1,
            "exec_time_ms": 8,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    client = await _make_client(tmp_path, runner_executor=fake_runner)
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "ecommerce", "message": "SQL: SELECT COUNT(*) AS total_orders FROM orders"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "4018" in payload["assistant_message"]
        assert "total orders" in payload["assistant_message"].lower()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_complex_result_refers_to_result_table(tmp_path):
    def fake_runner(*_, **__):
        return {
            "status": "success",
            "columns": ["priority", "count", "avg_csat"],
            "rows": [[f"p{i}", i, 4.5] for i in range(10)],
            "row_count": 10,
            "exec_time_ms": 12,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    client = await _make_client(tmp_path, runner_executor=fake_runner)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT priority, COUNT(*) AS count, AVG(csat_score) AS avg_csat FROM tickets GROUP BY priority",
            },
        )
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert "result table" in payload["assistant_message"].lower()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_greeting_does_not_execute_runner(tmp_path):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Runner should not be called for greeting messages")

    client = await _make_client(tmp_path, runner_executor=should_not_run)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "Hi",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "rejected"
        assert payload["details"]["query_mode"] == "chat"
        assert payload["result"]["row_count"] == 0
        assert payload["result"]["error"]["type"] == "LLM_UNAVAILABLE"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_schema_question_does_not_execute_runner(tmp_path):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Runner should not be called for schema-only messages")

    client = await _make_client(tmp_path, runner_executor=should_not_run)
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
        assert payload["status"] == "rejected"
        assert payload["details"]["query_mode"] == "chat"
        assert "llm service unavailable" in payload["assistant_message"].lower()
        assert payload["result"]["row_count"] == 0
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_mode_from_llm_does_not_execute_runner(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate(*_, **__):
        return {
            "query_mode": "chat",
            "assistant_message": "Hi there! How can I help with your dataset today?",
        }

    monkeypatch.setattr(app_main, "_generate_with_langchain", fake_generate)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Runner should not be called for chat-mode responses")

    client = await _make_client(tmp_path, runner_executor=should_not_run)
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "Hi"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "chat"
        assert "hi there" in payload["assistant_message"].lower()
        assert payload["result"]["row_count"] == 0
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_stateful_memory_with_thread_id(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate(*_, **kwargs):
        message = kwargs["message"].lower()
        history = kwargs.get("history") or []
        if "what is my name" in message:
            remembered = any(
                m.get("role") == "user" and "my name is dave" in str(m.get("content", "")).lower()
                for m in history
            )
            if remembered:
                return {"query_mode": "chat", "assistant_message": "Your name is Dave."}
            return {"query_mode": "chat", "assistant_message": "I don't know your name."}
        return {"query_mode": "chat", "assistant_message": "Nice to meet you, Dave!"}

    monkeypatch.setattr(app_main, "_generate_with_langchain", fake_generate)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Runner should not be called for chat mode memory test")

    client = await _make_client(tmp_path, runner_executor=should_not_run)
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
        assert "your name is dave" in second.json()["assistant_message"].lower()

        history_res = await client.get(f"/threads/{thread_id}/messages?limit=20")
        assert history_res.status_code == 200
        messages = history_res.json()["messages"]
        assert len(messages) >= 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_thread_isolation(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate(*_, **kwargs):
        message = kwargs["message"].lower()
        history = kwargs.get("history") or []
        if "what is my name" in message:
            remembered = any(
                m.get("role") == "user" and "my name is dave" in str(m.get("content", "")).lower()
                for m in history
            )
            if remembered:
                return {"query_mode": "chat", "assistant_message": "Your name is Dave."}
            return {"query_mode": "chat", "assistant_message": "I don't know your name."}
        return {"query_mode": "chat", "assistant_message": "Noted."}

    monkeypatch.setattr(app_main, "_generate_with_langchain", fake_generate)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Runner should not be called for chat mode memory test")

    client = await _make_client(tmp_path, runner_executor=should_not_run)
    try:
        await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "thread_id": "thread-a",
                "message": "my name is dave, remember this",
            },
        )
        isolated = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "thread_id": "thread-b",
                "message": "what is my name",
            },
        )
        assert isolated.status_code == 200
        assert "don't know your name" in isolated.json()["assistant_message"].lower()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_sql_policy_violation_rejected(tmp_path):
    client = await _make_client(tmp_path)
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
async def test_chat_sql_created_at_not_false_positive_blocked(tmp_path):
    client = await _make_client(tmp_path)
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
async def test_chat_sql_normalizes_dataset_qualified_table_reference(tmp_path):
    client = await _make_client(tmp_path)
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


@pytest.mark.anyio
async def test_chat_non_sql_accepts_dict_draft_from_llm(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate(*_, **__):
        return {
            "query_mode": "sql",
            "assistant_message": "LLM generated SQL.",
            "sql": "SELECT COUNT(*) AS n FROM tickets",
        }

    monkeypatch.setattr(app_main, "_generate_with_langchain", fake_generate)

    client = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "How many tickets are there?",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "sql"
        assert "42" in payload["assistant_message"]
        assert payload["result"]["rows"] == [[42]]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_non_executable_draft_without_rescue_returns_clarification(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate(*_, **__):
        return {
            "query_mode": "plan",
            "assistant_message": "I will query the table for you.",
            # Missing `plan`: should be treated as invalid/non-executable.
        }

    monkeypatch.setattr(app_main, "_generate_with_langchain", fake_generate)

    client = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "Find the highest ticket volume day.",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "rejected"
        assert payload["details"]["query_mode"] == "chat"
        assert "llm service unavailable or returned an invalid response" in payload["assistant_message"].lower()
        assert payload["result"]["error"]["type"] == "LLM_UNAVAILABLE"
        assert payload["details"]["compiled_sql"] is None
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_non_executable_draft_uses_sql_rescue(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate(*_, **__):
        return {
            "query_mode": "plan",
            "assistant_message": "I will query the table for you.",
            # Missing `plan`: invalid for execution.
        }

    def fake_rescue(*_, **__):
        return app_main.SqlRescueDraft(
            sql="SELECT COUNT(*) AS n FROM tickets LIMIT 1",
            assistant_message="Executed via SQL rescue.",
        )

    monkeypatch.setattr(app_main, "_generate_with_langchain", fake_generate)
    monkeypatch.setattr(app_main, "_generate_sql_rescue_with_langchain", fake_rescue)

    client = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "How many tickets are there?",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "sql"
        assert "42" in payload["assistant_message"]
        assert payload["result"]["rows"] == [[42]]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_stream_emits_status_and_result_events(tmp_path):
    client = await _make_client(tmp_path)
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
        assert "event: status" in body
        assert "planning" in body
        assert "executing" in body
        assert "event: result" in body
        assert "event: done" in body
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_post_runs_sql_executes_and_persists(tmp_path):
    client = await _make_client(tmp_path)
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
        run_payload = run_response.json()
        assert run_payload["query_mode"] == "sql"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_get_run_status_endpoint(tmp_path):
    client = await _make_client(tmp_path)
    try:
        response = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "SQL: SELECT COUNT(*) AS n FROM tickets"},
        )
        run_id = response.json()["run_id"]
        status_response = await client.get(f"/runs/{run_id}/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "succeeded"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_post_runs_python_executes_and_persists_python_code(tmp_path):
    captured = {}

    def fake_runner(settings, dataset, sql, timeout, max_rows, **kwargs):
        captured["query_type"] = kwargs.get("query_type")
        captured["python_code"] = kwargs.get("python_code")
        return {
            "status": "success",
            "columns": ["value"],
            "rows": [[1]],
            "row_count": 1,
            "exec_time_ms": 9,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    client = await _make_client(tmp_path, runner_executor=fake_runner)
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
        assert captured["query_type"] == "python"
        assert captured["python_code"] == "result = 1"

        run_id = payload["run_id"]
        run_payload = (await client.get(f"/runs/{run_id}")).json()
        assert run_payload["python_code"] == "result = 1"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_python_happy_path_uses_python_runner_mode(tmp_path):
    captured = {}

    def fake_runner(settings, dataset, sql, timeout, max_rows, **kwargs):
        captured["dataset_id"] = dataset["id"]
        captured["sql"] = sql
        captured["query_type"] = kwargs.get("query_type")
        captured["python_code"] = kwargs.get("python_code")
        return {
            "status": "success",
            "columns": ["n"],
            "rows": [[7]],
            "row_count": 1,
            "exec_time_ms": 10,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    client = await _make_client(tmp_path, runner_executor=fake_runner)
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
        assert payload["details"]["compiled_sql"] is None
        assert payload["details"]["python_code"] == "result = len(tickets)"
        run_id = payload["run_id"]
        assert captured["dataset_id"] == "support"
        assert captured["query_type"] == "python"
        assert captured["python_code"] == "result = len(tickets)"
        assert captured["sql"] == ""

        run_response = await client.get(f"/runs/{run_id}")
        assert run_response.status_code == 200
        run_payload = run_response.json()
        assert run_payload["python_code"] == "result = len(tickets)"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_python_rejected_when_feature_disabled(tmp_path):
    client = await _make_client(tmp_path, settings_overrides={"enable_python_execution": False})
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


@pytest.mark.anyio
async def test_chat_implicit_python_intent_uses_generated_python(tmp_path, monkeypatch):
    from app import main as app_main

    def fake_generate_python(*_, **__):
        return app_main.PythonDraft(
            python_code='result_df = tickets.groupby("priority").size().reset_index(name="n")',
            assistant_message="Generated pandas analysis.",
        )

    monkeypatch.setattr(app_main, "_generate_python_with_langchain", fake_generate_python)

    captured = {}

    def fake_runner(settings, dataset, sql, timeout, max_rows, **kwargs):
        captured["query_type"] = kwargs.get("query_type")
        captured["python_code"] = kwargs.get("python_code")
        return {
            "status": "success",
            "columns": ["priority", "n"],
            "rows": [["High", 1]],
            "row_count": 1,
            "exec_time_ms": 10,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    client = await _make_client(tmp_path, runner_executor=fake_runner)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "use pandas to group the tickets by priority",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "python"
        assert payload["assistant_message"]
        assert captured["query_type"] == "python"
        assert "groupby" in captured["python_code"]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_implicit_python_intent_uses_heuristic_when_llm_unavailable(tmp_path, monkeypatch):
    from app import main as app_main

    monkeypatch.setattr(app_main, "_generate_python_with_langchain", lambda *_, **__: None)

    captured = {}

    def fake_runner(settings, dataset, sql, timeout, max_rows, **kwargs):
        captured["python_code"] = kwargs.get("python_code")
        return {
            "status": "success",
            "columns": ["priority", "count"],
            "rows": [["High", 1]],
            "row_count": 1,
            "exec_time_ms": 10,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": None,
        }

    client = await _make_client(tmp_path, runner_executor=fake_runner)
    try:
        response = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "use pandas to group the tickets by priority",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "python"
        assert "groupby(\"priority\")" in captured["python_code"]
    finally:
        await client.aclose()
