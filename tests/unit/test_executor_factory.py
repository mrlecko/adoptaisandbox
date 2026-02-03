from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors import create_sandbox_executor  # noqa: E402
from app.executors.docker_executor import DockerExecutor  # noqa: E402
from app.executors.k8s_executor import K8sJobExecutor  # noqa: E402
from app.executors.microsandbox_executor import MicroSandboxExecutor  # noqa: E402


def test_create_sandbox_executor_docker():
    ex = create_sandbox_executor(
        provider="docker",
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        timeout_seconds=10,
        max_rows=200,
        max_output_bytes=65536,
    )
    assert isinstance(ex, DockerExecutor)


def test_create_sandbox_executor_microsandbox():
    ex = create_sandbox_executor(
        provider="microsandbox",
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        timeout_seconds=10,
        max_rows=200,
        max_output_bytes=65536,
        msb_server_url="http://127.0.0.1:5555/api/v1/rpc",
        msb_api_key="",
        msb_namespace="default",
        msb_memory_mb=512,
        msb_cpus=1.0,
    )
    assert isinstance(ex, MicroSandboxExecutor)


def test_create_sandbox_executor_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported sandbox provider"):
        create_sandbox_executor(
            provider="unknown",
            runner_image="csv-analyst-runner:test",
            datasets_dir="datasets",
            timeout_seconds=10,
            max_rows=200,
            max_output_bytes=65536,
        )


def test_create_sandbox_executor_k8s(monkeypatch):
    monkeypatch.setattr(
        "app.executors.k8s_executor.K8sJobExecutor._create_clients",
        lambda self: (object(), object()),
    )
    ex = create_sandbox_executor(
        provider="k8s",
        runner_image="csv-analyst-runner:test",
        datasets_dir="datasets",
        timeout_seconds=10,
        max_rows=200,
        max_output_bytes=65536,
        k8s_namespace="csv-analyst",
    )
    assert isinstance(ex, K8sJobExecutor)
