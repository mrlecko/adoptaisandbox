"""
QueryPlan to SQL compiler.

Compiles validated QueryPlan objects to deterministic DuckDB SQL.
Enforces safety constraints and query limits.
"""

from typing import List, Union
from ..models.query_plan import (
    QueryPlan,
    Filter,
    FilterOperator,
    Aggregation,
    SelectColumn,
    OrderBy,
    SortDirection,
)


class CompilationError(Exception):
    """Raised when QueryPlan cannot be compiled to valid SQL."""
    pass


class QueryPlanCompiler:
    """
    Compiles QueryPlan to SQL.

    Features:
    - Deterministic output (same plan = same SQL)
    - DuckDB-compatible SQL
    - Enforces LIMIT
    - Handles all filter operators
    - Supports aggregations and GROUP BY
    - Safe column/table name escaping
    """

    # Maximum columns to select without explicit aggregation or limit warning
    MAX_COLUMNS_WITHOUT_AGGREGATION = 20

    def __init__(self):
        """Initialize compiler."""
        pass

    def compile(self, plan: QueryPlan) -> str:
        """
        Compile QueryPlan to SQL.

        Args:
            plan: Validated QueryPlan object

        Returns:
            SQL string ready for execution

        Raises:
            CompilationError: If plan cannot be compiled
        """
        try:
            # Build SQL components
            select_clause = self._build_select(plan)
            from_clause = self._build_from(plan)
            where_clause = self._build_where(plan)
            group_by_clause = self._build_group_by(plan)
            order_by_clause = self._build_order_by(plan)
            limit_clause = self._build_limit(plan)

            # Assemble SQL
            sql_parts = [select_clause, from_clause]

            if where_clause:
                sql_parts.append(where_clause)

            if group_by_clause:
                sql_parts.append(group_by_clause)

            if order_by_clause:
                sql_parts.append(order_by_clause)

            if limit_clause:
                sql_parts.append(limit_clause)

            sql = "\n".join(sql_parts)

            return sql

        except Exception as e:
            raise CompilationError(f"Failed to compile QueryPlan: {e}") from e

    def _build_select(self, plan: QueryPlan) -> str:
        """Build SELECT clause."""
        if not plan.select:
            # No select specified: SELECT * (with LIMIT enforcement)
            return "SELECT *"

        columns = []
        for item in plan.select:
            if isinstance(item, SelectColumn):
                if item.column:
                    col = self._escape_identifier(item.column)
                    if item.alias:
                        col += f" AS {self._escape_identifier(item.alias)}"
                    columns.append(col)
                elif item.expr:
                    # Computed expression
                    expr = item.expr  # TODO: Consider validating/sanitizing
                    if item.alias:
                        expr += f" AS {self._escape_identifier(item.alias)}"
                    columns.append(expr)

            elif isinstance(item, Aggregation):
                agg_col = self._build_aggregation(item)
                columns.append(agg_col)

        if not columns:
            raise CompilationError("No columns in SELECT clause")

        return "SELECT\n  " + ",\n  ".join(columns)

    def _build_aggregation(self, agg: Aggregation) -> str:
        """Build aggregation expression."""
        func = agg.func.value.upper()
        column = self._escape_identifier(agg.column)
        alias = self._escape_identifier(agg.alias)

        if func == "COUNT_DISTINCT":
            return f"COUNT(DISTINCT {column}) AS {alias}"
        else:
            return f"{func}({column}) AS {alias}"

    def _build_from(self, plan: QueryPlan) -> str:
        """Build FROM clause."""
        table = self._escape_identifier(plan.table)
        return f"FROM {table}"

    def _build_where(self, plan: QueryPlan) -> str:
        """Build WHERE clause."""
        if not plan.filters:
            return ""

        conditions = []
        for f in plan.filters:
            condition = self._build_filter(f)
            conditions.append(condition)

        if not conditions:
            return ""

        return "WHERE\n  " + "\n  AND ".join(conditions)

    def _build_filter(self, f: Filter) -> str:
        """Build a single filter condition."""
        column = self._escape_identifier(f.column)
        op = f.op

        if op == FilterOperator.IS_NULL:
            return f"{column} IS NULL"

        if op == FilterOperator.IS_NOT_NULL:
            return f"{column} IS NOT NULL"

        # Operators that require a value
        if op == FilterOperator.EQ:
            return f"{column} = {self._format_value(f.value)}"

        if op == FilterOperator.NE:
            return f"{column} != {self._format_value(f.value)}"

        if op == FilterOperator.LT:
            return f"{column} < {self._format_value(f.value)}"

        if op == FilterOperator.LTE:
            return f"{column} <= {self._format_value(f.value)}"

        if op == FilterOperator.GT:
            return f"{column} > {self._format_value(f.value)}"

        if op == FilterOperator.GTE:
            return f"{column} >= {self._format_value(f.value)}"

        if op == FilterOperator.IN:
            values = ", ".join(self._format_value(v) for v in f.value)
            return f"{column} IN ({values})"

        if op == FilterOperator.BETWEEN:
            low = self._format_value(f.value[0])
            high = self._format_value(f.value[1])
            return f"{column} BETWEEN {low} AND {high}"

        if op == FilterOperator.CONTAINS:
            pattern = self._escape_like_pattern(str(f.value))
            return f"{column} LIKE '%{pattern}%'"

        if op == FilterOperator.STARTSWITH:
            pattern = self._escape_like_pattern(str(f.value))
            return f"{column} LIKE '{pattern}%'"

        if op == FilterOperator.ENDSWITH:
            pattern = self._escape_like_pattern(str(f.value))
            return f"{column} LIKE '%{pattern}'"

        raise CompilationError(f"Unsupported filter operator: {op}")

    def _build_group_by(self, plan: QueryPlan) -> str:
        """Build GROUP BY clause."""
        if not plan.group_by:
            return ""

        columns = [self._escape_identifier(col) for col in plan.group_by]
        return "GROUP BY " + ", ".join(columns)

    def _build_order_by(self, plan: QueryPlan) -> str:
        """Build ORDER BY clause."""
        if not plan.order_by:
            return ""

        order_items = []
        for order in plan.order_by:
            expr = self._escape_identifier(order.expr)
            direction = order.direction.value.upper()
            order_items.append(f"{expr} {direction}")

        return "ORDER BY " + ", ".join(order_items)

    def _build_limit(self, plan: QueryPlan) -> str:
        """Build LIMIT clause (always enforced)."""
        limit = plan.limit if plan.limit is not None else 200
        return f"LIMIT {limit}"

    def _escape_identifier(self, identifier: str) -> str:
        """
        Escape SQL identifier (table/column name).

        Uses double quotes for DuckDB compatibility.
        """
        # Remove any existing quotes
        identifier = identifier.strip('"')

        # Basic validation: alphanumeric + underscore
        if not all(c.isalnum() or c == '_' for c in identifier):
            raise CompilationError(
                f"Invalid identifier: {identifier}. "
                "Only alphanumeric and underscore allowed."
            )

        return f'"{identifier}"'

    def _format_value(self, value) -> str:
        """
        Format a value for SQL.

        Handles strings, numbers, booleans, None.
        """
        if value is None:
            return "NULL"

        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"

        if isinstance(value, (int, float)):
            return str(value)

        if isinstance(value, str):
            # Escape single quotes
            escaped = value.replace("'", "''")
            return f"'{escaped}'"

        raise CompilationError(f"Unsupported value type: {type(value)}")

    def _escape_like_pattern(self, pattern: str) -> str:
        """
        Escape special characters in LIKE pattern.

        Escapes: % and _
        """
        pattern = pattern.replace("%", "\\%")
        pattern = pattern.replace("_", "\\_")
        pattern = pattern.replace("'", "''")  # SQL string escaping
        return pattern

    def validate_data_exfil_heuristic(self, plan: QueryPlan) -> bool:
        """
        Check for potential data exfiltration attempts.

        Heuristic: Reject queries that:
        - Select many columns (>20)
        - Have no aggregation
        - Have no filters or very loose filters
        - Have a high limit (>200)

        Returns:
            True if query seems safe, False if suspicious
        """
        # If using aggregations, generally safe
        has_agg = any(
            isinstance(s, Aggregation) for s in (plan.select or [])
        )
        if has_agg:
            return True

        # If selecting specific columns (not *), check count
        if plan.select:
            num_columns = len(plan.select)
            if num_columns > self.MAX_COLUMNS_WITHOUT_AGGREGATION:
                # Many columns without aggregation: suspicious
                if not plan.filters or len(plan.filters) == 0:
                    # No filters either: very suspicious
                    return False

        # High limit without filters: suspicious
        if (plan.limit or 200) > 200 and (not plan.filters or len(plan.filters) == 0):
            return False

        return True
