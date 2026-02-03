"""
Integration tests for the MicroSandbox provider path.

These tests are opt-in and require a running MicroSandbox server plus a runner
image accessible to that server.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.microsandbox_executor import MicroSandboxExecutor  # noqa: E402
from app.main import Settings, create_app  # noqa: E402


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _build_settings(tmp_path: Path) -> Settings:
    datasets_dir = Path(__file__).parent.parent.parent / "datasets"
    return Settings(
        datasets_dir=str(datasets_dir),
        capsule_db_path=str(tmp_path / "capsules.db"),
        anthropic_api_key=None,
        openai_api_key=None,
        llm_provider="auto",
        runner_image=os.getenv("MSB_RUNNER_IMAGE", "csv-analyst-runner:test"),
        sandbox_provider="microsandbox",
        msb_server_url=os.getenv("MSB_SERVER_URL", "http://127.0.0.1:5555/api/v1/rpc"),
        msb_api_key=os.getenv("MSB_API_KEY", ""),
        msb_namespace=os.getenv("MSB_NAMESPACE", "default"),
        msb_memory_mb=int(os.getenv("MSB_MEMORY_MB", "512")),
        msb_cpus=float(os.getenv("MSB_CPUS", "1.0")),
        run_timeout_seconds=int(os.getenv("RUN_TIMEOUT_SECONDS", "10")),
        max_rows=200,
        max_output_bytes=65536,
    )


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
def require_microsandbox_env():
    if not _env_bool("RUN_MICROSANDBOX_TESTS", "0"):
        pytest.skip("Set RUN_MICROSANDBOX_TESTS=1 to run MicroSandbox integration tests.")

    ex = MicroSandboxExecutor(
        runner_image=os.getenv("MSB_RUNNER_IMAGE", "csv-analyst-runner:test"),
        datasets_dir="datasets",
        server_url=os.getenv("MSB_SERVER_URL", "http://127.0.0.1:5555/api/v1/rpc"),
        api_key=os.getenv("MSB_API_KEY", ""),
        namespace=os.getenv("MSB_NAMESPACE", "default"),
    )
    health = httpx.get(ex._health_url(), timeout=10)  # noqa: SLF001
    if health.status_code >= 400:
        pytest.fail(
            "MicroSandbox health check failed. "
            f"status={health.status_code}, body={health.text[:200]}"
        )


@pytest.mark.anyio
async def test_microsandbox_sql_query_e2e(tmp_path):
    app = create_app(settings=_build_settings(tmp_path))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        res = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: SELECT COUNT(*) AS total_tickets FROM tickets",
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "sql"
        assert payload["result"]["row_count"] == 1
        assert "total tickets" in payload["assistant_message"].lower()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_microsandbox_python_query_e2e(tmp_path):
    app = create_app(settings=_build_settings(tmp_path))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        res = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": (
                    "PYTHON: result_df = tickets.groupby('priority').size()"
                    ".reset_index(name='ticket_count').sort_values('ticket_count', ascending=False)"
                ),
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "succeeded"
        assert payload["details"]["query_mode"] == "python"
        assert payload["result"]["row_count"] > 0
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_microsandbox_policy_rejection_path(tmp_path):
    app = create_app(settings=_build_settings(tmp_path))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        res = await client.post(
            "/chat",
            json={
                "dataset_id": "support",
                "message": "SQL: DROP TABLE tickets",
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "rejected"
        assert payload["result"]["error"]["type"] == "SQL_POLICY_VIOLATION"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_microsandbox_timeout_path(tmp_path):
    settings = _build_settings(tmp_path)
    settings.run_timeout_seconds = 1
    app = create_app(settings=settings)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        res = await client.post(
            "/chat",
            json={
                "dataset_id": "ecommerce",
                "message": "SQL: SELECT SUM(random()) FROM range(500000000)",
            },
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "failed"
        err_type = (payload.get("result", {}).get("error", {}).get("type") or "").upper()
        assert "TIMEOUT" in err_type
    finally:
        await client.aclose()
