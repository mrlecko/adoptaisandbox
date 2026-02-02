# Future Enhancements

This document tracks planned enhancements for post-MVP development.

## Phase 4: Stretch Goals

### 🔮 MicroSandbox Integration (High Priority)

**Status**: Evaluated, deferred to post-MVP
**Decision**: See Decision 11 in DECISIONS.md

#### Overview

MicroSandbox (https://docs.microsandbox.dev/) is a mature sandboxed code execution platform that could serve as an alternative runner implementation.

#### Benefits

- **Mature Solution**: Battle-tested isolation and security
- **Multi-Language**: Supports Python, JavaScript, and more
- **Modern API**: Async Python SDK with clean abstractions
- **Maintenance**: Security patches handled upstream
- **Flexibility**: Execute commands, scripts, multiple languages
- **Ideal for Python Mode**: Perfect for restricted Python execution stretch goal

#### Architecture

```python
# Abstract interface (to be created in Phase 4)
class Runner(ABC):
    @abstractmethod
    async def execute(self, request: RunnerRequest) -> RunnerResponse:
        pass

# Current implementation (Phase 1)
class DockerRunner(Runner):
    """Custom DuckDB runner in Docker container"""
    pass

# Future implementation (Phase 4)
class MicroSandboxRunner(Runner):
    """Runner using MicroSandbox for isolation"""

    def __init__(self):
        self.client = MicroSandboxClient()

    async def execute(self, request: RunnerRequest) -> RunnerResponse:
        async with PythonSandbox.create(name=f"run-{request.run_id}") as sb:
            # Load CSVs
            # Execute SQL via DuckDB in sandbox
            # Return results
            pass
```

#### Configuration

```python
# Environment variable
RUNNER_TYPE = os.getenv("RUNNER_TYPE", "docker")  # or "microsandbox"

# Factory pattern
def create_runner() -> Runner:
    if RUNNER_TYPE == "docker":
        return DockerRunner()
    elif RUNNER_TYPE == "microsandbox":
        return MicroSandboxRunner()
    else:
        raise ValueError(f"Unknown runner type: {RUNNER_TYPE}")
```

#### Deployment Considerations

**Requirements**:
- MicroSandbox server running: `msb server start --dev`
- Python SDK installed: `pip install microsandbox`
- Network connectivity between agent-server and `msb` server

**Docker Compose** (development):
```yaml
services:
  microsandbox:
    image: microsandbox/server:latest
    ports:
      - "8080:8080"

  agent-server:
    # ...
    environment:
      - RUNNER_TYPE=microsandbox
      - MICROSANDBOX_URL=http://microsandbox:8080
```

**Kubernetes**:
- Deploy MicroSandbox as a service
- Agent server connects via internal service URL
- Same RBAC considerations as Docker mode

#### Use Cases

1. **SQL Execution** (current use case)
   - Works with both Docker and MicroSandbox
   - MicroSandbox provides additional isolation

2. **Python Execution** (stretch goal)
   - MicroSandbox is ideal for this
   - Built-in support for restricted Python
   - No need to build our own Python sandbox

3. **Multi-Language Support** (future)
   - JavaScript for data transformations
   - R for statistical analysis
   - Any language MicroSandbox supports

#### Implementation Checklist

- [ ] Evaluate MicroSandbox licensing (appears open source)
- [ ] Create abstract `Runner` interface
- [ ] Refactor `DockerRunner` to implement interface
- [ ] Implement `MicroSandboxRunner` class
- [ ] Add `RUNNER_TYPE` configuration
- [ ] Update Dockerfile and docker-compose.yml
- [ ] Add MicroSandbox to Helm chart (optional service)
- [ ] Write integration tests for MicroSandbox mode
- [ ] Document deployment and configuration
- [ ] Add to README as alternative option

#### Testing Strategy

```python
# Test both runners with same test suite
@pytest.mark.parametrize("runner_type", ["docker", "microsandbox"])
async def test_sql_execution(runner_type):
    runner = create_runner(runner_type)

    request = RunnerRequest(
        dataset_id="ecommerce",
        sql="SELECT * FROM orders LIMIT 10"
    )

    response = await runner.execute(request)

    assert response.status == "success"
    assert len(response.rows) == 10
```

#### Migration Path

1. **Phase 1 (Current)**: Docker runner only
2. **Phase 4.1**: Create abstract interface, refactor Docker runner
3. **Phase 4.2**: Add MicroSandbox runner implementation
4. **Phase 4.3**: Add configuration and deployment docs
5. **Phase 4.4**: Test both runners in production
6. **Phase 5**: Evaluate which to make default based on production experience

#### Resources

- **MicroSandbox Docs**: https://docs.microsandbox.dev/
- **GitHub**: (need to find repo)
- **Decision Log**: Decision 11 in docs/DECISIONS.md
- **TODO**: Phase 4.1 in TODO.md

---

## Other Future Enhancements

### Multi-Dataset Queries

Support JOINs across multiple datasets.

**Current**: Single dataset per query
**Future**: `FROM dataset1.table1 JOIN dataset2.table2`

### User-Uploaded CSVs

Allow temporary CSV uploads for ad-hoc analysis.

**Security**: Same sandbox restrictions apply
**Storage**: Temporary (deleted after session)
**Size Limits**: Configurable max upload size

### Query Caching

Cache results for identical queries on same dataset version.

**Cache Key**: `dataset_version_hash + sql_hash`
**Storage**: Redis or in-memory
**TTL**: Configurable (default 1 hour)

### Chart Visualization

Auto-generate charts for numeric results.

**Types**: Bar, line, pie, scatter
**Library**: Chart.js or Plotly
**Trigger**: Automatic for numeric columns, or user-requested

### Multi-Turn Analysis Sessions

Support temporary views and derived tables across chat turns.

**Features**:
- `CREATE TEMP VIEW` support
- Session-scoped temp tables
- Cross-turn variable references

### Authentication & User History

Basic auth with per-user query history.

**Auth**: OAuth or simple username/password
**History**: Store user's queries and results
**Sharing**: Share run capsules via links

### PostgreSQL Migration

Migrate from SQLite to PostgreSQL for horizontal scaling.

**Benefits**: Better concurrency, replication, production-ready
**Migration**: Keep capsule schema compatible

---

## Contribution Guidelines

To propose a new enhancement:

1. Create an issue describing the enhancement
2. Reference relevant PRD sections
3. Provide use cases and benefits
4. Consider MVP vs. stretch goal classification
5. Update this document if approved

---

**Last Updated**: 2026-02-02
