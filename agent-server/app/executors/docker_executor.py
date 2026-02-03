"""
Docker-backed executor implementation.

Uses Docker SDK for daemon connectivity/metadata and subprocess execution for
stdin payload delivery to the runner container.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import docker

from .base import Executor


class DockerExecutor(Executor):
    def __init__(
        self,
        runner_image: str,
        datasets_dir: str,
        timeout_seconds: int = 10,
        max_rows: int = 200,
        max_output_bytes: int = 65536,
    ):
        self.runner_image = runner_image
        self.datasets_dir = datasets_dir
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows
        self.max_output_bytes = max_output_bytes
        self._status: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self.client = None
        try:
            self.client = docker.from_env()
        except Exception:
            # Some environments lack docker SDK transport support for http+docker.
            # We fall back to docker CLI checks so execution still works.
            self.client = None

    def _check_docker_available(self) -> None:
        if self.client is not None:
            try:
                self.client.ping()
                return
            except Exception:
                pass

        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "Docker daemon is not reachable")

    def submit_run(
        self, payload: Dict[str, Any], query_type: str = "sql"
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        self._status[run_id] = {"run_id": run_id, "status": "running"}

        self._check_docker_available()

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
            f"{Path(self.datasets_dir).resolve()}:/data:ro",
        ]
        if query_type == "python":
            cmd.extend(["--entrypoint", "python3"])
        cmd.append(self.runner_image)
        if query_type == "python":
            cmd.append("/app/runner_python.py")

        proc = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            timeout=self.timeout_seconds + 5,
        )

        if not proc.stdout.strip():
            result = {
                "status": "error",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "stdout_trunc": "",
                "stderr_trunc": proc.stderr[:4096],
                "error": {
                    "type": "RUNNER_INTERNAL_ERROR",
                    "message": "Runner returned empty stdout.",
                },
            }
        else:
            try:
                result = json.loads(proc.stdout)
            except json.JSONDecodeError:
                result = {
                    "status": "error",
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "exec_time_ms": 0,
                    "stdout_trunc": proc.stdout[:4096],
                    "stderr_trunc": proc.stderr[:4096],
                    "error": {
                        "type": "RUNNER_INTERNAL_ERROR",
                        "message": "Runner returned invalid JSON.",
                    },
                }

        self._results[run_id] = result
        self._status[run_id] = {
            "run_id": run_id,
            "status": "succeeded" if result.get("status") == "success" else "failed",
        }
        return {
            "run_id": run_id,
            "status": self._status[run_id]["status"],
            "result": result,
        }

    def get_status(self, run_id: str) -> Dict[str, Any]:
        return self._status.get(run_id, {"run_id": run_id, "status": "not_found"})

    def get_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._results.get(run_id)

    def cleanup(self, run_id: str) -> None:
        self._status.pop(run_id, None)
        self._results.pop(run_id, None)
