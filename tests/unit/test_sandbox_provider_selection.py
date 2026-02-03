from pathlib import Path
import sys

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.main import Settings, create_app  # noqa: E402


class MockLLM(BaseChatModel):
    responses: list = []

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self.responses.pop(0) if self.responses else AIMessage(content="OK")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self


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

        def get_status(self, run_id):
            return {"run_id": run_id, "status": "succeeded"}

        def get_result(self, run_id):
            return None

        def cleanup(self, run_id):
            pass

    called = {"value": False}

    def fake_factory(**_kwargs):  # noqa: ANN001
        called["value"] = True
        return _FakeExecutor()

    monkeypatch.setattr("app.main.create_sandbox_executor", fake_factory)

    mock_llm = MockLLM(responses=[AIMessage(content="OK")])

    settings = Settings(
        datasets_dir=str(Path(__file__).parent.parent.parent / "datasets"),
        capsule_db_path=str(tmp_path / "capsules.db"),
        sandbox_provider="microsandbox",
        msb_server_url="http://127.0.0.1:5555/api/v1/rpc",
        msb_api_key="",
    )
    app = create_app(settings=settings, llm=mock_llm)
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


@pytest.mark.anyio
async def test_create_app_docker_uses_provider_factory(monkeypatch, tmp_path):
    """Docker now goes through the factory — verify it IS called."""

    class _FakeDockerExecutor:
        def submit_run(self, payload, query_type="sql"):
            return {
                "run_id": "r2",
                "status": "succeeded",
                "result": {
                    "status": "success",
                    "columns": ["n"],
                    "rows": [[1]],
                    "row_count": 1,
                    "exec_time_ms": 1,
                    "error": None,
                },
            }

        def get_status(self, run_id):
            return {"run_id": run_id, "status": "succeeded"}

        def get_result(self, run_id):
            return None

        def cleanup(self, run_id):
            pass

    called = {"value": False}

    def fake_factory(**_kwargs):
        called["value"] = True
        return _FakeDockerExecutor()

    monkeypatch.setattr("app.main.create_sandbox_executor", fake_factory)

    mock_llm = MockLLM(responses=[AIMessage(content="OK")])

    settings = Settings(
        datasets_dir=str(Path(__file__).parent.parent.parent / "datasets"),
        capsule_db_path=str(tmp_path / "capsules.db"),
        sandbox_provider="docker",
    )
    app = create_app(settings=settings, llm=mock_llm)
    assert app is not None
    assert called["value"] is True
