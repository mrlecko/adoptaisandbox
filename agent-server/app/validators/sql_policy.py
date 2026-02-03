"""
SQL validation policy for read-only query execution.
"""

from __future__ import annotations

import re
from typing import Optional

SQL_BLOCKLIST = [
    "drop",
    "delete",
    "insert",
    "update",
    "create",
    "alter",
    "attach",
    "install",
    "load",
    "pragma",
    "call",
    "copy",
    "export",
]


def contains_blocked_sql_token(sql_lower: str, token: str) -> bool:
    pattern = rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])"
    return re.search(pattern, sql_lower) is not None


def normalize_sql_for_dataset(sql: str, dataset_id: str) -> str:
    normalized = re.sub(
        rf'(?i)"{re.escape(dataset_id)}"\s*\.\s*',
        "",
        sql,
    )
    normalized = re.sub(
        rf"(?i)\b{re.escape(dataset_id)}\s*\.\s*",
        "",
        normalized,
    )
    return normalized


def validate_sql_policy(sql: str) -> Optional[str]:
    sql_clean = sql.strip()
    lowered = sql_clean.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return "Only SELECT/WITH queries are allowed."

    if ";" in sql_clean.rstrip(";"):
        return "Multiple SQL statements are not allowed."

    for token in SQL_BLOCKLIST:
        if contains_blocked_sql_token(lowered, token):
            return f"SQL contains blocked token: {token}"

    return None
