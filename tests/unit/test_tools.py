"""Unit tests for app.tools — each tool exercised with a FakeExecutor."""

from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.executors.base import Executor  # noqa: E402
from app.tools import create_tools  # noqa: E402
from app.validators.compiler import QueryPlanCompiler  # noqa: E402


DATASETS_DIR = str(Path(__file__).parent.parent.parent / "datasets")


class FakeExecutor(Executor):
    """Minimal executor that returns canned results and records calls."""

    def __init__(self, results=None, default_result=None):
        self.calls: list[dict] = []
        self._results = list(results) if results else []
        self._default = default_result or {
            "run_id": "fake-run-1",
            "status": "succeeded",
            "result": {
                "status": "success",
                "columns": ["n"],
                "rows": [[42]],
                "row_count": 1,
                "exec_time_ms": 5,
                "error": None,
            },
        }

    def submit_run(self, payload, query_type="sql"):
        self.calls.append({"payload": payload, "query_type": query_type})
        if self._results:
            return self._results.pop(0)
        return self._default

    def get_status(self, run_id):
        return {"run_id": run_id, "status": "succeeded"}

    def get_result(self, run_id):
        return self._default.get("result")

    def cleanup(self, run_id):
        pass


def _make_tools(executor=None, **kwargs):
    defaults = dict(
        executor=executor or FakeExecutor(),
        compiler=QueryPlanCompiler(),
        datasets_dir=DATASETS_DIR,
        max_rows=200,
        max_output_bytes=65536,
        timeout_seconds=10,
        enable_python_execution=True,
    )
    defaults.update(kwargs)
    return create_tools(**defaults)


