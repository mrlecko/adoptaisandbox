from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.validators.sql_policy import (  # noqa: E402
    normalize_sql_for_dataset,
    validate_sql_policy,
)


def test_validate_sql_policy_allows_created_at():
    sql = "SELECT MAX(created_at) AS last_ticket_added FROM tickets"
    assert validate_sql_policy(sql) is None


def test_validate_sql_policy_rejects_drop():
    sql = "SELECT 1; DROP TABLE tickets"
    assert validate_sql_policy(sql) == "Multiple SQL statements are not allowed."


def test_validate_sql_policy_rejects_non_select():
    sql = "DELETE FROM tickets"
    assert validate_sql_policy(sql) == "Only SELECT/WITH queries are allowed."


def test_normalize_sql_for_dataset_removes_prefix():
    sql = "SELECT COUNT(*) FROM support.tickets"
    normalized = normalize_sql_for_dataset(sql, "support")
    assert normalized == "SELECT COUNT(*) FROM tickets"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM tickets",
        "WITH t AS (SELECT * FROM tickets) SELECT COUNT(*) FROM t",
    ],
)
def test_validate_sql_policy_happy_paths(sql):
    assert validate_sql_policy(sql) is None
