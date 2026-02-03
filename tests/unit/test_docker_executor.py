import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.docker_executor import DockerExecutor  # noqa: E402


class _FakeDockerClient:
    def __init__(self):
        self.ping_called = False

    def ping(self):
        self.ping_called = True


def test_docker_executor_submit_run_sql(monkeypatch, tmp_path):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(
        "app.executors.docker_executor.docker.from_env",
        lambda: fake_client,
    )

    captured = {"cmd": None}

    def fake_subprocess_run(*args, **_kwargs):
        captured["cmd"] = args[0]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "status": "success",
                    "columns": ["n"],
                    "rows": [[42]],
                    "row_count": 1,
                    "exec_time_ms": 1,
                    "stdout_trunc": "",
                    "stderr_trunc": "",
                    "error": None,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("app.executors.docker_executor.subprocess.run", fake_subprocess_run)

    ex = DockerExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir=str(tmp_path),
        timeout_seconds=5,
        max_rows=10,
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "sql": "SELECT COUNT(*) AS n FROM tickets",
        },
        query_type="sql",
    )
    assert fake_client.ping_called is True
    assert captured["cmd"] is not None
    assert "--network" in captured["cmd"]
    assert "none" in captured["cmd"]
    assert "--read-only" in captured["cmd"]
    assert "--tmpfs" in captured["cmd"]
    assert out["status"] == "succeeded"
    run_id = out["run_id"]
    assert ex.get_status(run_id)["status"] == "succeeded"
    assert ex.get_result(run_id)["status"] == "success"
    ex.cleanup(run_id)
    assert ex.get_status(run_id)["status"] == "not_found"


def test_docker_executor_submit_run_python_uses_entrypoint(monkeypatch, tmp_path):
    fake_client = _FakeDockerClient()
    monkeypatch.setattr(
        "app.executors.docker_executor.docker.from_env",
        lambda: fake_client,
    )

    captured = {"cmd": None}

    def fake_subprocess_run(*args, **_kwargs):
        captured["cmd"] = args[0]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "status": "success",
                    "columns": ["value"],
                    "rows": [[1]],
                    "row_count": 1,
                    "exec_time_ms": 1,
                    "stdout_trunc": "",
                    "stderr_trunc": "",
                    "error": None,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("app.executors.docker_executor.subprocess.run", fake_subprocess_run)

    ex = DockerExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir=str(tmp_path),
        timeout_seconds=5,
        max_rows=10,
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "python_code": "result = 1",
        },
        query_type="python",
    )

    assert fake_client.ping_called is True
    assert out["status"] == "succeeded"
    assert "--entrypoint" in captured["cmd"]
    assert "python3" in captured["cmd"]
    assert "/app/runner_python.py" in captured["cmd"]
