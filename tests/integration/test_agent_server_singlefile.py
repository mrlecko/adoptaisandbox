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


async def _make_client(tmp_path, runner_result=None):
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

    app = create_app(settings=settings, runner_executor=fake_runner)
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
        assert "CSV Analyst Chat (Minimal)" in body
        assert "id=\"dataset\"" in body
        assert "/chat/stream" in body
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
