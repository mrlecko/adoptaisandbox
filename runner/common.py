"""
Shared runner utilities used by SQL and Python entrypoints.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DATA_ROOT = Path("/data")


def sanitize_table_name(filename: str) -> str:
    table_name = Path(filename).stem
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(f"Invalid table name derived from filename: {filename}")
    return table_name


def sanitize_data_path(path_value: str) -> str:
    candidate = Path(path_value)
    if not candidate.is_absolute():
        raise ValueError(f"CSV path must be absolute: {path_value}")

    resolved = candidate.resolve()
    data_root = DATA_ROOT.resolve()
    if resolved != data_root and data_root not in resolved.parents:
        raise ValueError(f"CSV path must be under {data_root}: {path_value}")
    if not resolved.is_file():
        raise ValueError(f"CSV file not found: {path_value}")

    return str(resolved)


class RunnerResponse:
    def __init__(self):
        self.status = "success"
        self.columns = []
        self.rows = []
        self.row_count = 0
        self.exec_time_ms = 0
        self.stdout_trunc = ""
        self.stderr_trunc = ""
        self.error = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "columns": self.columns,
                "rows": self.rows,
                "row_count": self.row_count,
                "exec_time_ms": self.exec_time_ms,
                "stdout_trunc": self.stdout_trunc,
                "stderr_trunc": self.stderr_trunc,
                "error": self.error,
            },
            default=str,
        )
