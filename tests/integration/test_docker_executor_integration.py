"""
Integration tests for DockerExecutor with the real runner container.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.docker_executor import DockerExecutor  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = REPO_ROOT / "datasets"
RUNNER_TEST_IMAGE = os.environ.get("RUNNER_TEST_IMAGE", "csv-analyst-runner:test")


def _docker_ready() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker binary is not installed"
    proc = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, proc.stderr.strip() or "docker daemon is not reachable"
    return True, ""


def _image_exists(image: str) -> bool:
    proc = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


@pytest.fixture(scope="module", autouse=True)
def require_docker_and_image():
    ok, reason = _docker_ready()
    if not ok:
        pytest.skip(f"Skipping DockerExecutor integration tests: {reason}")
    if not _image_exists(RUNNER_TEST_IMAGE):
        pytest.skip(
            f"Skipping DockerExecutor integration tests: image '{RUNNER_TEST_IMAGE}' not found."
        )


def test_docker_executor_executes_sql_query():
    ex = DockerExecutor(
        runner_image=RUNNER_TEST_IMAGE,
        datasets_dir=str(DATASETS_DIR),
        timeout_seconds=10,
        max_rows=20,
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "sql": "SELECT priority, COUNT(*) AS n FROM tickets GROUP BY priority ORDER BY n DESC",
            "timeout_seconds": 10,
            "max_rows": 20,
        },
        query_type="sql",
    )
    assert out["status"] == "succeeded"
    assert out["result"]["status"] == "success"
    assert out["result"]["row_count"] > 0
    run_id = out["run_id"]
    assert ex.get_status(run_id)["status"] == "succeeded"
    assert ex.get_result(run_id) is not None
    ex.cleanup(run_id)
    assert ex.get_status(run_id)["status"] == "not_found"


def test_docker_executor_executes_python_query():
    ex = DockerExecutor(
        runner_image=RUNNER_TEST_IMAGE,
        datasets_dir=str(DATASETS_DIR),
        timeout_seconds=10,
        max_rows=20,
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "python_code": (
                "result_df = tickets.groupby('priority').size()"
                ".reset_index(name='ticket_count').sort_values('ticket_count', ascending=False)"
            ),
            "timeout_seconds": 10,
            "max_rows": 20,
            "max_output_bytes": 65536,
        },
        query_type="python",
    )
    assert out["status"] == "succeeded"
    assert out["result"]["status"] == "success"
    assert "priority" in out["result"]["columns"]
