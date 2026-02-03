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

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.validators.sql_policy import validate_sql_policy  # noqa: E402


def test_sql_policy_blocks_drop_statement():
    err = validate_sql_policy("SELECT * FROM tickets; DROP TABLE tickets")
    assert err is not None


def test_python_policy_blocks_subprocess_import():
    err = py_runner.validate_python_policy("import subprocess\nresult=1")
    assert err == "Blocked import: subprocess"


def test_python_policy_blocks_eval_call():
    err = py_runner.validate_python_policy("result = eval('1+1')")
    assert err == "Blocked call: eval"


def test_python_policy_blocks_socket_import():
    err = py_runner.validate_python_policy("import socket\nresult=1")
    assert err == "Blocked import: socket"


def test_python_policy_blocks_file_open_call():
    err = py_runner.validate_python_policy("f = open('/tmp/x', 'w')\nresult=1")
    assert err == "Blocked call: open"


def test_python_policy_blocks_dunder_import_call():
    err = py_runner.validate_python_policy("result = __import__('os')")
    assert err == "Blocked call: __import__"
