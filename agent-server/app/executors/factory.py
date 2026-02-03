"""
Executor factory for selecting sandbox providers.
"""

from __future__ import annotations

from .base import Executor
from .docker_executor import DockerExecutor
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
    raise ValueError(f"Unsupported sandbox provider: {provider}")
