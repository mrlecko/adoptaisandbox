"""
Integration tests for the sandboxed runner container.

These tests validate that CSV datasets can be loaded and queried, and that
runner hardening controls behave as expected.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = REPO_ROOT / "datasets"
RUNNER_TEST_IMAGE = os.environ.get("RUNNER_TEST_IMAGE", "csv-analyst-runner:test")


def _docker_ready() -> tuple[bool, str]:
    """Return whether Docker is available and daemon is reachable."""
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


@pytest.fixture(scope="module", autouse=True)
def require_docker_and_datasets():
    """Skip module if Docker or datasets are unavailable."""
    ok, reason = _docker_ready()
    if not ok:
        pytest.skip(f"Skipping runner integration tests: {reason}")

    required = [
        DATASETS_DIR / "ecommerce" / "orders.csv",
        DATASETS_DIR / "ecommerce" / "order_items.csv",
        DATASETS_DIR / "ecommerce" / "inventory.csv",
        DATASETS_DIR / "support" / "tickets.csv",
        DATASETS_DIR / "sensors" / "sensors.csv",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        pytest.skip(f"Skipping runner integration tests, missing datasets: {missing}")


def _run_runner(payload: dict) -> tuple[int, dict, str]:
    """Execute the runner container with sandbox flags and return parsed output."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--cpus",
        "0.5",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-v",
        f"{DATASETS_DIR}:/data:ro",
        RUNNER_TEST_IMAGE,
    ]
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )

    stdout = proc.stdout.strip()
    try:
        response = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        pytest.fail(f"Runner output is not valid JSON: {exc}; stdout={stdout!r}")

    return proc.returncode, response, proc.stderr.strip()


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        (
            "ecommerce_join",
            {
                "dataset_id": "ecommerce",
                "files": [
                    {"name": "orders.csv", "path": "/data/ecommerce/orders.csv"},
                    {"name": "order_items.csv", "path": "/data/ecommerce/order_items.csv"},
                    {"name": "inventory.csv", "path": "/data/ecommerce/inventory.csv"},
                ],
                "sql": (
                    "SELECT i.category, COUNT(*) AS line_items "
                    "FROM order_items oi "
                    "JOIN inventory i ON i.product_id = oi.product_id "
                    "GROUP BY i.category ORDER BY line_items DESC"
                ),
                "timeout_seconds": 10,
                "max_rows": 20,
            },
        ),
        (
            "support_aggregate",
            {
                "dataset_id": "support",
                "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
                "sql": (
                    "SELECT priority, COUNT(*) AS tickets "
                    "FROM tickets GROUP BY priority ORDER BY tickets DESC"
                ),
                "timeout_seconds": 10,
                "max_rows": 20,
            },
        ),
        (
            "sensors_aggregate",
            {
                "dataset_id": "sensors",
                "files": [{"name": "sensors.csv", "path": "/data/sensors/sensors.csv"}],
                "sql": (
                    "SELECT zone, SUM(CASE WHEN anomaly_flag THEN 1 ELSE 0 END) AS anomalies "
                    "FROM sensors GROUP BY zone ORDER BY anomalies DESC"
                ),
                "timeout_seconds": 10,
                "max_rows": 20,
            },
        ),
    ],
)
def test_runner_executes_queries(name: str, payload: dict):
    """Runner should load CSVs and return query results for all datasets."""
    return_code, response, stderr = _run_runner(payload)

    assert return_code == 0, f"{name} failed: stderr={stderr}, response={response}"
    assert response.get("status") == "success"
    assert response.get("row_count", 0) > 0
    assert isinstance(response.get("columns"), list)
    assert isinstance(response.get("rows"), list)


def test_runner_rejects_path_outside_data_root():
    payload = {
        "dataset_id": "ecommerce",
        "files": [{"name": "orders.csv", "path": "/etc/passwd"}],
        "sql": "SELECT * FROM orders LIMIT 1",
        "timeout_seconds": 10,
        "max_rows": 10,
    }
    return_code, response, _ = _run_runner(payload)

    assert return_code != 0
    assert response.get("status") == "error"
    assert "under /data" in response.get("error", {}).get("message", "")


def test_runner_rejects_relative_csv_path():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets.csv", "path": "support/tickets.csv"}],
        "sql": "SELECT COUNT(*) FROM tickets",
        "timeout_seconds": 10,
        "max_rows": 10,
    }
    return_code, response, _ = _run_runner(payload)

    assert return_code != 0
    assert response.get("status") == "error"
    assert "must be absolute" in response.get("error", {}).get("message", "")


def test_runner_rejects_unsafe_table_name():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets;drop", "path": "/data/support/tickets.csv"}],
        "sql": "SELECT COUNT(*) FROM tickets",
        "timeout_seconds": 10,
        "max_rows": 10,
    }
    return_code, response, _ = _run_runner(payload)

    assert return_code != 0
    assert response.get("status") == "error"
    assert "Invalid table name" in response.get("error", {}).get("message", "")


def test_runner_classifies_timeouts():
    payload = {
        "dataset_id": "ecommerce",
        "files": [{"name": "orders.csv", "path": "/data/ecommerce/orders.csv"}],
        "sql": "SELECT SUM(random()) FROM range(500000000)",
        "timeout_seconds": 1,
        "max_rows": 10,
    }
    return_code, response, _ = _run_runner(payload)

    assert return_code != 0
    assert response.get("status") == "timeout"
    assert response.get("error", {}).get("type") == "RUNNER_TIMEOUT"
    assert response.get("exec_time_ms", 0) >= 900
