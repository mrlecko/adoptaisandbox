"""
QueryPlan JSON DSL models.

Supports structured query representation with future extensibility
for non-SQL query types (Python, custom JSON queries, etc.).
"""

from enum import Enum
from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class FilterOperator(str, Enum):
    """Supported filter operators."""
    EQ = "="
    NE = "!="
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    IN = "in"
    BETWEEN = "between"
    CONTAINS = "contains"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class AggregationFunction(str, Enum):
    """Supported aggregation functions."""
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class SortDirection(str, Enum):
    """Sort direction."""
    ASC = "asc"
    DESC = "desc"


class Filter(BaseModel):
    """
    A single filter condition.

    Examples:
        Filter(column="status", op="=", value="completed")
        Filter(column="total", op=">", value=100)
        Filter(column="category", op="in", value=["Electronics", "Home"])
        Filter(column="price", op="between", value=[10, 100])
        Filter(column="name", op="contains", value="wireless")
        Filter(column="resolved_at", op="is_null")
    """
    column: str = Field(..., description="Column name to filter on")
    op: FilterOperator = Field(..., description="Filter operator")
    value: Optional[Union[str, int, float, bool, List[Any]]] = Field(
        None,
        description="Value to compare against (not needed for is_null/is_not_null)"
    )

    @model_validator(mode='after')
    def validate_operator_value(self):
        """Validate that value is provided when required."""
        if self.op in [FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL]:
            if self.value is not None:
                raise ValueError(f"Operator {self.op} should not have a value")
        else:
            if self.value is None:
                raise ValueError(f"Operator {self.op} requires a value")

        # Validate value types for specific operators
        if self.op == FilterOperator.IN:
            if not isinstance(self.value, list):
                raise ValueError("Operator 'in' requires a list value")

        if self.op == FilterOperator.BETWEEN:
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("Operator 'between' requires a list of exactly 2 values")

        return self


class SelectColumn(BaseModel):
    """
    A column selection (simple or computed).

    For simple columns, just specify the column name.
    For computed/aliased columns, use the 'expr' field.
    """
    column: Optional[str] = Field(None, description="Column name for simple select")
    expr: Optional[str] = Field(None, description="SQL expression for computed columns")
    alias: Optional[str] = Field(None, description="Alias for the column")

    @model_validator(mode='after')
    def validate_column_or_expr(self):
        """Ensure either column or expr is provided."""
        if not self.column and not self.expr:
            raise ValueError("Either 'column' or 'expr' must be provided")
        return self


class Aggregation(BaseModel):
    """
    An aggregation function.

    Examples:
        Aggregation(func="sum", column="total", alias="total_revenue")
        Aggregation(func="count", column="order_id", alias="order_count")
        Aggregation(func="avg", column="price", alias="avg_price")
    """
    func: AggregationFunction = Field(..., description="Aggregation function")
    column: str = Field(..., description="Column to aggregate")
    alias: str = Field(..., description="Alias for the aggregated result")


class OrderBy(BaseModel):
    """
    Sort specification.

    Examples:
        OrderBy(expr="total_revenue", direction="desc")
        OrderBy(expr="customer_id", direction="asc")
    """
    expr: str = Field(..., description="Column name or alias to sort by")
    direction: SortDirection = Field(
        SortDirection.ASC,
        description="Sort direction"
    )


class QueryPlan(BaseModel):
    """
    Structured query plan (JSON DSL).

    This is the primary query representation that will be compiled to SQL.
    Designed to be validated, deterministic, and safe.

    Example:
        QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[SelectColumn(column="order_id"), SelectColumn(column="total")],
            filters=[Filter(column="status", op="=", value="completed")],
            order_by=[OrderBy(expr="total", direction="desc")],
            limit=10
        )
    """
    dataset_id: str = Field(..., description="Dataset identifier")
    table: str = Field(..., description="Primary table name")

    select: Optional[List[Union[SelectColumn, Aggregation]]] = Field(
        None,
        description="Columns to select (simple or aggregated)"
    )

    filters: Optional[List[Filter]] = Field(
        default_factory=list,
        description="Filter conditions (WHERE clause)"
    )

    group_by: Optional[List[str]] = Field(
        default_factory=list,
        description="Columns to group by"
    )

    order_by: Optional[List[OrderBy]] = Field(
        default_factory=list,
        description="Sort specification"
    )

    limit: Optional[int] = Field(
        200,
        ge=1,
        le=1000,
        description="Maximum rows to return (enforced, default 200)"
    )

    notes: Optional[str] = Field(
        None,
        description="Optional explanation from the model about the query"
    )

    @field_validator('select')
    @classmethod
    def validate_select(cls, v):
        """Ensure select is not empty if provided."""
        if v is not None and len(v) == 0:
            raise ValueError("Select list cannot be empty if provided")
        return v

    @model_validator(mode='after')
    def validate_aggregations(self):
        """
        Validate aggregation rules:
        - If aggregations present, must have group_by (unless all are aggregations)
        - Columns in select must be in group_by if mixing with aggregations
        """
        if not self.select:
            return self

        # Check if we have any aggregations
        has_agg = any(isinstance(s, Aggregation) for s in self.select)
        has_simple = any(isinstance(s, SelectColumn) for s in self.select)

        if has_agg and has_simple:
            # Mixed: need group_by
            simple_columns = [
                s.column for s in self.select
                if isinstance(s, SelectColumn) and s.column
            ]
            if not self.group_by:
                raise ValueError(
                    "When mixing aggregations with regular columns, "
                    "group_by is required"
                )
            # All simple columns should be in group_by
            for col in simple_columns:
                if col not in self.group_by:
                    raise ValueError(
                        f"Column '{col}' must be in group_by when using aggregations"
                    )

        return self


