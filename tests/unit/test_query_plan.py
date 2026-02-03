"""
Unit tests for QueryPlan models.

Tests validation, schema constraints, and edge cases.
"""

import pytest
from pydantic import ValidationError

import sys
from pathlib import Path
# Add agent-server to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.models.query_plan import (  # noqa: E402
    QueryPlan,
    Filter,
    FilterOperator,
    Aggregation,
    AggregationFunction,
    SelectColumn,
    OrderBy,
    SortDirection,
    QueryRequest,
    QueryType,
)


class TestFilterValidation:
    """Test Filter model validation."""

    def test_valid_simple_filter(self):
        """Test creating valid simple filters."""
        f = Filter(column="status", op=FilterOperator.EQ, value="completed")
        assert f.column == "status"
        assert f.op == FilterOperator.EQ
        assert f.value == "completed"

    def test_valid_numeric_filter(self):
        """Test numeric comparison filters."""
        f = Filter(column="total", op=FilterOperator.GT, value=100)
        assert f.value == 100

        f = Filter(column="price", op=FilterOperator.BETWEEN, value=[10, 100])
        assert f.value == [10, 100]

    def test_valid_in_filter(self):
        """Test IN operator with list."""
        f = Filter(
            column="category",
            op=FilterOperator.IN,
            value=["Electronics", "Clothing"]
        )
        assert isinstance(f.value, list)
        assert len(f.value) == 2

    def test_valid_null_filters(self):
        """Test NULL checking filters."""
        f = Filter(column="resolved_at", op=FilterOperator.IS_NULL)
        assert f.value is None

        f = Filter(column="resolved_at", op=FilterOperator.IS_NOT_NULL)
        assert f.value is None

    def test_valid_string_pattern_filters(self):
        """Test string pattern matching filters."""
        f = Filter(column="name", op=FilterOperator.CONTAINS, value="wireless")
        assert f.value == "wireless"

        f = Filter(column="email", op=FilterOperator.STARTSWITH, value="admin")
        f = Filter(column="file", op=FilterOperator.ENDSWITH, value=".csv")

    def test_invalid_null_with_value(self):
        """Test that IS_NULL cannot have a value."""
        with pytest.raises(ValidationError, match="should not have a value"):
            Filter(column="x", op=FilterOperator.IS_NULL, value="something")

    def test_invalid_missing_value(self):
        """Test that non-null operators require a value."""
        with pytest.raises(ValidationError, match="requires a value"):
            Filter(column="status", op=FilterOperator.EQ, value=None)

    def test_invalid_in_not_list(self):
        """Test that IN operator requires a list."""
        with pytest.raises(ValidationError, match="requires a list"):
            Filter(column="x", op=FilterOperator.IN, value="not_a_list")

    def test_invalid_between_wrong_length(self):
        """Test that BETWEEN requires exactly 2 values."""
        with pytest.raises(ValidationError, match="exactly 2 values"):
            Filter(column="x", op=FilterOperator.BETWEEN, value=[1, 2, 3])

        with pytest.raises(ValidationError, match="exactly 2 values"):
            Filter(column="x", op=FilterOperator.BETWEEN, value=[1])


class TestSelectColumnValidation:
    """Test SelectColumn model validation."""

    def test_valid_simple_column(self):
        """Test simple column selection."""
        s = SelectColumn(column="order_id")
        assert s.column == "order_id"
        assert s.alias is None

    def test_valid_column_with_alias(self):
        """Test column with alias."""
        s = SelectColumn(column="customer_id", alias="cust_id")
        assert s.alias == "cust_id"

    def test_valid_expression(self):
        """Test expression-based selection."""
        s = SelectColumn(expr="price * quantity", alias="total")
        assert s.expr == "price * quantity"
        assert s.alias == "total"

    def test_invalid_empty_select(self):
        """Test that either column or expr must be provided."""
        with pytest.raises(ValidationError, match="must be provided"):
            SelectColumn()


class TestAggregationValidation:
    """Test Aggregation model validation."""

    def test_valid_aggregations(self):
        """Test all aggregation functions."""
        agg = Aggregation(
            func=AggregationFunction.COUNT,
            column="order_id",
            alias="order_count"
        )
        assert agg.func == AggregationFunction.COUNT

        for func in AggregationFunction:
            agg = Aggregation(func=func, column="test_col", alias="result")
            assert agg.func == func


