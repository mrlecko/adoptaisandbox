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


def _run_runner_python(payload: dict) -> tuple[int, dict, str]:
    """Execute Python runner entrypoint in same container image."""
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
        "--entrypoint",
        "python3",
        RUNNER_TEST_IMAGE,
        "/app/runner_python.py",
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
        pytest.fail(f"Python runner output is not valid JSON: {exc}; stdout={stdout!r}")

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


def test_python_runner_executes_dataframe_code():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
        "python_code": (
            "result_df = tickets.groupby('priority').size().reset_index(name='ticket_count')"
            ".sort_values('ticket_count', ascending=False)"
        ),
        "timeout_seconds": 10,
        "max_rows": 10,
        "max_output_bytes": 65536,
    }
    return_code, response, stderr = _run_runner_python(payload)

    assert return_code == 0, f"python runner failed: stderr={stderr}, response={response}"
    assert response.get("status") == "success"
    assert response.get("row_count", 0) > 0
    assert "priority" in response.get("columns", [])
    assert "ticket_count" in response.get("columns", [])


def test_python_runner_captures_trailing_expression_result():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
        "python_code": "1 + 2",
        "timeout_seconds": 10,
        "max_rows": 10,
        "max_output_bytes": 65536,
    }
    return_code, response, stderr = _run_runner_python(payload)

    assert return_code == 0, f"python runner failed: stderr={stderr}, response={response}"
    assert response.get("status") == "success"
    assert response.get("columns") == ["value"]
    assert response.get("rows") == [[3]]


def test_python_runner_blocks_dangerous_imports():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
        "python_code": "import os\nresult = 1",
        "timeout_seconds": 10,
        "max_rows": 10,
        "max_output_bytes": 65536,
    }
    return_code, response, _ = _run_runner_python(payload)

    assert return_code != 0
    assert response.get("status") == "error"
    assert response.get("error", {}).get("type") == "PYTHON_POLICY_VIOLATION"


def test_python_runner_classifies_timeouts():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
        "python_code": "while True:\n    pass",
        "timeout_seconds": 1,
        "max_rows": 10,
        "max_output_bytes": 65536,
    }
    return_code, response, _ = _run_runner_python(payload)

    assert return_code != 0
    assert response.get("status") == "timeout"
    assert response.get("error", {}).get("type") == "RUNNER_TIMEOUT"


def test_python_runner_enforces_output_byte_limit():
    payload = {
        "dataset_id": "support",
        "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
        "python_code": "result_rows = [[str(i) * 200] for i in range(100)]\nresult_columns = ['big']",
        "timeout_seconds": 10,
        "max_rows": 100,
        "max_output_bytes": 2048,
    }
    return_code, response, _ = _run_runner_python(payload)

    assert return_code == 0
    assert response.get("status") == "success"
    assert response.get("row_count", 0) < 100


def test_runner_container_blocks_network_egress():
    """Container runtime should block outbound networking with --network none."""
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "python3",
        RUNNER_TEST_IMAGE,
        "-c",
        (
            "import socket,sys;"
            "s=socket.socket();"
            "s.settimeout(1);"
            "ok=False\n"
            "try:\n"
            " s.connect(('1.1.1.1',53)); ok=True\n"
            "except Exception:\n"
            " ok=False\n"
            "sys.exit(1 if ok else 0)"
        ),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"network egress unexpectedly available: {proc.stderr}"
