#!/usr/bin/env python3
"""
CSV Analyst Chat - Sandboxed Python Runner

Executes constrained Python code against CSV datasets in an isolated container.
Reads RunnerRequest JSON from stdin, writes RunnerResponse JSON to stdout.
"""

import ast
import io
import json
import signal
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:  # container/runtime path
    from common import RunnerResponse, sanitize_data_path, sanitize_table_name
except ImportError:  # test/import path
    from runner.common import RunnerResponse, sanitize_data_path, sanitize_table_name


class TimeoutError(Exception):
    """Raised when code execution exceeds timeout."""


MAX_STDIO_BYTES = 65536

ALLOWED_IMPORTS = {
    "pandas",
    "numpy",
    "math",
    "statistics",
    "re",
    "datetime",
}
BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "pathlib",
    "shutil",
    "ctypes",
    "importlib",
}
BLOCKED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input"}

# Methods blocked on specific namespace variables (pd.read_csv, np.load, etc.)
BLOCKED_MODULE_METHODS = {
    "pd": {
        "read_csv", "read_excel", "read_json", "read_parquet", "read_table",
        "read_fwf", "read_html", "read_sql", "read_clipboard", "read_stata",
        "read_sas", "read_spss", "read_orc", "read_pickle",
    },
    "np": {
        "load", "save", "savez", "savez_compressed",
        "fromfile", "tofile", "loadtxt", "savetxt", "genfromtxt",
    },
}

# Write-method names blocked on ANY object (covers df.to_csv, series.to_parquet, etc.)
BLOCKED_WRITE_ATTRS = {
    "to_csv", "to_excel", "to_parquet", "to_pickle", "to_sql",
    "to_stata", "to_clipboard", "to_orc",
}

LAST_EXPR_RESULT_VAR = "__last_expr_result"

class RunnerRequest:
    def __init__(self, data: Dict[str, Any]):
        self.dataset_id = data.get("dataset_id", "unknown")
        self.files = data.get("files", [])
        self.python_code = data.get("python_code", "")
        self.timeout_seconds = data.get("timeout_seconds", 10)
        self.max_rows = data.get("max_rows", 200)
        self.max_output_bytes = data.get("max_output_bytes", 65536)

    def validate(self) -> Optional[str]:
        if not self.python_code:
            return "python_code is required"
        if not self.files:
            return "At least one file is required"
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            return "Timeout must be between 1 and 60 seconds"
        if self.max_rows <= 0 or self.max_rows > 1000:
            return "max_rows must be between 1 and 1000"
        if self.max_output_bytes <= 1024 or self.max_output_bytes > 1_000_000:
            return "max_output_bytes must be between 1024 and 1000000"
        return None