class TestQueryPlanValidation:
    """Test QueryPlan model validation."""

    def test_valid_simple_query_plan(self):
        """Test creating a valid simple QueryPlan."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column="order_id"),
                SelectColumn(column="total")
            ],
            filters=[
                Filter(column="status", op=FilterOperator.EQ, value="completed")
            ],
            limit=10
        )
        assert plan.dataset_id == "ecommerce"
        assert plan.table == "orders"
        assert len(plan.select) == 2
        assert plan.limit == 10

    def test_valid_aggregation_query_plan(self):
        """Test QueryPlan with aggregations."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="order_items",
            select=[
                SelectColumn(column="category"),
                Aggregation(
                    func=AggregationFunction.SUM,
                    column="price",
                    alias="total_revenue"
                )
            ],
            group_by=["category"],
            limit=20
        )
        assert plan.group_by == ["category"]
        assert len(plan.select) == 2

    def test_valid_all_aggregations(self):
        """Test QueryPlan with only aggregations (no group_by needed)."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                Aggregation(func=AggregationFunction.COUNT, column="order_id", alias="total_orders"),
                Aggregation(func=AggregationFunction.AVG, column="total", alias="avg_order_value")
            ],
            limit=1
        )
        # Should be valid without group_by
        assert plan.select is not None

    def test_default_limit(self):
        """Test that limit defaults to 200."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[SelectColumn(column="order_id")]
        )
        assert plan.limit == 200

    def test_limit_bounds(self):
        """Test limit min/max validation."""
        # Valid limits
        QueryPlan(dataset_id="test", table="t", limit=1)
        QueryPlan(dataset_id="test", table="t", limit=1000)

        # Invalid: too low
        with pytest.raises(ValidationError):
            QueryPlan(dataset_id="test", table="t", limit=0)

        # Invalid: too high
        with pytest.raises(ValidationError):
            QueryPlan(dataset_id="test", table="t", limit=1001)

    def test_invalid_empty_select(self):
        """Test that select cannot be an empty list."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            QueryPlan(
                dataset_id="test",
                table="t",
                select=[]
            )

    def test_invalid_mixed_without_group_by(self):
        """Test that mixing columns and aggregations requires group_by."""
        with pytest.raises(ValidationError, match="group_by is required"):
            QueryPlan(
                dataset_id="ecommerce",
                table="orders",
                select=[
                    SelectColumn(column="customer_id"),
                    Aggregation(func=AggregationFunction.SUM, column="total", alias="sum_total")
                ]
                # Missing group_by
            )

    def test_invalid_column_not_in_group_by(self):
        """Test that selected columns must be in group_by."""
        with pytest.raises(ValidationError, match="must be in group_by"):
            QueryPlan(
                dataset_id="ecommerce",
                table="orders",
                select=[
                    SelectColumn(column="customer_id"),
                    SelectColumn(column="status"),  # Not in group_by!
                    Aggregation(func=AggregationFunction.SUM, column="total", alias="sum_total")
                ],
                group_by=["customer_id"]  # Missing 'status'
            )

    def test_valid_order_by(self):
        """Test ORDER BY specification."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[SelectColumn(column="total")],
            order_by=[
                OrderBy(expr="total", direction=SortDirection.DESC)
            ]
        )
        assert len(plan.order_by) == 1
        assert plan.order_by[0].direction == SortDirection.DESC

    def test_notes_field(self):
        """Test optional notes field."""
        plan = QueryPlan(
            dataset_id="test",
            table="t",
            notes="This query finds completed orders"
        )
        assert plan.notes == "This query finds completed orders"


