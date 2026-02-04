# Evidence Bundle (Deterministic Verification)

Generated: 2026-02-03T21:25:16Z (UTC)  
Commit at capture start: `ffe20f2`

Purpose: provide concrete, reproducible proof that the core local demo path and key regression suites are working.

---

## Environment Snapshot

Commands:

```bash
python3 --version
docker --version
```

Observed:

```text
Python 3.11.11
Docker version 28.1.1, build 4eba377
```

---

## 1) Golden Path Local Demo Check (P0 Item #1)

Command:

```bash
OPENAI_API_KEY=dummy make first-run-check
```

Observed output:

```text
✓ Agent virtualenv ready at agent-server/.venv
./scripts/first_run_check.sh
[1/6] Verifying runner image...
[2/6] Starting agent server on http://127.0.0.1:18080...
[3/6] Waiting for /healthz...
[4/6] Checking dataset registry endpoint...
[5/6] Running deterministic SQL execution check via /chat...
[6/6] Validating response contracts...
PASS: first-run-check contract assertions succeeded.
PASS: first-run-check completed.
Log file: ./docs/evidence/logs/first_run_check.log
```

Server log evidence:
- `docs/evidence/logs/first_run_check.log`

Command wrapper log:
- `docs/evidence/logs/make_first_run_check.log`

---

## 2) Code Quality Checks

Commands:

```bash
agent-server/.venv/bin/ruff check agent-server
agent-server/.venv/bin/black --check agent-server
```

Observed:

```text
All checks passed!
All done! ✨ 🍰 ✨
21 files would be left unchanged.
```

Logs:
- `docs/evidence/logs/ruff_check.log`
- `docs/evidence/logs/black_check.log`

---

## 3) Unit + Security Test Proof

Commands:

```bash
agent-server/.venv/bin/pytest tests/unit -q
agent-server/.venv/bin/pytest tests/security -q
```

Observed:

```text
152 passed, 6 warnings in 4.14s
6 passed in 0.04s
```

Logs:
- `docs/evidence/logs/pytest_unit.log`
- `docs/evidence/logs/pytest_security.log`

---

## 4) Agent Server Integration Proof

Command:

```bash
agent-server/.venv/bin/pytest tests/integration/test_agent_server_singlefile.py -v
```

Observed:

```text
======================= 31 passed, 33 warnings in 7.24s =======================
```

Log:
- `docs/evidence/logs/pytest_agent_integration_v.log`

---

## 5) Docker Runner + Executor Integration Proof

Command:

```bash
make test-runner
```

Observed:

```text
============================= 14 passed in 26.23s ==============================
```

Log:
- `docs/evidence/logs/make_test_runner.log`

This suite includes:
- SQL runner execution over all three datasets
- Python runner execution and policy checks
- timeout classification
- output-byte-limit enforcement
- network-egress block verification
- DockerExecutor SQL/Python integration

---

## 6) Notes on Warnings and Determinism

- Current warnings are LangGraph deprecation warnings for `create_react_agent`; tests still pass.
- `make first-run-check` intentionally uses deterministic explicit SQL path for stable pass/fail signal.
- CI and local command expectations are aligned to the same key suites:
  - lint
  - unit/security
  - agent integration
  - docker runner/executor integration

---

## 7) CI Hardening Snapshot (P0 Item #4)

Workflow file:
- `.github/workflows/ci.yml`

Current CI gate order:
1. `lint-and-core-tests`
   - `ruff check`
   - `black --check`
   - `pytest tests/unit`
   - `pytest tests/security`
   - `pytest tests/integration/test_agent_server_singlefile.py`
2. `docker-integration`
   - builds `csv-analyst-runner:test`
   - runs runner + Docker executor integration suites
3. `build-images` (push events only; depends on both prior gates)

Pinned consistency expectations:
- Python runtime for CI test jobs: `3.13`
- Docker test image tag for runner integration: `csv-analyst-runner:test`
- Build/push step blocked unless test gates pass
