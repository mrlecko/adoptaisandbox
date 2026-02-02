# Project Decisions Log

This document tracks key architectural and implementation decisions.

## Date: 2026-02-02

### Decision 1: Dataset Mounting Strategy ✅

**Options Considered**:
- A) Bake datasets into runner image
- B) Mount via ConfigMap (K8s only)
- C) Mount via PVC (K8s only)

**Decision**: **Option A - Bake into runner image**

**Rationale**:
- Simplest for MVP
- Works in both Docker and K8s modes
- No dynamic mounting complexity
- Datasets are small (<10MB total)
- Ensures consistency (datasets versioned with image)
- Faster startup (no mount overhead)

**Tradeoffs**:
- Image rebuilds required for dataset updates
- Larger image size (acceptable for MVP)

**Status**: Finalized ✅

---

### Decision 2: Hosting Strategy ✅

**Options Considered**:
- Managed Kubernetes (GKE/EKS/AKS/DOKS)
- k3s on single VM
- PaaS-only deployment

**Decision**: **Primary: k3s on VM, Secondary: Managed K8s**

**Rationale**:
- k3s on VM is fastest to public URL (for take-home demo)
- Still demonstrates K8s + Helm + Job sandboxing
- Lower cost and setup time
- Single moving part for debugging
- Document managed K8s as production path in README

**Implementation Plan**:
1. Create runbook for k3s on DigitalOcean/Linode droplet
2. Document managed K8s alternative (GKE preferred)
3. Both use same Helm chart

**Status**: Finalized ✅

---

### Decision 3: SQL Validation Approach ✅

**Options Considered**:
- Denylist (keyword blocklist)
- AST parsing (full SQL parse tree validation)
- Hybrid (denylist + limited AST)

**Decision**: **Denylist for MVP, AST as stretch**

**Rationale**:
- Denylist is sufficient for sandbox + read-only constraints
- Simple to implement and test
- Easy to reason about
- AST parsing adds complexity without significant security gain (given other defenses)
- Defense-in-depth already present (no network, read-only FS, timeouts)

**Implementation**:
```python
DENIED_KEYWORDS = [
    'DROP', 'DELETE', 'INSERT', 'UPDATE', 'CREATE', 'ALTER',
    'ATTACH', 'DETACH', 'INSTALL', 'LOAD', 'PRAGMA', 'CALL',
    'COPY', 'EXPORT', 'IMPORT'
]
```

Case-insensitive regex matching before execution.

**Status**: Finalized ✅

---

### Decision 4: Python Execution Mode ✅

**Decision**: **Defer to post-MVP (v1.1)**

**Rationale**:
- MVP scope is already ambitious with SQL mode
- SQL covers 90% of analytics use cases
- Python adds significant complexity:
  - Import validation/sandboxing
  - AST parsing required
  - Larger security surface
  - More testing required
- Clear stretch goal with well-defined requirements in PRD

**Revisit Criteria**:
- After MVP deployed and stable
- If user feedback requests it
- If time permits (Phase 4)

**Status**: Finalized ✅

---

### Decision 5: Dataset Schemas ✅

**Decision**: **3 datasets with specifications defined**

**Datasets**:
1. **Ecommerce** (3 files: orders, order_items, inventory)
   - Tests: joins, multi-table queries, aggregations
   - ~5,000 orders, ~12,000 items, ~500 products

2. **Support Tickets** (1 file: tickets)
   - Tests: NULL handling, time windows, SLA calculations
   - ~8,000 tickets over 90 days

3. **IoT Sensors** (1 file: sensors)
   - Tests: time-series, anomalies, environmental data
   - ~50,000 readings over 30 days

**Golden Queries**: 6 per dataset (18 total)

**Documentation**: See `docs/use-cases/` for full specifications

**Status**: Finalized ✅

---

### Decision 6: LangChain Agent Architecture

**Decision**: Use LangChain with **structured outputs** for QueryPlan generation

**Implementation**:
- Pydantic models for QueryPlan schema
- Agent tools: `list_datasets`, `get_schema`, `execute_query_plan`, `execute_sql`, `get_run_status`
- System prompt emphasizes JSON plan as default
- Retry loop with validation feedback

**Alternative Considered**: Free-form LLM outputs with regex parsing
**Rejected Because**: Structured outputs are more reliable and easier to validate

**Status**: Finalized ✅

---

### Decision 7: Capsule Storage

**Decision**: **SQLite for MVP**

**Rationale**:
- Simple, no external dependencies
- Sufficient for single-instance agent server
- Easy to inspect/debug
- Acceptable for take-home scope