def validate_python_policy(code: str) -> Optional[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"Invalid Python syntax: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_MODULES:
                    return f"Blocked import: {root}"
                if root not in ALLOWED_IMPORTS:
                    return f"Import not allowed: {root}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in BLOCKED_MODULES:
                return f"Blocked import: {module}"
            if module and module not in ALLOWED_IMPORTS:
                return f"Import not allowed: {module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                return f"Blocked call: {node.func.id}"
            if isinstance(node.func, ast.Attribute):
                attr_name = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    mod = node.func.value.id
                    if mod in BLOCKED_MODULES:
                        return f"Blocked module access: {mod}"
                    if mod in BLOCKED_MODULE_METHODS and attr_name in BLOCKED_MODULE_METHODS[mod]:
                        return f"Blocked method: {mod}.{attr_name}"
                if attr_name in BLOCKED_WRITE_ATTRS:
                    return f"Blocked method: {attr_name}"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                return f"Blocked dunder access: {node.attr}"

    return None


def _compile_user_code(code: str):
    """Compile user code, capturing a trailing expression into a synthetic variable."""
    tree = ast.parse(code, mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        tree.body[-1] = ast.Assign(
            targets=[ast.Name(id=LAST_EXPR_RESULT_VAR, ctx=ast.Store())],
            value=tree.body[-1].value,
        )
        ast.fix_missing_locations(tree)
    return compile(tree, "<runner_python>", "exec")


def load_csvs(files: List[Dict[str, str]]) -> Dict[str, pd.DataFrame]:
    dfs: Dict[str, pd.DataFrame] = {}
    for file_info in files:
        name = file_info.get("name", "")
        path = file_info.get("path", "")
        if not name or not path:
            raise ValueError(f"Invalid file info: {file_info}")
        table_name = sanitize_table_name(name)
        csv_path = sanitize_data_path(path)
        if table_name in dfs:
            raise ValueError(f"Duplicate table name from files list: {table_name}")
        dfs[table_name] = pd.read_csv(csv_path)
    return dfs


def _safe_builtins() -> Dict[str, Any]:
    return {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }


def _convert_to_table(local_ns: Dict[str, Any], max_rows: int) -> tuple[list[str], list[list[Any]]]:
    if "result_df" in local_ns:
        result_df = local_ns["result_df"]
        if not isinstance(result_df, pd.DataFrame):
            raise ValueError("result_df must be a pandas DataFrame")
        sliced = result_df.head(max_rows)
        return [str(c) for c in sliced.columns], sliced.values.tolist()

    if "result_rows" in local_ns:
        rows = local_ns["result_rows"]
        if not isinstance(rows, list):
            raise ValueError("result_rows must be a list")
        rows = rows[:max_rows]
        columns = local_ns.get("result_columns")
        if columns is None:
            width = len(rows[0]) if rows else 1
            columns = [f"col_{i+1}" for i in range(width)]
        return [str(c) for c in columns], rows

    if "result" in local_ns:
        result = local_ns["result"]
        if isinstance(result, pd.DataFrame):
            sliced = result.head(max_rows)
            return [str(c) for c in sliced.columns], sliced.values.tolist()
        if isinstance(result, dict):
            return ["key", "value"], [[k, v] for k, v in list(result.items())[:max_rows]]
        if isinstance(result, list):
            rows = result[:max_rows]
            if rows and isinstance(rows[0], list):
                width = len(rows[0])
                return [f"col_{i+1}" for i in range(width)], rows
            return ["value"], [[r] for r in rows]
        return ["value"], [[result]]

    return [], []


def _trim_rows_to_output_limit(columns: list[str], rows: list[list[Any]], max_output_bytes: int) -> list[list[Any]]:
    trimmed = list(rows)
    while trimmed:
        payload = json.dumps({"columns": columns, "rows": trimmed}, default=str)
        if len(payload.encode("utf-8")) <= max_output_bytes:
            break
        trimmed.pop()
    return trimmed


def execute_python(request: RunnerRequest) -> RunnerResponse:
    response = RunnerResponse()
    start_time = time.time()

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    def timeout_handler(_signum, _frame):
        raise TimeoutError("Python execution timed out")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(request.timeout_seconds)

    try:
        dfs = load_csvs(request.files)

        global_ns: Dict[str, Any] = {"__builtins__": _safe_builtins(), "pd": pd, "np": np, "dfs": dfs}
        local_ns: Dict[str, Any] = {}
        for name, df in dfs.items():
            global_ns[name] = df

        compiled_code = _compile_user_code(request.python_code)
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compiled_code, global_ns, local_ns)

        # If the user ended code with an expression, treat it as the result unless
        # they already provided an explicit result variable.
        if (
            LAST_EXPR_RESULT_VAR in local_ns
            and "result_df" not in local_ns
            and "result_rows" not in local_ns
            and "result" not in local_ns
        ):
            local_ns["result"] = local_ns[LAST_EXPR_RESULT_VAR]

        columns, rows = _convert_to_table(local_ns, request.max_rows)
        if not columns and not rows:
            raise ValueError(
                "Python code produced no tabular/scalar result. "
                "Set result/result_df/result_rows, or end with an expression."
            )
        rows = _trim_rows_to_output_limit(columns, rows, request.max_output_bytes)

        response.columns = columns
        response.rows = rows
        response.row_count = len(rows)
        response.stdout_trunc = stdout_buf.getvalue()[:MAX_STDIO_BYTES]
        response.stderr_trunc = stderr_buf.getvalue()[:MAX_STDIO_BYTES]
    except TimeoutError:
        response.status = "timeout"
        response.error = {
            "type": "RUNNER_TIMEOUT",
            "message": f"Python execution exceeded timeout of {request.timeout_seconds} seconds",
        }
    except Exception as exc:
        response.status = "error"
        response.error = {
            "type": "PYTHON_EXECUTION_ERROR",
            "message": str(exc),
        }
        response.stdout_trunc = stdout_buf.getvalue()[:MAX_STDIO_BYTES]
        response.stderr_trunc = stderr_buf.getvalue()[:MAX_STDIO_BYTES]
    finally:
        signal.alarm(0)
        response.exec_time_ms = int((time.time() - start_time) * 1000)

    return response


def main() -> int:
    response = RunnerResponse()

    try:
        raw_input = sys.stdin.read().strip()
        if not raw_input:
            response.status = "error"
            response.error = {"type": "VALIDATION_ERROR", "message": "No input provided"}
            print(response.to_json())
            return 1

        try:
            data = json.loads(raw_input)
        except json.JSONDecodeError as exc:
            response.status = "error"
            response.error = {"type": "VALIDATION_ERROR", "message": f"Invalid JSON: {exc}"}
            print(response.to_json())
            return 1

        request = RunnerRequest(data)
        validation_error = request.validate()
        if validation_error:
            response.status = "error"
            response.error = {"type": "VALIDATION_ERROR", "message": validation_error}
            print(response.to_json())
            return 1

        policy_error = validate_python_policy(request.python_code)
        if policy_error:
            response.status = "error"
            response.error = {"type": "PYTHON_POLICY_VIOLATION", "message": policy_error}
            print(response.to_json())
            return 1

        response = execute_python(request)
        print(response.to_json())
        return 0 if response.status == "success" else 1
    except Exception as exc:
        response.status = "error"
        response.error = {"type": "RUNNER_INTERNAL_ERROR", "message": str(exc)}
        print(response.to_json())
        return 1


if __name__ == "__main__":
    sys.exit(main())