class QueryType(str, Enum):
    """
    Type of query to execute.

    Extensible for future query types:
    - PLAN: Structured QueryPlan (current default)
    - SQL: Raw SQL (validated)
    - PYTHON: Python code (future, sandboxed)
    - JSON_QUERY: Custom JSON query language (future)
    """
    PLAN = "plan"
    SQL = "sql"
    PYTHON = "python"  # Future
    JSON_QUERY = "json_query"  # Future


class QueryRequest(BaseModel):
    """
    Top-level query request envelope.

    Extensible design to support multiple query types.
    For MVP, only 'plan' and 'sql' types are supported.

    Examples:
        # QueryPlan request
        QueryRequest(
            query_type="plan",
            plan=QueryPlan(...)
        )

        # Raw SQL request (future)
        QueryRequest(
            query_type="sql",
            sql="SELECT * FROM orders LIMIT 10"
        )
    """
    dataset_id: str = Field(..., description="Dataset to query")
    query_type: QueryType = Field(
        QueryType.PLAN,
        description="Type of query"
    )

    # Query content (only one should be provided based on query_type)
    plan: Optional[QueryPlan] = Field(None, description="Structured query plan")
    sql: Optional[str] = Field(None, description="Raw SQL query (validated)")
    python_code: Optional[str] = Field(None, description="Python code (future)")

    # Execution parameters
    timeout_seconds: Optional[int] = Field(
        10,
        ge=1,
        le=60,
        description="Query timeout"
    )
    max_rows: Optional[int] = Field(
        200,
        ge=1,
        le=1000,
        description="Maximum rows to return"
    )

    @model_validator(mode='after')
    def validate_query_content(self):
        """Ensure appropriate query content is provided for the query type."""
        if self.query_type == QueryType.PLAN:
            if not self.plan:
                raise ValueError("QueryPlan must be provided for query_type='plan'")
            if self.sql or self.python_code:
                raise ValueError("Only 'plan' should be provided for query_type='plan'")

        elif self.query_type == QueryType.SQL:
            if not self.sql:
                raise ValueError("SQL must be provided for query_type='sql'")
            if self.plan or self.python_code:
                raise ValueError("Only 'sql' should be provided for query_type='sql'")

        elif self.query_type == QueryType.PYTHON:
            raise ValueError("Python query type not yet implemented")

        elif self.query_type == QueryType.JSON_QUERY:
            raise ValueError("JSON query type not yet implemented")

        return self


# Example usage / documentation
EXAMPLE_QUERY_PLANS = {
    "simple_select": QueryPlan(
        dataset_id="ecommerce",
        table="orders",
        select=[
            SelectColumn(column="order_id"),
            SelectColumn(column="total")
        ],
        filters=[
            Filter(column="status", op=FilterOperator.EQ, value="completed")
        ],
        order_by=[OrderBy(expr="total", direction=SortDirection.DESC)],
        limit=10
    ),

    "aggregation": QueryPlan(
        dataset_id="ecommerce",
        table="order_items",
        select=[
            SelectColumn(column="category"),
            Aggregation(func=AggregationFunction.SUM, column="price", alias="total_revenue"),
            Aggregation(func=AggregationFunction.COUNT, column="item_id", alias="item_count")
        ],
        group_by=["category"],
        order_by=[OrderBy(expr="total_revenue", direction=SortDirection.DESC)],
        limit=20
    ),

    "complex_filters": QueryPlan(
        dataset_id="support",
        table="tickets",
        select=[
            SelectColumn(column="ticket_id"),
            SelectColumn(column="priority"),
            SelectColumn(column="created_at")
        ],
        filters=[
            Filter(column="status", op=FilterOperator.EQ, value="Open"),
            Filter(column="priority", op=FilterOperator.IN, value=["High", "Critical"]),
            Filter(column="created_at", op=FilterOperator.GTE, value="2024-01-01")
        ],
        order_by=[OrderBy(expr="created_at", direction=SortDirection.ASC)],
        limit=50
    )
}
