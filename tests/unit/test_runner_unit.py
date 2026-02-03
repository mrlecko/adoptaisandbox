import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if "pandas" not in sys.modules:
    fake_pd = types.ModuleType("pandas")

    class _DataFrame:  # pragma: no cover - test stub
        pass

    fake_pd.DataFrame = _DataFrame
    fake_pd.read_csv = lambda *_args, **_kwargs: _DataFrame()
    sys.modules["pandas"] = fake_pd

if "numpy" not in sys.modules:
    sys.modules["numpy"] = types.ModuleType("numpy")

import runner.runner_python as py_runner  # noqa: E402
import runner.common as runner_common  # noqa: E402


def test_sql_runner_sanitize_table_name():
    assert runner_common.sanitize_table_name("tickets.csv") == "tickets"


def test_python_policy_blocks_os_import():
    err = py_runner.validate_python_policy("import os\nresult=1")
    assert err == "Blocked import: os"


def test_python_policy_allows_pandas():
    err = py_runner.validate_python_policy("import pandas as pd\nresult=1")
    assert err is None


def test_python_convert_result_scalar():
    cols, rows = py_runner._convert_to_table({"result": 7}, max_rows=10)  # noqa: SLF001
    assert cols == ["value"]
    assert rows == [[7]]


def test_sql_runner_sanitize_data_path_under_data_root(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    ds = data_root / "support"
    ds.mkdir(parents=True)
    f = ds / "tickets.csv"
    f.write_text("ticket_id\n1\n")
    monkeypatch.setattr(runner_common, "DATA_ROOT", data_root)
    sanitized = runner_common.sanitize_data_path(str(f))
    assert sanitized == str(f.resolve())


def test_python_runner_request_validation():
    req = py_runner.RunnerRequest(
        {
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "python_code": "result = 1",
            "timeout_seconds": 5,
            "max_rows": 10,
            "max_output_bytes": 4096,
        }
    )
    assert req.validate() is None

    bad = py_runner.RunnerRequest(
        {
            "dataset_id": "support",
            "files": [],
            "python_code": "",
            "timeout_seconds": 0,
            "max_rows": 0,
            "max_output_bytes": 100,
        }
    )
    assert bad.validate() == "python_code is required"


def test_python_runner_request_validation_output_bounds():
    too_small = py_runner.RunnerRequest(
        {
            "dataset_id": "support",
            "files": [{"name": "tickets.csv", "path": "/data/support/tickets.csv"}],
            "python_code": "result = 1",
            "timeout_seconds": 5,
            "max_rows": 10,
            "max_output_bytes": 512,
        }
    )
    assert too_small.validate() == "max_output_bytes must be between 1024 and 1000000"


def test_python_policy_blocks_open_call():
    err = py_runner.validate_python_policy("f = open('/tmp/a.txt', 'w')\nresult = 1")
    assert err == "Blocked call: open"


def test_python_convert_result_rows_infers_columns():
    cols, rows = py_runner._convert_to_table(  # noqa: SLF001
        {"result_rows": [[1, "a"], [2, "b"]]},
        max_rows=10,
    )
    assert cols == ["col_1", "col_2"]
    assert rows == [[1, "a"], [2, "b"]]


def test_python_trim_rows_to_output_limit():
    rows = [[str(i) * 50] for i in range(50)]
    trimmed = py_runner._trim_rows_to_output_limit(  # noqa: SLF001
        columns=["big"],
        rows=rows,
        max_output_bytes=600,
    )
    assert len(trimmed) < len(rows)