**Schema**:
```sql
CREATE TABLE run_capsules (
    run_id TEXT PRIMARY KEY,
    timestamp DATETIME,
    dataset_id TEXT,
    dataset_version_hash TEXT,
    question TEXT,
    plan_json TEXT,
    compiled_sql TEXT,
    runner_mode TEXT,
    resource_limits TEXT,
    result_preview TEXT,
    stats TEXT,
    stdout TEXT,
    stderr TEXT,
    status TEXT,
    error TEXT
);
```

**Migration Path** (post-MVP): PostgreSQL for multi-replica deployment

**Status**: Finalized ✅

---

### Decision 8: Query Plan DSL Scope

**Decision**: Support **subset of SQL** via JSON DSL

**Included Operations**:
- SELECT (columns + aggregations)
- FROM (single table)
- WHERE (filters with operators: =, !=, <, <=, >, >=, IN, BETWEEN, LIKE)
- GROUP BY
- ORDER BY
- LIMIT (enforced)

**Excluded (for MVP)**:
- Explicit JOINs (but compiler can add implicit joins if needed)
- Subqueries
- UNION/INTERSECT/EXCEPT
- Window functions
- CTEs (WITH clauses)

**Rationale**:
- Covers 90% of analytics queries
- Simple to validate and compile
- Reduces attack surface
- Can be extended post-MVP

**Status**: Finalized ✅

---

### Decision 9: Runner Technology

**Decision**: **DuckDB in Python script**

**Alternatives Considered**:
- SQLite: Lacks advanced analytics functions
- PostgreSQL: Too heavy for ephemeral runners
- Pandas: Not SQL-native

**Rationale**:
- DuckDB is fast, lightweight, embeddable
- Excellent CSV support (reads directly)
- SQL-native (no ORM needed)
- Advanced analytics functions
- Small footprint

**Status**: Finalized ✅

---

### Decision 10: UI Framework

**Decision**: Use **LangChain Agent UI starter** as-is

**Rationale**:
- Stock UI reduces development time
- Pre-integrated with LangGraph
- Good enough for MVP
- Customization can happen post-MVP

**Required Customizations**:
- Dataset selector dropdown
- "Show details" panel (plan, SQL, logs)
- Suggested prompts per dataset

**Status**: Finalized ✅

---

## Open Questions

None - all MVP decisions finalized.

## Decision 11: Runner Implementation ✅

**Options Considered**:
- A) Custom Docker Runner (build ourselves)
- B) MicroSandbox (mature third-party solution)
- C) Both (pluggable architecture)

**Decision**: **Option A - Custom Docker Runner for MVP, MicroSandbox later**

**Rationale**:
- **PRD Alignment**: PRD specifically describes Docker-based runner
- **Simplicity**: Fewer moving parts, faster to MVP
- **No External Dependencies**: Self-contained, easier deployment
- **Full Control**: Complete control over security hardening
- **K8s Path**: Direct translation to Kubernetes Jobs
- **Known Technology**: Team already knows Docker SDK

**MicroSandbox Evaluation**:
- ✅ Pros: Mature, feature-rich, async API, multi-language support
- ⚠️ Cons: External service dependency, additional infrastructure, learning curve
- 🔮 Future: Excellent candidate for Phase 4 (stretch goals)

**Implementation Plan**:
1. **Phase 1 (MVP)**: Build custom Docker runner
   - `runner/runner.py` - DuckDB + CSV loader
   - `runner/Dockerfile` - Security hardened
   - Simple stdin/stdout JSON protocol

2. **Phase 4 (Post-MVP)**: Add MicroSandbox support
   - Create `MicroSandboxRunner` class
   - Implement abstract `Runner` interface
   - Add configuration option: `RUNNER_TYPE=docker|microsandbox`
   - Document deployment with `msb` server
   - Useful for Python execution mode

**Extensibility Design**:
- Abstract `Runner` interface for pluggability
- Factory pattern for runner creation
- Configuration-driven runner selection

**Status**: Docker Runner in development ✅

**References**:
- MicroSandbox: https://docs.microsandbox.dev/
- PRD Section 10: Runner Spec

---

## Post-MVP Considerations

1. **MicroSandbox Integration**: Alternative runner implementation (see Decision 11)
2. **Multi-dataset queries**: Allow JOINs across datasets
3. **User uploads**: Support temporary CSV uploads
4. **Query caching**: Cache identical queries per dataset version
5. **Python mode**: Restricted Python execution (MicroSandbox ideal for this)
6. **Charts**: Auto-generate visualizations
7. **Auth**: Basic authentication and per-user history
8. **PostgreSQL**: Migrate from SQLite for horizontal scaling

---

## Decision Template

```markdown
### Decision N: [Title]

**Options Considered**:
- Option A
- Option B

**Decision**: **[Chosen option]**

**Rationale**:
- Reason 1
- Reason 2

**Tradeoffs**:
- Pro
- Con

**Status**: [Pending/Finalized/Revisited]
```
