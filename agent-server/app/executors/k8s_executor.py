"""
Kubernetes Job-backed executor implementation.

Runs one short-lived Job per query, fetches runner JSON from Pod logs, and
cleans up Job resources after completion.
"""

from __future__ import annotations

import ast
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException

from .base import Executor


class K8sJobExecutor(Executor):
    def __init__(
        self,
        runner_image: str,
        datasets_dir: str,
        namespace: str = "default",
        timeout_seconds: int = 10,
        max_rows: int = 200,
        max_output_bytes: int = 65536,
        service_account_name: str = "",
        image_pull_policy: str = "IfNotPresent",
        cpu_limit: str = "500m",
        memory_limit: str = "512Mi",
        datasets_pvc: str = "",
        job_ttl_seconds: int = 300,
        poll_interval_seconds: float = 0.25,
    ):
        self.runner_image = runner_image
        self.datasets_dir = datasets_dir
        self.namespace = namespace
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows
        self.max_output_bytes = max_output_bytes
        self.service_account_name = service_account_name.strip()
        self.image_pull_policy = image_pull_policy
        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit
        self.datasets_pvc = datasets_pvc.strip()
        self.job_ttl_seconds = job_ttl_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.keep_jobs = os.getenv("K8S_KEEP_JOBS", "false").strip().lower() == "true"

        self._status: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._job_names: Dict[str, str] = {}

        self.batch_api, self.core_api = self._create_clients()

    def _create_clients(self) -> tuple[Any, Any]:
        try:
            config.load_incluster_config()
        except ConfigException:
            try:
                config.load_kube_config()
            except Exception as exc:  # pragma: no cover - env dependent
                raise RuntimeError(
                    "Could not load Kubernetes config (in-cluster or local kubeconfig)."
                ) from exc
        return client.BatchV1Api(), client.CoreV1Api()

    def _job_name(self, run_id: str) -> str:
        return f"csv-analyst-{run_id[:8]}"

    def _runner_script(self, query_type: str) -> str:
        return "/app/runner_python.py" if query_type == "python" else "/app/runner.py"

    def _runner_bootstrap_code(self, query_type: str) -> str:
        runner_script = self._runner_script(query_type)
        return (
            "import os, subprocess, sys\n"
            "payload = os.environ.get('RUNNER_REQUEST_JSON', '')\n"
            f"proc = subprocess.run(['python3', '{runner_script}'], input=payload, text=True, capture_output=True)\n"
            "sys.stdout.write(proc.stdout or '')\n"
            "sys.exit(proc.returncode)\n"
        )

    def _build_job(
        self, *, job_name: str, payload: Dict[str, Any], query_type: str
    ) -> Any:
        timeout = int(payload.get("timeout_seconds", self.timeout_seconds))
        volumes = [
            client.V1Volume(name="tmp", empty_dir=client.V1EmptyDirVolumeSource())
        ]
        volume_mounts = [client.V1VolumeMount(name="tmp", mount_path="/tmp")]

        if self.datasets_pvc:
            volumes.append(
                client.V1Volume(
                    name="datasets",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=self.datasets_pvc
                    ),
                )
            )
            volume_mounts.append(
                client.V1VolumeMount(
                    name="datasets", mount_path="/data", read_only=True
                )
            )

        container = client.V1Container(
            name="runner",
            image=self.runner_image,
            image_pull_policy=self.image_pull_policy,
            command=["python3", "-c", self._runner_bootstrap_code(query_type)],
            env=[
                client.V1EnvVar(
                    name="RUNNER_REQUEST_JSON",
                    value=json.dumps(payload),
                ),
            ],
            volume_mounts=volume_mounts,
            resources=client.V1ResourceRequirements(
                limits={"cpu": self.cpu_limit, "memory": self.memory_limit},
                requests={"cpu": self.cpu_limit, "memory": self.memory_limit},
            ),
            security_context=client.V1SecurityContext(
                run_as_non_root=True,
                run_as_user=1000,
                run_as_group=1000,
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )

        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[container],
            volumes=volumes,
        )
        if self.service_account_name:
            pod_spec.service_account_name = self.service_account_name

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app.kubernetes.io/name": "csv-analyst-runner",
                    "app.kubernetes.io/managed-by": "csv-analyst-agent",
                }
            ),
            spec=pod_spec,
        )

        job_spec = client.V1JobSpec(
            template=template,
            backoff_limit=0,
            active_deadline_seconds=timeout + 5,
            ttl_seconds_after_finished=self.job_ttl_seconds,
        )
        return client.V1Job(
            metadata=client.V1ObjectMeta(name=job_name),
            spec=job_spec,
        )

    def _wait_for_job_terminal_state(
        self, *, job_name: str, timeout_seconds: int
    ) -> str:
        deadline = time.monotonic() + max(timeout_seconds + 5, 5)
        while time.monotonic() < deadline:
            job = self.batch_api.read_namespaced_job_status(
                name=job_name,
                namespace=self.namespace,
            )
            status = getattr(job, "status", None)
            if status and getattr(status, "succeeded", 0):
                return "succeeded"
            if status and getattr(status, "failed", 0):
                return "failed"
            time.sleep(self.poll_interval_seconds)
        return "timeout"

    def _read_job_logs(self, job_name: str) -> str:
        pods = self.core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"job-name={job_name}",
        )
        if not pods.items:
            return ""
        pod_name = pods.items[0].metadata.name
        return (
            self.core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
            )
            or ""
        )

    def _delete_job(self, job_name: str) -> None:
        try:
            self.batch_api.delete_namespaced_job(
                name=job_name,
                namespace=self.namespace,
                propagation_policy="Background",
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def _timeout_result(self, timeout_seconds: int) -> Dict[str, Any]:
        return {
            "status": "timeout",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "exec_time_ms": 0,
            "stdout_trunc": "",
            "stderr_trunc": "",
            "error": {
                "type": "RUNNER_TIMEOUT",
                "message": f"Query exceeded timeout of {timeout_seconds} seconds",
            },
        }

    @staticmethod
    def _is_parse_failure(result: Dict[str, Any]) -> bool:
        error = (result or {}).get("error") or {}
        message = str(error.get("message") or "").lower()
        return result.get("status") == "error" and (
            "empty stdout" in message or "invalid json" in message
        )

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

        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            pass

        # Some runner wrappers may emit Python literal repr output.
        try:
            literal = ast.literal_eval(trimmed)
            if isinstance(literal, dict):
                return literal
        except Exception:
            pass

        # Fallback: parse the first apparent JSON object from mixed log text.
        start = trimmed.find("{")
        end = trimmed.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(trimmed[start : end + 1])
            except json.JSONDecodeError:
                pass

        for line in reversed(trimmed.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                try:
                    literal = ast.literal_eval(line)
                    if isinstance(literal, dict):
                        return literal
                except Exception:
                    pass

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

    def submit_run(
        self, payload: Dict[str, Any], query_type: str = "sql"
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        timeout = int(payload.get("timeout_seconds", self.timeout_seconds))
        self._status[run_id] = {"run_id": run_id, "status": "running"}

        job_name = self._job_name(run_id)
        self._job_names[run_id] = job_name

        result: Dict[str, Any]
        try:
            job = self._build_job(
                job_name=job_name, payload=payload, query_type=query_type
            )
            self.batch_api.create_namespaced_job(namespace=self.namespace, body=job)

            terminal = self._wait_for_job_terminal_state(
                job_name=job_name,
                timeout_seconds=timeout,
            )
            stdout = self._read_job_logs(job_name)
            result = self._parse_runner_output(stdout, "")

            # Logs can lag very slightly after Job completion; retry parsing a few
            # times before classifying as a runner JSON failure.
            if terminal == "succeeded" and self._is_parse_failure(result):
                for _ in range(4):
                    time.sleep(0.2)
                    stdout = self._read_job_logs(job_name)
                    result = self._parse_runner_output(stdout, "")
                    if not self._is_parse_failure(result):
                        break

            if terminal == "timeout":
                result = self._timeout_result(timeout)
            elif terminal == "failed" and result.get("status") == "success":
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
                        "message": "Kubernetes Job failed before returning a valid result.",
                    },
                }
        except Exception as exc:
            is_timeout = "timeout" in str(exc).lower()
            result = {
                "status": "timeout" if is_timeout else "error",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 0,
                "stdout_trunc": "",
                "stderr_trunc": "",
                "error": {
                    "type": "RUNNER_TIMEOUT" if is_timeout else "RUNNER_INTERNAL_ERROR",
                    "message": str(exc),
                },
            }
        finally:
            if not self.keep_jobs:
                try:
                    self._delete_job(job_name)
                except Exception:
                    # Best-effort cleanup.
                    pass

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
        job_name = self._job_names.pop(run_id, None)
        if job_name:
            try:
                self._delete_job(job_name)
            except Exception:
                pass
        self._status.pop(run_id, None)
        self._results.pop(run_id, None)
