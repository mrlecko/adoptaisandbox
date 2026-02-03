"""
MicroSandbox-backed executor implementation.

This executor uses the MicroSandbox JSON-RPC API to start a sandbox, run the
existing runner entrypoint inside it, and return a normalized RunnerResponse.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from .base import Executor


class MicroSandboxExecutor(Executor):
    def __init__(
        self,
        runner_image: str,
        datasets_dir: str,
        server_url: str,
        api_key: str = "",
        namespace: str = "default",
        timeout_seconds: int = 10,
        max_rows: int = 200,
        max_output_bytes: int = 65536,
        memory_mb: int = 512,
        cpus: float = 1.0,
    ):
        self.runner_image = runner_image
        self.datasets_dir = datasets_dir
        self.server_url = server_url
        self.api_key = api_key
        self.namespace = namespace
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows
        self.max_output_bytes = max_output_bytes
        self.memory_mb = memory_mb
        self.cpus = cpus

        self._status: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}

    def _rpc_url(self) -> str:
        server = self.server_url.strip()
        if not server:
            raise RuntimeError("MSB_SERVER_URL is required for MicroSandbox provider")
        if server.endswith("/api/v1/rpc"):
            return server
        if server.endswith("/"):
            server = server[:-1]
        if server.endswith("/api/v1"):
            return f"{server}/rpc"
        if "/api/v1/" in server:
            return server
        return f"{server}/api/v1/rpc"

    def _health_url(self) -> str:
        rpc = self._rpc_url()
        if rpc.endswith("/rpc"):
            return f"{rpc[:-4]}/health"
        parsed = urlparse(rpc)
        base = f"{parsed.scheme}://{parsed.netloc}"
        return f"{base}/api/v1/health"

    def _validate_connectivity(self) -> None:
        try:
            health = httpx.get(self._health_url(), timeout=10)
            health.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                "MicroSandbox server is not reachable. "
                f"Check MSB_SERVER_URL and server status: {exc}"
            ) from exc

    def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request_body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        response = httpx.post(
            self._rpc_url(),
            json=request_body,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            message = payload["error"].get("message", "unknown RPC error")
            raise RuntimeError(f"{method} failed: {message}")
        return payload.get("result", {})

    def _start_sandbox(self, run_id: str) -> str:
        sandbox_name = f"csv-analyst-{run_id[:8]}"
        volumes = [f"{Path(self.datasets_dir).resolve()}:/data:ro"]
        self._rpc(
            "sandbox.start",
            {
                "sandbox": sandbox_name,
                "namespace": self.namespace,
                "config": {
                    "image": self.runner_image,
                    "memory": self.memory_mb,
                    "cpus": self.cpus,
                    "volumes": volumes,
                },
            },
        )
        return sandbox_name

    def _build_runner_code(self, payload: Dict[str, Any], query_type: str) -> str:
        runner_path = "/app/runner_python.py" if query_type == "python" else "/app/runner.py"
        payload_str = json.dumps(payload)
        timeout = int(payload.get("timeout_seconds", self.timeout_seconds)) + 5
        return (
            "import subprocess, sys\n"
            f"payload = {payload_str!r}\n"
            f"cmd = ['python3', '{runner_path}']\n"
            f"proc = subprocess.run(cmd, input=payload, text=True, capture_output=True, timeout={timeout})\n"
            "sys.stdout.write(proc.stdout or '')\n"
            "sys.stderr.write(proc.stderr or '')\n"
        )

    def _extract_output(self, repl_result: Dict[str, Any]) -> tuple[str, str]:
        stdout = (
            repl_result.get("output")
            or repl_result.get("stdout")
            or repl_result.get("result")
            or ""
        )
        stderr = repl_result.get("stderr") or ""
        return str(stdout), str(stderr)

    def _parse_runner_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        trimmed = stdout.strip()
        if not trimmed:
            return {
                "status": "error",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "stdout_trunc": "",
                "stderr_trunc": stderr[:4096],
                "error": {
                    "type": "RUNNER_INTERNAL_ERROR",
                    "message": "Runner returned empty stdout.",
                },
            }

        # Try full payload first, then fallback to last JSON line.
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            pass

        for line in reversed(trimmed.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        return {
            "status": "error",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 0,
            "stdout_trunc": trimmed[:4096],
            "stderr_trunc": stderr[:4096],
            "error": {
                "type": "RUNNER_INTERNAL_ERROR",
                "message": "Runner returned invalid JSON.",
            },
        }

    def submit_run(self, payload: Dict[str, Any], query_type: str = "sql") -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        self._status[run_id] = {"run_id": run_id, "status": "running"}
        sandbox_name: Optional[str] = None

        try:
            self._validate_connectivity()
            sandbox_name = self._start_sandbox(run_id)
            repl_result = self._rpc(
                "sandbox.repl.run",
                {
                    "sandbox": sandbox_name,
                    "namespace": self.namespace,
                    "language": "python",
                    "code": self._build_runner_code(payload, query_type),
                    "timeout": int(payload.get("timeout_seconds", self.timeout_seconds)) + 5,
                },
            )
            stdout, stderr = self._extract_output(repl_result)
            result = self._parse_runner_output(stdout, stderr)
        except Exception as exc:
            error_type = "RUNNER_INTERNAL_ERROR"
            status = "error"
            if "timeout" in str(exc).lower():
                error_type = "RUNNER_TIMEOUT"
                status = "timeout"
            result = {
                "status": status,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "stdout_trunc": "",
                "stderr_trunc": "",
                "error": {
                    "type": error_type,
                    "message": str(exc),
                },
            }
        finally:
            if sandbox_name:
                try:
                    self._rpc(
                    "sandbox.stop",
                    {
                        "sandbox": sandbox_name,
                        "namespace": self.namespace,
                    },
                )
                except Exception:
                    # Best effort cleanup.
                    pass

        self._results[run_id] = result
        self._status[run_id] = {
            "run_id": run_id,
            "status": "succeeded" if result.get("status") == "success" else "failed",
        }
        return {"run_id": run_id, "status": self._status[run_id]["status"], "result": result}

    def get_status(self, run_id: str) -> Dict[str, Any]:
        return self._status.get(run_id, {"run_id": run_id, "status": "not_found"})

    def get_result(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._results.get(run_id)

    def cleanup(self, run_id: str) -> None:
        self._status.pop(run_id, None)
        self._results.pop(run_id, None)
