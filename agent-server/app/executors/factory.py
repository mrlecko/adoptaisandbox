"""
Executor factory for selecting sandbox providers.
"""

from __future__ import annotations

from .base import Executor
from .docker_executor import DockerExecutor
from .k8s_executor import K8sJobExecutor
from .microsandbox_executor import MicroSandboxExecutor


def create_sandbox_executor(
    *,
    provider: str,
    runner_image: str,
    datasets_dir: str,
    timeout_seconds: int,
    max_rows: int,
    max_output_bytes: int,
    msb_server_url: str = "",
    msb_api_key: str = "",
    msb_namespace: str = "default",
    msb_memory_mb: int = 512,
    msb_cpus: float = 1.0,
    k8s_namespace: str = "default",
    k8s_service_account_name: str = "",
    k8s_image_pull_policy: str = "IfNotPresent",
    k8s_cpu_limit: str = "500m",
    k8s_memory_limit: str = "512Mi",
    k8s_datasets_pvc: str = "",
    k8s_job_ttl_seconds: int = 300,
    k8s_poll_interval_seconds: float = 0.25,
) -> Executor:
    normalized = (provider or "docker").strip().lower()
    if normalized == "docker":
        return DockerExecutor(
            runner_image=runner_image,
            datasets_dir=datasets_dir,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
            max_output_bytes=max_output_bytes,
        )
    if normalized == "microsandbox":
        return MicroSandboxExecutor(
            runner_image=runner_image,
            datasets_dir=datasets_dir,
            server_url=msb_server_url,
            api_key=msb_api_key,
            namespace=msb_namespace,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
            max_output_bytes=max_output_bytes,
            memory_mb=msb_memory_mb,
            cpus=msb_cpus,
        )
    if normalized == "k8s":
        return K8sJobExecutor(
            runner_image=runner_image,
            datasets_dir=datasets_dir,
            namespace=k8s_namespace,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
            max_output_bytes=max_output_bytes,
            service_account_name=k8s_service_account_name,
            image_pull_policy=k8s_image_pull_policy,
            cpu_limit=k8s_cpu_limit,
            memory_limit=k8s_memory_limit,
            datasets_pvc=k8s_datasets_pvc,
            job_ttl_seconds=k8s_job_ttl_seconds,
            poll_interval_seconds=k8s_poll_interval_seconds,
        )
    raise ValueError(f"Unsupported sandbox provider: {provider}")
