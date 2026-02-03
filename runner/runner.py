#!/usr/bin/env python3
"""
CSV Analyst Chat - Sandboxed SQL Runner

Executes SQL queries against CSV datasets in an isolated environment.
Reads RunnerRequest JSON from stdin, writes RunnerResponse JSON to stdout.

Security:
- No network access (enforced by Docker --network none)
- Read-only dataset access
- Timeout enforcement
- Resource limits (enforced by container)
- Non-root user (enforced by Dockerfile)
"""

import sys
import json
import signal
import time
from typing import Any, Dict, List, Optional

try:
    import duckdb
except ImportError:
    print(json.dumps({
        "status": "error",
        "error": {
            "type": "RUNNER_INTERNAL_ERROR",
            "message": "DuckDB not installed"
        }
    }))
    sys.exit(1)

try:  # container/runtime path
    from common import RunnerResponse, sanitize_data_path, sanitize_table_name
except ImportError:  # test/import path
    from runner.common import RunnerResponse, sanitize_data_path, sanitize_table_name


class TimeoutError(Exception):
    """Raised when query execution times out."""
    pass

def is_timeout_exception(exc: Exception, timed_out: bool, timeout_seconds: int, start_time: float) -> bool:
    """Best-effort timeout classification for interrupted DuckDB queries."""
    if timed_out:
        return True

    elapsed_ms = int((time.time() - start_time) * 1000)
    msg = str(exc).lower()
    return "interrupt" in msg and elapsed_ms >= int(timeout_seconds * 900)


class RunnerRequest:
    """
    Input request schema.

    Expected JSON from stdin:
    {
        "dataset_id": "ecommerce",
        "files": [
            {"name": "orders.csv", "path": "/data/ecommerce/orders.csv"}
        ],
        "sql": "SELECT * FROM orders LIMIT 10",
        "timeout_seconds": 10,
        "max_rows": 200
    }
    """

    def __init__(self, data: Dict[str, Any]):
        self.dataset_id = data.get("dataset_id", "unknown")
        self.files = data.get("files", [])
        self.sql = data.get("sql", "")
        self.timeout_seconds = data.get("timeout_seconds", 10)
        self.max_rows = data.get("max_rows", 200)

    def validate(self) -> Optional[str]:
        """Validate request. Returns error message if invalid."""
        if not self.sql:
            return "SQL query is required"
        if not self.files:
            return "At least one file is required"
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            return "Timeout must be between 1 and 60 seconds"
        if self.max_rows <= 0 or self.max_rows > 1000:
            return "max_rows must be between 1 and 1000"
        return None


def load_csvs_into_duckdb(conn: duckdb.DuckDBPyConnection, files: List[Dict]) -> None:
    """
    Load CSV files into DuckDB tables.

    Args:
        conn: DuckDB connection
        files: List of {name, path} dicts
    """
    loaded_tables = set()

    for file_info in files:
        name = file_info.get("name", "")
        path = file_info.get("path", "")

        if not name or not path:
            raise ValueError(f"Invalid file info: {file_info}")

        table_name = sanitize_table_name(name)
        csv_path = sanitize_data_path(path)
        if table_name in loaded_tables:
            raise ValueError(f"Duplicate table name from files list: {table_name}")

        # Keep the file path as a bound parameter to avoid SQL injection risk.
        conn.execute(
            f'CREATE TABLE "{table_name}" AS SELECT * FROM read_csv_auto(?)',
            [csv_path],
        )
        loaded_tables.add(table_name)


def execute_query(request: RunnerRequest) -> RunnerResponse:
    """
    Execute SQL query with timeout and resource limits.

    Args:
        request: Validated RunnerRequest

    Returns:
        RunnerResponse with results or error
    """
    response = RunnerResponse()
    start_time = time.time()
    timed_out = False

    try:
        def timeout_handler(signum, frame):
            """Signal handler for timeout."""
            nonlocal timed_out
            timed_out = True
            raise TimeoutError("Query execution timed out")

        # Set up timeout signal
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(request.timeout_seconds)

        # Create in-memory DuckDB connection
        conn = duckdb.connect(":memory:")

        try:
            # Load CSV files
            load_csvs_into_duckdb(conn, request.files)

            # Execute query
            result = conn.execute(request.sql)

            # Fetch results (limited by max_rows)
            rows = result.fetchmany(request.max_rows)

            # Get column names
            columns = [desc[0] for desc in result.description] if result.description else []

            # Populate response
            response.columns = columns
            response.rows = rows
            response.row_count = len(rows)

        finally:
            conn.close()
            # Cancel alarm
            signal.alarm(0)

    except TimeoutError:
        response.status = "timeout"
        response.error = {
            "type": "RUNNER_TIMEOUT",
            "message": f"Query exceeded timeout of {request.timeout_seconds} seconds"
        }

    except duckdb.Error as e:
        if is_timeout_exception(e, timed_out, request.timeout_seconds, start_time):
            response.status = "timeout"
            response.error = {
                "type": "RUNNER_TIMEOUT",
                "message": f"Query exceeded timeout of {request.timeout_seconds} seconds"
            }
        else:
            response.status = "error"
            response.error = {
                "type": "SQL_EXECUTION_ERROR",
                "message": str(e)
            }

    except Exception as e:
        if is_timeout_exception(e, timed_out, request.timeout_seconds, start_time):
            response.status = "timeout"
            response.error = {
                "type": "RUNNER_TIMEOUT",
                "message": f"Query exceeded timeout of {request.timeout_seconds} seconds"
            }
        else:
            response.status = "error"
            response.error = {
                "type": "RUNNER_INTERNAL_ERROR",
                "message": str(e)
            }

    finally:
        # Calculate execution time
        end_time = time.time()
        response.exec_time_ms = int((end_time - start_time) * 1000)

    return response


def main():
    """Main entry point."""
    try:
        # Read request from stdin
        input_data = sys.stdin.read()

        if not input_data.strip():
            response = RunnerResponse()
            response.status = "error"
            response.error = {
                "type": "INVALID_INPUT",
                "message": "No input provided on stdin"
            }
            print(response.to_json())
            sys.exit(1)

        # Parse JSON
        try:
            request_data = json.loads(input_data)
        except json.JSONDecodeError as e:
            response = RunnerResponse()
            response.status = "error"
            response.error = {
                "type": "INVALID_JSON",
                "message": f"Failed to parse JSON: {e}"
            }
            print(response.to_json())
            sys.exit(1)

        # Create and validate request
        request = RunnerRequest(request_data)
        validation_error = request.validate()

        if validation_error:
            response = RunnerResponse()
            response.status = "error"
            response.error = {
                "type": "VALIDATION_ERROR",
                "message": validation_error
            }
            print(response.to_json())
            sys.exit(1)

        # Execute query
        response = execute_query(request)

        # Write response to stdout
        print(response.to_json())

        # Exit with appropriate code
        sys.exit(0 if response.status == "success" else 1)

    except Exception as e:
        # Catch-all for unexpected errors
        response = RunnerResponse()
        response.status = "error"
        response.error = {
            "type": "RUNNER_INTERNAL_ERROR",
            "message": f"Unexpected error: {e}"
        }
        print(response.to_json())
        sys.exit(1)


if __name__ == "__main__":
    main()
