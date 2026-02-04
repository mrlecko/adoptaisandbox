# SANDBOXING_DISCUSSION.md

## Purpose

This document provides a senior-level technical discussion of the two sandbox execution paths in this project:

1. `SANDBOX_PROVIDER=docker`
2. `SANDBOX_PROVIDER=microsandbox`

It focuses on production tradeoffs, hardening work required, estimated level-of-effort (LoE), and practical risks.

---

## Current Architecture Snapshot (As Implemented)

The agent server executes SQL/Python workloads by sending JSON payloads to a sandbox runner image (`csv-analyst-runner:*`), with two provider implementations:

- **DockerExecutor** (`agent-server/app/executors/docker_executor.py`)
  - Runs `docker run --rm -i ...` per request.
  - Mounts datasets as read-only (`-v <datasets>:/data:ro`).
  - Applies runtime flags: `--network none`, `--read-only`, `--pids-limit 64`, `--memory 512m`, `--cpus 0.5`, tmpfs `/tmp`.
  - Uses same runner image for SQL and Python (Python path via entrypoint override).

- **MicroSandboxExecutor** (`agent-server/app/executors/microsandbox_executor.py`)
  - Calls MicroSandbox JSON-RPC (`sandbox.start` -> `sandbox.repl.run` -> `sandbox.stop`).
  - Uses API key auth (Bearer token) when configured.
  - Mounts datasets and runs the same runner scripts inside sandbox.
  - Has CLI fallback (`msb exe`) if RPC path fails for selected classes of errors.

Shared characteristics:

- Same runner contracts (`runner.py`, `runner_python.py`).
- Same API response contract at agent server boundary.
- Same SQL policy checks and Python policy checks before execution.

---

## What "Production Grade" Means Here

For this project, "production grade" should mean:

1. **Security hardening**: least privilege, strong isolation, policy enforcement, auditable controls.
2. **Reliability**: predictable behavior under load/failure; graceful degradation.
3. **Scalability**: concurrency model that supports expected QPS and burst.
4. **Observability**: traces/metrics/logs with run-level correlation.
5. **Operability**: easy deployment, upgrade, rollback, and incident response.
6. **Compliance posture**: secret handling, data boundary controls, retention posture.

---

## Option A: Docker Sandbox

## Execution Model

Each query starts a short-lived container directly from the agent server host via Docker CLI/daemon. The container reads request JSON on stdin, executes, returns JSON on stdout, then exits.

## Strengths

- **Simple mental model**: very low conceptual overhead.
- **Strong local determinism**: ideal for demos, local dev, CI integration tests.
- **No additional control plane dependency**: fewer moving parts than external sandbox services.
- **Clear runtime controls already present**: network disabled, read-only rootfs, constrained memory/cpu/pids, read-only data mount.
- **Excellent debuggability**: easy to reproduce with local `docker run`.

## Weaknesses / Risks in Production

- **Host-level blast radius**: agent needs effective access to Docker daemon; compromise of app process can become host compromise if not heavily constrained.
- **Multi-tenant weakness**: direct Docker daemon usage is usually not ideal for strict tenant isolation.
- **Scalability bottlenecks**: per-request container startup overhead; no queue or asynchronous scheduler.
- **State is process-local**: executor status/result caches are in-memory dictionaries, not distributed across replicas.
- **Policy consistency drift risk**: Docker flags live in app code; drift across environments if not centrally enforced.
- **Operational coupling**: app lifecycle tied directly to container runtime health on same node.

## Production Hardening Work (Docker Path)

1. **Runtime isolation uplift**
   - Rootless runtime, seccomp/AppArmor profiles, drop all Linux capabilities explicitly, consider gVisor/Kata.
2. **Execution control plane**
   - Move run submission to queue + worker pool (or K8s Jobs) to decouple API latency from sandbox lifecycle.
3. **Distributed run state**
   - Persist status/results in durable backend (already partly present via capsules, but executor runtime state is local).
4. **Admission + policy guardrails**
   - Centralize allowed images, runner signature verification, immutable tags/digests.
5. **Observability + SLOs**
   - Run-level metrics: startup latency, failure class, timeout rates, p95/p99 by query type.
6. **Secrets + host hardening**
   - Do not expose broad docker socket to app; broker execution through constrained service account or sidecar pattern.

## Docker Production LoE (from current state)

LoE scale: 1 point ~= 0.5 engineer-day of focused implementation + validation.

- Security hardening: **12-16 pts**
- Reliability/scaling refactor (queue/worker/state): **14-20 pts**
- Observability/SLO + alerting: **6-10 pts**
- CI/CD + release guardrails: **4-6 pts**

**Total Docker path LoE: 36-52 pts** (~3.5 to 6.5 engineer-weeks for one senior engineer; faster with 2 engineers).

