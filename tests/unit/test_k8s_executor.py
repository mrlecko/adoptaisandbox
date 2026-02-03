import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.k8s_executor import ConfigException, K8sJobExecutor  # noqa: E402


class _FakeBatchApi:
    def __init__(self, *, terminal_state: str = "succeeded"):
        self.terminal_state = terminal_state
        self.created = None
        self.deleted = []

    def create_namespaced_job(self, namespace, body):  # noqa: ANN001
        self.created = (namespace, body)
        return body

    def read_namespaced_job_status(self, name, namespace):  # noqa: ANN001
        _ = (name, namespace)
        succeeded = 1 if self.terminal_state == "succeeded" else 0
        failed = 1 if self.terminal_state == "failed" else 0
        return SimpleNamespace(
            status=SimpleNamespace(succeeded=succeeded, failed=failed)
        )

    def delete_namespaced_job(
        self, name, namespace, propagation_policy
    ):  # noqa: ANN001
        self.deleted.append((name, namespace, propagation_policy))
        return None


class _FakeCoreApi:
    def __init__(self, logs: str):
        self.logs = logs

    def list_namespaced_pod(self, namespace, label_selector):  # noqa: ANN001
        _ = (namespace, label_selector)
        pod = SimpleNamespace(metadata=SimpleNamespace(name="runner-pod-1"))
        return SimpleNamespace(items=[pod])

    def read_namespaced_pod_log(self, name, namespace):  # noqa: ANN001
        _ = (name, namespace)
        return self.logs


def test_k8s_executor_submit_run_sql_success(monkeypatch):
    fake_batch = _FakeBatchApi(terminal_state="succeeded")
    fake_core = _FakeCoreApi(
        logs=json.dumps(
            {
                "status": "success",
                "columns": ["n"],
                "rows": [[9]],
                "row_count": 1,
                "exec_time_ms": 3,
                "stdout_trunc": "",
                "stderr_trunc": "",
                "error": None,
            }
        )
    )
    monkeypatch.setattr(
        K8sJobExecutor,
        "_create_clients",
        lambda self: (fake_batch, fake_core),
    )

    ex = K8sJobExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        namespace="csv-analyst",
        timeout_seconds=10,
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "sql": "SELECT COUNT(*) AS n FROM tickets",
            "timeout_seconds": 10,
            "max_rows": 10,
            "max_output_bytes": 1024,
        },
        query_type="sql",
    )

    assert out["status"] == "succeeded"
    assert out["result"]["rows"] == [[9]]
    assert fake_batch.created is not None
    namespace, job = fake_batch.created
    assert namespace == "csv-analyst"
    container = job.spec.template.spec.containers[0]
    assert "/app/runner.py" in container.command[-1]
    assert "sys.stderr.write" not in container.command[-1]
    assert container.security_context.run_as_non_root is True
    assert container.security_context.run_as_user == 1000
    env_names = [entry.name for entry in container.env]
    assert "RUNNER_REQUEST_JSON" in env_names
    mounts = {mount.mount_path for mount in container.volume_mounts}
    assert "/tmp" in mounts
    assert fake_batch.deleted, "expected Job cleanup call"


def test_k8s_executor_submit_run_python_uses_python_runner(monkeypatch):
    fake_batch = _FakeBatchApi(terminal_state="succeeded")
    fake_core = _FakeCoreApi(
        logs=json.dumps(
            {
                "status": "success",
                "columns": ["value"],
                "rows": [[1]],
                "row_count": 1,
                "exec_time_ms": 3,
                "stdout_trunc": "",
                "stderr_trunc": "",
                "error": None,
            }
        )
    )
    monkeypatch.setattr(
        K8sJobExecutor,
        "_create_clients",
        lambda self: (fake_batch, fake_core),
    )

    ex = K8sJobExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        namespace="csv-analyst",
        timeout_seconds=10,
    )
    out = ex.submit_run(
        payload={
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "python_code": "result = 1",
            "timeout_seconds": 10,
            "max_rows": 10,
            "max_output_bytes": 1024,
        },
        query_type="python",
    )

    assert out["status"] == "succeeded"
    _, job = fake_batch.created
    container = job.spec.template.spec.containers[0]
    assert "/app/runner_python.py" in container.command[-1]


def test_k8s_executor_timeout_maps_to_runner_timeout(monkeypatch):
    fake_batch = _FakeBatchApi(terminal_state="succeeded")
    fake_core = _FakeCoreApi(logs="")
    monkeypatch.setattr(
        K8sJobExecutor,
        "_create_clients",
        lambda self: (fake_batch, fake_core),
    )
    monkeypatch.setattr(
        K8sJobExecutor,
        "_wait_for_job_terminal_state",
        lambda self, **_kwargs: "timeout",
    )

    ex = K8sJobExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        namespace="csv-analyst",
        timeout_seconds=1,
        poll_interval_seconds=0.01,
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


def test_k8s_executor_parses_json_from_mixed_log_text(monkeypatch):
    fake_batch = _FakeBatchApi(terminal_state="succeeded")
    mixed_logs = (
        "some non-json prefix\n"
        '{"status":"success","columns":["n"],"rows":[[1]],"row_count":1,'
        '"exec_time_ms":5,"stdout_trunc":"","stderr_trunc":"","error":null}\n'
        "trailing note"
    )
    fake_core = _FakeCoreApi(logs=mixed_logs)
    monkeypatch.setattr(
        K8sJobExecutor,
        "_create_clients",
        lambda self: (fake_batch, fake_core),
    )

    ex = K8sJobExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        namespace="csv-analyst",
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
    assert out["status"] == "succeeded"
    assert out["result"]["rows"] == [[1]]


def test_k8s_executor_parses_python_literal_dict_logs(monkeypatch):
    fake_batch = _FakeBatchApi(terminal_state="succeeded")
    literal_logs = (
        "{'status': 'success', 'columns': ['n'], 'rows': [[2]], 'row_count': 1, "
        "'exec_time_ms': 5, 'stdout_trunc': '', 'stderr_trunc': '', 'error': None}"
    )
    fake_core = _FakeCoreApi(logs=literal_logs)
    monkeypatch.setattr(
        K8sJobExecutor,
        "_create_clients",
        lambda self: (fake_batch, fake_core),
    )

    ex = K8sJobExecutor(
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        namespace="csv-analyst",
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
    assert out["status"] == "succeeded"
    assert out["result"]["rows"] == [[2]]


def test_k8s_executor_requires_kube_config(monkeypatch):
    monkeypatch.setattr(
        "app.executors.k8s_executor.config.load_incluster_config",
        lambda: (_ for _ in ()).throw(ConfigException("no incluster config")),
    )
    monkeypatch.setattr(
        "app.executors.k8s_executor.config.load_kube_config",
        lambda: (_ for _ in ()).throw(Exception("no kubeconfig")),
    )

    with pytest.raises(RuntimeError, match="Could not load Kubernetes config"):
        K8sJobExecutor(
            runner_image="csv-analyst-runner:test",
            datasets_dir="datasets",
            namespace="csv-analyst",
        )
