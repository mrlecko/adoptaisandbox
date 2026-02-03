import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.microsandbox_executor import MicroSandboxExecutor  # noqa: E402


def test_microsandbox_rpc_url_normalization():
    ex = MicroSandboxExecutor(
        runner_image="img",
        datasets_dir="datasets",
        server_url="http://127.0.0.1:5555",
    )
    assert ex._rpc_url() == "http://127.0.0.1:5555/api/v1/rpc"  # noqa: SLF001
    assert ex._health_url() == "http://127.0.0.1:5555/api/v1/health"  # noqa: SLF001


def test_microsandbox_executor_submit_sql_success(monkeypatch):
    calls = []

    def fake_rpc(self, method, params):  # noqa: ANN001
        calls.append((method, params))
        if method == "sandbox.start":
            return {"name": "sb-1"}
        if method == "sandbox.repl.run":
            return {
                "output": json.dumps(
                    {
                        "status": "success",
                        "columns": ["n"],
                        "rows": [[42]],
                        "row_count": 1,
                        "exec_time_ms": 10,
                        "stdout_trunc": "",
                        "stderr_trunc": "",
                        "error": None,
                    }
                )
            }
        if method == "sandbox.stop":
            return {"ok": True}
        raise AssertionError(method)

    monkeypatch.setattr(MicroSandboxExecutor, "_rpc", fake_rpc)
    monkeypatch.setattr(MicroSandboxExecutor, "_validate_connectivity", lambda self: None)

    ex = MicroSandboxExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        server_url="http://127.0.0.1:5555/api/v1/rpc",
        api_key="",
        namespace="default",
        timeout_seconds=10,
        max_rows=200,
        max_output_bytes=65536,
    )

    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "sql": "SELECT COUNT(*) AS n FROM tickets",
            "timeout_seconds": 10,
            "max_rows": 200,
            "max_output_bytes": 65536,
        },
        query_type="sql",
    )
    assert out["status"] == "succeeded"
    assert out["result"]["rows"] == [[42]]
    assert calls[0][0] == "sandbox.start"
    assert calls[0][1]["sandbox"] == "sb-1" or calls[0][1]["sandbox"].startswith("csv-analyst-")
    assert calls[-1][0] == "sandbox.stop"


def test_microsandbox_executor_submit_python_uses_python_runner(monkeypatch):
    captured_code = {"code": ""}

    def fake_rpc(self, method, params):  # noqa: ANN001
        if method == "sandbox.start":
            return {"name": "sb-2"}
        if method == "sandbox.repl.run":
            captured_code["code"] = params["code"]
            return {
                "output": json.dumps(
                    {
                        "status": "success",
                        "columns": ["value"],
                        "rows": [[1]],
                        "row_count": 1,
                        "exec_time_ms": 10,
                        "stdout_trunc": "",
                        "stderr_trunc": "",
                        "error": None,
                    }
                )
            }
        if method == "sandbox.stop":
            return {"ok": True}
        raise AssertionError(method)

    monkeypatch.setattr(MicroSandboxExecutor, "_rpc", fake_rpc)
    monkeypatch.setattr(MicroSandboxExecutor, "_validate_connectivity", lambda self: None)

    ex = MicroSandboxExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        server_url="http://127.0.0.1:5555/api/v1/rpc",
        api_key="",
        namespace="default",
    )

    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "python_code": "result = 1",
            "timeout_seconds": 10,
            "max_rows": 200,
            "max_output_bytes": 65536,
        },
        query_type="python",
    )
    assert out["status"] == "succeeded"
    assert "/app/runner_python.py" in captured_code["code"]


def test_microsandbox_executor_invalid_runner_json(monkeypatch):
    def fake_rpc(self, method, _params):  # noqa: ANN001
        if method == "sandbox.start":
            return {"name": "sb-3"}
        if method == "sandbox.repl.run":
            return {"output": "not-json"}
        if method == "sandbox.stop":
            return {"ok": True}
        raise AssertionError(method)

    monkeypatch.setattr(MicroSandboxExecutor, "_rpc", fake_rpc)
    monkeypatch.setattr(MicroSandboxExecutor, "_validate_connectivity", lambda self: None)

    ex = MicroSandboxExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        server_url="http://127.0.0.1:5555/api/v1/rpc",
        api_key="",
        namespace="default",
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "sql": "SELECT 1",
            "timeout_seconds": 10,
            "max_rows": 10,
            "max_output_bytes": 1024,
        },
        query_type="sql",
    )
    assert out["status"] == "failed"
    assert out["result"]["error"]["type"] == "RUNNER_INTERNAL_ERROR"


def test_microsandbox_executor_timeout_mapping(monkeypatch):
    def fake_rpc(self, method, _params):  # noqa: ANN001
        if method == "sandbox.start":
            return {"name": "sb-4"}
        if method == "sandbox.repl.run":
            raise RuntimeError("execution timeout exceeded")
        if method == "sandbox.stop":
            return {"ok": True}
        raise AssertionError(method)

    monkeypatch.setattr(MicroSandboxExecutor, "_rpc", fake_rpc)
    monkeypatch.setattr(MicroSandboxExecutor, "_validate_connectivity", lambda self: None)

    ex = MicroSandboxExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        server_url="http://127.0.0.1:5555/api/v1/rpc",
        api_key="",
        namespace="default",
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "sql": "SELECT 1",
            "timeout_seconds": 1,
            "max_rows": 10,
            "max_output_bytes": 1024,
        },
        query_type="sql",
    )
    assert out["status"] == "failed"
    assert out["result"]["status"] == "timeout"
    assert out["result"]["error"]["type"] == "RUNNER_TIMEOUT"