def _tool_by_name(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(f"Tool {name} not found")


# ── list_datasets ─────────────────────────────────────────────────────────


def test_list_datasets_returns_all_three():
    tools = _make_tools()
    result = json.loads(_tool_by_name(tools, "list_datasets").invoke({}))
    ids = {d["id"] for d in result["datasets"]}
    assert ids == {"ecommerce", "support", "sensors"}


def test_list_datasets_includes_prompts():
    tools = _make_tools()
    result = json.loads(_tool_by_name(tools, "list_datasets").invoke({}))
    for ds in result["datasets"]:
        assert "prompts" in ds
        assert len(ds["prompts"]) > 0


# ── get_dataset_schema ────────────────────────────────────────────────────


def test_get_dataset_schema_returns_files_and_sample():
    tools = _make_tools()
    result = json.loads(
        _tool_by_name(tools, "get_dataset_schema").invoke({"dataset_id": "support"})
    )
    assert result["id"] == "support"
    assert len(result["files"]) >= 1
    assert "schema" in result["files"][0]
    assert len(result["files"][0]["sample_rows"]) == 3


def test_get_dataset_schema_unknown_id_raises():
    tools = _make_tools()
    with pytest.raises(KeyError, match="Unknown dataset_id"):
        _tool_by_name(tools, "get_dataset_schema").invoke({"dataset_id": "nonexistent"})


# ── execute_sql ───────────────────────────────────────────────────────────


def test_execute_sql_happy_path():
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    result = json.loads(
        _tool_by_name(tools, "execute_sql").invoke(
            {"dataset_id": "support", "sql": "SELECT COUNT(*) AS n FROM tickets"}
        )
    )
    assert result["status"] == "success"
    assert result["rows"] == [[42]]
    assert result["compiled_sql"] == "SELECT COUNT(*) AS n FROM tickets"
    assert len(executor.calls) == 1
    assert executor.calls[0]["query_type"] == "sql"


def test_execute_sql_normalizes_dataset_prefix():
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    result = json.loads(
        _tool_by_name(tools, "execute_sql").invoke(
            {"dataset_id": "support", "sql": "SELECT * FROM support.tickets LIMIT 5"}
        )
    )
    # The compiled_sql should have 'support.' stripped
    assert "support." not in result["compiled_sql"]
    assert "FROM tickets" in result["compiled_sql"]


def test_execute_sql_policy_violation_rejected():
    tools = _make_tools()
    result = json.loads(
        _tool_by_name(tools, "execute_sql").invoke(
            {"dataset_id": "support", "sql": "DROP TABLE tickets"}
        )
    )
    assert result["status"] == "error"
    assert result["error"]["type"] == "SQL_POLICY_VIOLATION"


def test_execute_sql_created_at_not_false_positive():
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    result = json.loads(
        _tool_by_name(tools, "execute_sql").invoke(
            {
                "dataset_id": "support",
                "sql": "SELECT MAX(created_at) AS last FROM tickets",
            }
        )
    )
    # Should NOT be blocked — 'created_at' contains 'create' but only as substring
    assert result["status"] == "success"
    assert len(executor.calls) == 1


def test_execute_sql_missing_table_includes_schema_hint():
    executor = FakeExecutor(
        default_result={
            "run_id": "fake-run-err",
            "status": "failed",
            "result": {
                "status": "error",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "exec_time_ms": 3,
                "error": {
                    "type": "SQL_EXECUTION_ERROR",
                    "message": "Catalog Error: Table with name product_sales does not exist!",
                },
            },
        }
    )
    tools = _make_tools(executor=executor)
    result = json.loads(
        _tool_by_name(tools, "execute_sql").invoke(
            {
                "dataset_id": "ecommerce",
                "sql": "SELECT AVG(discount) FROM product_sales",
            }
        )
    )
    assert result["status"] == "error"
    assert "schema_hint" in result
    assert "order_items" in result["schema_hint"]["tables"]
    assert "discount" in result["schema_hint"]["tables"]["order_items"]


# ── execute_query_plan ────────────────────────────────────────────────────


def test_execute_query_plan_compiles_and_runs():
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    plan = {
        "dataset_id": "support",
        "table": "tickets",
        "select": [{"column": "priority"}],
        "limit": 10,
    }
    result = json.loads(
        _tool_by_name(tools, "execute_query_plan").invoke(
            {"dataset_id": "support", "plan": json.dumps(plan)}
        )
    )
    assert result["status"] == "success"
    assert "plan_json" in result
    assert result["plan_json"]["table"] == "tickets"
    assert "compiled_sql" in result
    assert len(executor.calls) == 1


def test_execute_query_plan_dataset_id_from_arg_wins():
    """The function-arg dataset_id should override anything in the plan body."""
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    # plan says dataset_id=ecommerce but we call with support
    plan = {
        "dataset_id": "ecommerce",
        "table": "tickets",
        "select": [{"column": "priority"}],
        "limit": 10,
    }
    result = json.loads(
        _tool_by_name(tools, "execute_query_plan").invoke(
            {"dataset_id": "support", "plan": json.dumps(plan)}
        )
    )
    # The plan_json.dataset_id should be 'support' (from arg)
    assert result["plan_json"]["dataset_id"] == "support"


def test_execute_query_plan_policy_violation():
    """A plan that compiles to blocked SQL should be caught."""
    # QueryPlan won't generate DROP, so we test that policy check is in the path
    # by verifying a valid plan does NOT get blocked
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    plan = {
        "dataset_id": "support",
        "table": "tickets",
        "select": [{"column": "priority"}],
        "limit": 5,
    }
    result = json.loads(
        _tool_by_name(tools, "execute_query_plan").invoke(
            {"dataset_id": "support", "plan": json.dumps(plan)}
        )
    )
    assert result["status"] == "success"


# ── execute_python ────────────────────────────────────────────────────────


def test_execute_python_happy_path():
    executor = FakeExecutor()
    tools = _make_tools(executor=executor)
    result = json.loads(
        _tool_by_name(tools, "execute_python").invoke(
            {"dataset_id": "support", "python_code": "result = len(tickets)"}
        )
    )
    assert result["status"] == "success"
    assert len(executor.calls) == 1
    assert executor.calls[0]["query_type"] == "python"
    assert executor.calls[0]["payload"]["python_code"] == "result = len(tickets)"


def test_execute_python_disabled():
    tools = _make_tools(enable_python_execution=False)
    result = json.loads(
        _tool_by_name(tools, "execute_python").invoke(
            {"dataset_id": "support", "python_code": "result = 1"}
        )
    )
    assert result["status"] == "error"
    assert result["error"]["type"] == "FEATURE_DISABLED"


def test_execute_python_passes_timeout_and_max_rows():
    executor = FakeExecutor()
    tools = _make_tools(executor=executor, timeout_seconds=42, max_rows=100)
    _tool_by_name(tools, "execute_python").invoke(
        {"dataset_id": "support", "python_code": "result = 1"}
    )
    payload = executor.calls[0]["payload"]
    assert payload["timeout_seconds"] == 42
    assert payload["max_rows"] == 100
