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

## Post-MVP Considerations

1. **Multi-dataset queries**: Allow JOINs across datasets
2. **User uploads**: Support temporary CSV uploads
3. **Query caching**: Cache identical queries per dataset version
4. **Python mode**: Restricted Python execution
5. **Charts**: Auto-generate visualizations
6. **Auth**: Basic authentication and per-user history
7. **PostgreSQL**: Migrate from SQLite for horizontal scaling

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