## Docker Production Limitations

- Still less ideal than managed/isolated sandbox platforms for strict multi-tenant untrusted code.
- Organizational security teams often reject app->docker-daemon models in internet-facing services.
- Tight security posture often pushes architecture toward orchestrated job backends anyway.

---

## Option B: MicroSandbox

## Execution Model

The agent calls a remote sandbox control plane over RPC, starts a named sandbox, executes runner logic via REPL command, parses output, then stops the sandbox. Auth is token-based (`MSB_API_KEY`).

## Strengths

- **Control-plane separation**: sandbox lifecycle managed outside the app process.
- **Better isolation story potential**: if MicroSandbox runtime policy is hardened centrally.
- **Cleaner multi-host story**: app and sandbox runtime can scale independently.
- **Operational leverage**: central policy, auth, and sandbox telemetry can be standardized.
- **Good long-term fit** for remote/prod-like environments and shared infrastructure.

## Weaknesses / Risks in Production

- **Dependency on external sandbox service**: adds network, auth, and service availability risk.
- **Latency overhead**: start/execute/stop over RPC per run.
- **Fallback complexity**: CLI fallback can diverge behavior and currently installs requirements at runtime in fallback flow (slow, supply-chain risk, non-deterministic).
- **Resource mapping simplification**: CPU is rounded to integer in current start payload; may not match intended quotas.
- **Volume policy ambiguity**: current code mounts datasets but does not explicitly enforce `:ro` semantics in MicroSandbox config (depends on platform behavior).
- **Operational maturity requirement**: key rotation, namespace governance, endpoint reliability, and run cleanup become mandatory disciplines.

## Production Hardening Work (MicroSandbox Path)

1. **RPC-only deterministic execution**
   - Remove or heavily constrain CLI fallback in production; use one authoritative execution path.
2. **Image/runtime policy**
   - Enforce signed immutable runner images; disallow dynamic pip installs during execution.
3. **Auth hardening**
   - Key rotation, short-lived credentials, tenant/namespace scoping, RBAC policies.
4. **Data mount + network policies**
   - Explicitly enforce read-only dataset mounts and egress policy in sandbox profile.
5. **Reliability engineering**
   - Retries with idempotency keys, timeout budgets, circuit breakers, dead-letter handling for failed runs.
6. **Observability integration**
   - Correlate app run_id with sandbox ID and RPC request ID; capture lifecycle metrics and errors.

## MicroSandbox Production LoE (from current state)

- RPC path hardening + fallback policy: **10-14 pts**
- Security/compliance controls (auth/image/policy): **14-20 pts**
- Reliability + resiliency controls: **12-18 pts**
- Observability/SLO + runbook maturity: **8-12 pts**

**Total MicroSandbox path LoE: 44-64 pts** (~4.5 to 8 engineer-weeks for one senior engineer; faster with platform support).

## MicroSandbox Production Limitations

- Higher operational complexity than local Docker.
- Requires confidence in vendor/runtime behavior and support model.
- Failures are harder to debug without strong distributed tracing and sandbox-side logs.

---

## Side-by-Side Production Comparison

| Dimension | Docker | MicroSandbox |
|---|---|---|
| Local dev simplicity | Excellent | Good (requires server/auth) |
| Operational complexity | Low-Medium | Medium-High |
| Multi-tenant isolation potential | Medium (needs major hardening) | High potential (if platform hardened) |
| Control plane dependency | None (local daemon only) | Yes (RPC service availability critical) |
| Cold-start latency | Medium | Medium-High (RPC + sandbox startup) |
| Security review friendliness | Often challenging | Often better if platform controls are mature |
| Determinism (as implemented) | High | Medium (fallback path can diverge) |
| Best fit | Interview/demo, small trusted workloads | Shared production infrastructure, policy-driven environments |

---

## Recommended Production Strategy

If the goal is interview demo + near-term reliability:

1. Keep **Docker** as default for local/dev.
2. Keep **MicroSandbox** as explicit opt-in for environments where control-plane separation is needed.
3. For real production, choose one primary path and fully harden it; avoid "dual-primary" operation until both are mature.

If the goal is long-term enterprise posture:

- Favor **MicroSandbox as strategic direction** (centralized controls, cleaner isolation narrative),
- but first eliminate fallback nondeterminism and enforce strict runtime/image/auth policies.

---

## Key Risks to Communicate in an Interview

1. You intentionally support two sandbox providers for portability and risk management.
2. Docker path is operationally simple but has host-runtime trust implications.
3. MicroSandbox path has stronger architecture potential but requires control-plane maturity.
4. Current implementation is already functional and tested; production-grade work is mainly hardening, reliability, and policy engineering.

That framing demonstrates pragmatic engineering judgment: you can ship now, and you know exactly what must change to satisfy stricter production requirements.

