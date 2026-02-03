from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.main import Settings, create_app  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_create_app_microsandbox_uses_provider_factory(monkeypatch, tmp_path):
    class _FakeExecutor:
        def submit_run(self, payload, query_type="sql"):  # noqa: ANN001
            return {
                "run_id": "r1",
                "status": "succeeded",
                "result": {
                    "status": "success",
                    "columns": ["n"],
                    "rows": [[7]],
                    "row_count": 1,
                    "exec_time_ms": 1,
                    "stdout_trunc": "",
                    "stderr_trunc": "",
                    "error": None,
                },
            }

    called = {"value": False}

    def fake_factory(**_kwargs):  # noqa: ANN001
        called["value"] = True
        return _FakeExecutor()

    monkeypatch.setattr("app.main.create_sandbox_executor", fake_factory)

    settings = Settings(
        datasets_dir=str(Path(__file__).parent.parent.parent / "datasets"),
        capsule_db_path=str(tmp_path / "capsules.db"),
        sandbox_provider="microsandbox",
        msb_server_url="http://127.0.0.1:5555/api/v1/rpc",
        msb_api_key="",
    )
    app = create_app(settings=settings)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        res = await client.post(
            "/chat",
            json={"dataset_id": "support", "message": "SQL: SELECT COUNT(*) AS n FROM tickets"},
        )
        assert res.status_code == 200
        assert called["value"] is True
        assert res.json()["result"]["rows"] == [[7]]
    finally:
        await client.aclose()


def test_create_app_docker_does_not_require_microsandbox(monkeypatch, tmp_path):
    def fail_factory(**_kwargs):  # noqa: ANN001
        raise AssertionError("create_sandbox_executor should not be called for docker provider")

    monkeypatch.setattr("app.main.create_sandbox_executor", fail_factory)
    settings = Settings(
        datasets_dir=str(Path(__file__).parent.parent.parent / "datasets"),
        capsule_db_path=str(tmp_path / "capsules.db"),
        sandbox_provider="docker",
    )
    app = create_app(settings=settings)
    assert app is not None
