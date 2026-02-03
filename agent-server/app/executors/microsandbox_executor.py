"""
MicroSandbox-backed executor implementation.

This executor uses the MicroSandbox JSON-RPC API to start a sandbox, run the
existing runner entrypoint inside it, and return a normalized RunnerResponse.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
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

    def _runner_host_dir(self) -> Path:
        repo_root = Path(__file__).resolve().parents[3]
        runner_dir = repo_root / "runner"
        if not runner_dir.exists():
            raise RuntimeError(f"Runner directory not found for fallback execution: {runner_dir}")
        return runner_dir

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
        if response.status_code >= 400:
            raise RuntimeError(f"{method} HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        if payload.get("error"):
            message = payload["error"].get("message", "unknown RPC error")
            raise RuntimeError(f"{method} failed: {message}")
        return payload.get("result", {})

    def _start_sandbox(self, run_id: str) -> str:
        sandbox_name = f"csv-analyst-{run_id[:8]}"
        volumes = [f"{Path(self.datasets_dir).resolve()}:/data"]
        self._rpc(
            "sandbox.start",
            {
                "sandbox": sandbox_name,
                "namespace": self.namespace,
                "config": {
                    "image": self.runner_image,
                    "memory": self.memory_mb,
                    "cpus": max(1, int(round(self.cpus))),
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

    def _should_attempt_cli_fallback(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        if "not reachable" in msg:
            return False
        return any(
            token in msg
            for token in [
                "http 400",
                "http 401",
                "http 403",
                "http 404",
                "http 500",
                "unauthorized",
                "unsupported registry",
                "failed to connect to portal",
                "internal server error",
            ]
        )

    def _build_fallback_script(self, payload: Dict[str, Any], query_type: str) -> str:
        runner_path = "/app/runner_python.py" if query_type == "python" else "/app/runner.py"
        payload_json = json.dumps(payload)
        timeout_seconds = int(payload.get("timeout_seconds", self.timeout_seconds))
        process_timeout = timeout_seconds + 2
        return (
            "import json, subprocess, sys\n"
            "subprocess.run([\n"
            "    'python3',\n"
            "    '-m',\n"
            "    'pip',\n"
            "    'install',\n"
            "    '--quiet',\n"
            "    '--disable-pip-version-check',\n"
            "    '--no-cache-dir',\n"
            "    '-r',\n"
            "    '/app/requirements.txt',\n"
            "], check=True)\n"
            f"payload = {payload_json!r}\n"
            f"cmd = ['python3', '{runner_path}']\n"
            "try:\n"
            f"    proc = subprocess.run(cmd, input=payload, text=True, capture_output=True, timeout={process_timeout})\n"
            "    sys.stdout.write(proc.stdout or '')\n"
            "    sys.stderr.write(proc.stderr or '')\n"
            "except subprocess.TimeoutExpired:\n"
            "    sys.stdout.write(json.dumps({\n"
            "        'status': 'timeout',\n"
            "        'columns': [],\n"
            "        'rows': [],\n"
            "        'row_count': 0,\n"
            "        'exec_time_ms': 0,\n"
            "        'stdout_trunc': '',\n"
            "        'stderr_trunc': '',\n"
            "        'error': {\n"
            "            'type': 'RUNNER_TIMEOUT',\n"
            f"            'message': 'Query exceeded timeout of {timeout_seconds} seconds',\n"
            "        },\n"
            "    }))\n"
        )

    def _run_via_cli_fallback(self, payload: Dict[str, Any], query_type: str) -> Dict[str, Any]:
        msb_cli = os.getenv("MSB_CLI_PATH") or str(Path.home() / ".local" / "bin" / "msb")
        if not Path(msb_cli).exists():
            msb_cli = "msb"

        fallback_image = os.getenv("MSB_FALLBACK_IMAGE", "python:3.11-slim")
        datasets_dir = Path(self.datasets_dir).resolve()
        runner_dir = self._runner_host_dir().resolve()
        timeout = int(payload.get("timeout_seconds", self.timeout_seconds))

        with tempfile.TemporaryDirectory(prefix="msb_exec_") as tmp_dir:
            script_path = Path(tmp_dir) / "execute_runner.py"
            script_path.write_text(self._build_fallback_script(payload, query_type), encoding="utf-8")

            cmd = [
                msb_cli,
                "exe",
                "--memory",
                str(int(self.memory_mb)),
                "--cpus",
                str(max(1, int(round(self.cpus)))),
                "--env",
                "PIP_DISABLE_PIP_VERSION_CHECK=1",
                "-v",
                f"{datasets_dir}:/data",
                "-v",
                f"{runner_dir}:/app",
                "-v",
                f"{tmp_dir}:/tmp",
                "-e",
                "python3",
                fallback_image,
                "--",
                "/tmp/execute_runner.py",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=max(timeout + 5, 120),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"cli fallback timeout: {exc}") from exc

            return self._parse_runner_output(proc.stdout or "", proc.stderr or "")

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
            if self._should_attempt_cli_fallback(exc):
                try:
                    result = self._run_via_cli_fallback(payload, query_type)
                except Exception as fallback_exc:
                    result = {
                        "status": "error",
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "exec_time_ms": 0,
                        "stdout_trunc": "",
                        "stderr_trunc": "",
                        "error": {
                            "type": "RUNNER_INTERNAL_ERROR",
                            "message": (
                                f"{exc} | cli fallback failed: {fallback_exc}"
                            ),
                        },
                    }
            else:
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