class TestQueryRequestValidation:
    """Test QueryRequest model validation."""

    def test_valid_plan_request(self):
        """Test valid QueryRequest with QueryPlan."""
        req = QueryRequest(
            dataset_id="ecommerce",
            query_type=QueryType.PLAN,
            plan=QueryPlan(
                dataset_id="ecommerce",
                table="orders"
            )
        )
        assert req.query_type == QueryType.PLAN
        assert req.plan is not None

    def test_valid_sql_request(self):
        """Test valid QueryRequest with raw SQL."""
        req = QueryRequest(
            dataset_id="ecommerce",
            query_type=QueryType.SQL,
            sql="SELECT * FROM orders LIMIT 10"
        )
        assert req.query_type == QueryType.SQL
        assert req.sql is not None

    def test_default_query_type(self):
        """Test that query_type defaults to PLAN."""
        req = QueryRequest(
            dataset_id="ecommerce",
            plan=QueryPlan(dataset_id="ecommerce", table="orders")
        )
        assert req.query_type == QueryType.PLAN

    def test_default_timeout_and_max_rows(self):
        """Test default values for timeout and max_rows."""
        req = QueryRequest(
            dataset_id="ecommerce",
            plan=QueryPlan(dataset_id="ecommerce", table="orders")
        )
        assert req.timeout_seconds == 10
        assert req.max_rows == 200

    def test_invalid_plan_type_missing_plan(self):
        """Test that PLAN type requires a plan."""
        with pytest.raises(ValidationError, match="QueryPlan must be provided"):
            QueryRequest(
                dataset_id="ecommerce",
                query_type=QueryType.PLAN
                # Missing plan
            )

    def test_invalid_sql_type_missing_sql(self):
        """Test that SQL type requires sql."""
        with pytest.raises(ValidationError, match="SQL must be provided"):
            QueryRequest(
                dataset_id="ecommerce",
                query_type=QueryType.SQL
                # Missing sql
            )

    def test_invalid_plan_type_with_sql(self):
        """Test that PLAN type cannot have SQL."""
        with pytest.raises(ValidationError, match="Only 'plan' should be provided"):
            QueryRequest(
                dataset_id="ecommerce",
                query_type=QueryType.PLAN,
                plan=QueryPlan(dataset_id="ecommerce", table="orders"),
                sql="SELECT * FROM orders"  # Should not be here
            )

    def test_python_type_not_implemented(self):
        """Test that PYTHON type raises not implemented."""
        with pytest.raises(ValidationError, match="not yet implemented"):
            QueryRequest(
                dataset_id="ecommerce",
                query_type=QueryType.PYTHON,
                python_code="print('hello')"
            )


class TestComplexScenarios:
    """Test complex real-world query scenarios."""

    def test_ecommerce_top_products_query(self):
        """Test: Top products by revenue."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="order_items",
            select=[
                SelectColumn(column="product_id"),
                Aggregation(func=AggregationFunction.SUM, column="price", alias="total_revenue")
            ],
            group_by=["product_id"],
            order_by=[OrderBy(expr="total_revenue", direction=SortDirection.DESC)],
            limit=10
        )
        assert plan.dataset_id == "ecommerce"

    def test_support_sla_compliance_query(self):
        """Test: SLA compliance by priority."""
        plan = QueryPlan(
            dataset_id="support",
            table="tickets",
            select=[
                SelectColumn(column="priority"),
                Aggregation(func=AggregationFunction.COUNT, column="ticket_id", alias="total_tickets")
            ],
            filters=[
                Filter(column="status", op=FilterOperator.IN, value=["Resolved", "Closed"])
            ],
            group_by=["priority"],
            limit=10
        )
        assert len(plan.filters) == 1

    def test_sensors_anomaly_detection_query(self):
        """Test: Recent anomalies by location."""
        plan = QueryPlan(
            dataset_id="sensors",
            table="sensors",
            select=[
                SelectColumn(column="location"),
                Aggregation(func=AggregationFunction.COUNT, column="sensor_id", alias="anomaly_count")
            ],
            filters=[
                Filter(column="anomaly_flag", op=FilterOperator.EQ, value=True),
                Filter(column="timestamp", op=FilterOperator.GTE, value="2024-01-01")
            ],
            group_by=["location"],
            order_by=[OrderBy(expr="anomaly_count", direction=SortDirection.DESC)],
            limit=20
        )
        assert len(plan.filters) == 2

    def test_multiple_filters_and_sorts(self):
        """Test query with multiple filters and sort orders."""
        plan = QueryPlan(
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
                Filter(column="csat_score", op=FilterOperator.IS_NULL)
            ],
            order_by=[
                OrderBy(expr="priority", direction=SortDirection.ASC),
                OrderBy(expr="created_at", direction=SortDirection.ASC)
            ],
            limit=50
        )
        assert len(plan.filters) == 3
        assert len(plan.order_by) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
