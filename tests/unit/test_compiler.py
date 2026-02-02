"""
Unit tests for QueryPlanCompiler.

Tests SQL compilation, determinism, and safety features.
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.models.query_plan import (
    QueryPlan,
    Filter,
    FilterOperator,
    Aggregation,
    AggregationFunction,
    SelectColumn,
    OrderBy,
    SortDirection,
)
from app.validators.compiler import QueryPlanCompiler, CompilationError


class TestBasicCompilation:
    """Test basic SQL compilation."""

    def setup_method(self):
        """Set up compiler for each test."""
        self.compiler = QueryPlanCompiler()

    def test_simple_select_all(self):
        """Test compiling SELECT * query."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            limit=10
        )
        sql = self.compiler.compile(plan)

        assert "SELECT *" in sql
        assert 'FROM "orders"' in sql
        assert "LIMIT 10" in sql

    def test_simple_select_columns(self):
        """Test selecting specific columns."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column="order_id"),
                SelectColumn(column="total")
            ],
            limit=5
        )
        sql = self.compiler.compile(plan)

        assert '"order_id"' in sql
        assert '"total"' in sql
        assert 'FROM "orders"' in sql
        assert "LIMIT 5" in sql

    def test_column_with_alias(self):
        """Test column with alias."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column="customer_id", alias="cust_id")
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"customer_id" AS "cust_id"' in sql

    def test_default_limit(self):
        """Test that limit defaults to 200."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders"
        )
        sql = self.compiler.compile(plan)

        assert "LIMIT 200" in sql


class TestFilterCompilation:
    """Test filter compilation."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_equality_filter(self):
        """Test = operator."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            filters=[
                Filter(column="status", op=FilterOperator.EQ, value="completed")
            ]
        )
        sql = self.compiler.compile(plan)

        assert "WHERE" in sql
        assert '"status" = \'completed\'' in sql

    def test_numeric_filters(self):
        """Test numeric comparison operators."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            filters=[
                Filter(column="total", op=FilterOperator.GT, value=100),
                Filter(column="quantity", op=FilterOperator.LTE, value=5)
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"total" > 100' in sql
        assert '"quantity" <= 5' in sql

    def test_in_operator(self):
        """Test IN operator."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            filters=[
                Filter(
                    column="category",
                    op=FilterOperator.IN,
                    value=["Electronics", "Clothing"]
                )
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"category" IN (\'Electronics\', \'Clothing\')' in sql

    def test_between_operator(self):
        """Test BETWEEN operator."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            filters=[
                Filter(column="price", op=FilterOperator.BETWEEN, value=[10, 100])
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"price" BETWEEN 10 AND 100' in sql

    def test_null_operators(self):
        """Test IS NULL and IS NOT NULL."""
        plan = QueryPlan(
            dataset_id="support",
            table="tickets",
            filters=[
                Filter(column="resolved_at", op=FilterOperator.IS_NULL),
                Filter(column="csat_score", op=FilterOperator.IS_NOT_NULL)
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"resolved_at" IS NULL' in sql
        assert '"csat_score" IS NOT NULL' in sql

    def test_string_pattern_operators(self):
        """Test LIKE operators (contains, startswith, endswith)."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="inventory",
            filters=[
                Filter(column="name", op=FilterOperator.CONTAINS, value="wireless"),
                Filter(column="sku", op=FilterOperator.STARTSWITH, value="ELEC"),
                Filter(column="category", op=FilterOperator.ENDSWITH, value="ics")
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"name" LIKE \'%wireless%\'' in sql
        assert '"sku" LIKE \'ELEC%\'' in sql
        assert '"category" LIKE \'%ics\'' in sql

    def test_boolean_filter(self):
        """Test boolean values in filters."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            filters=[
                Filter(column="returned", op=FilterOperator.EQ, value=True)
            ]
        )
        sql = self.compiler.compile(plan)

        assert '"returned" = TRUE' in sql

    def test_multiple_filters_with_and(self):
        """Test multiple filters are AND-ed."""
        plan = QueryPlan(
            dataset_id="support",
            table="tickets",
            filters=[
                Filter(column="status", op=FilterOperator.EQ, value="Open"),
                Filter(column="priority", op=FilterOperator.EQ, value="High")
            ]
        )
        sql = self.compiler.compile(plan)

        assert "WHERE" in sql
        assert '"status" = \'Open\'' in sql
        assert '"priority" = \'High\'' in sql
        assert "AND" in sql


class TestAggregationCompilation:
    """Test aggregation compilation."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_simple_aggregation(self):
        """Test basic aggregation functions."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                Aggregation(func=AggregationFunction.COUNT, column="order_id", alias="total_orders")
            ]
        )
        sql = self.compiler.compile(plan)

        assert 'COUNT("order_id") AS "total_orders"' in sql

    def test_count_distinct(self):
        """Test COUNT(DISTINCT ...) aggregation."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                Aggregation(
                    func=AggregationFunction.COUNT_DISTINCT,
                    column="customer_id",
                    alias="unique_customers"
                )
            ]
        )
        sql = self.compiler.compile(plan)

        assert 'COUNT(DISTINCT "customer_id") AS "unique_customers"' in sql

    def test_multiple_aggregations(self):
        """Test multiple aggregation functions."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                Aggregation(func=AggregationFunction.SUM, column="total", alias="revenue"),
                Aggregation(func=AggregationFunction.AVG, column="total", alias="avg_order"),
                Aggregation(func=AggregationFunction.COUNT, column="order_id", alias="count")
            ]
        )
        sql = self.compiler.compile(plan)

        assert 'SUM("total") AS "revenue"' in sql
        assert 'AVG("total") AS "avg_order"' in sql
        assert 'COUNT("order_id") AS "count"' in sql

    def test_aggregation_with_group_by(self):
        """Test aggregation with GROUP BY."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="order_items",
            select=[
                SelectColumn(column="category"),
                Aggregation(func=AggregationFunction.SUM, column="price", alias="total_revenue")
            ],
            group_by=["category"]
        )
        sql = self.compiler.compile(plan)

        assert '"category"' in sql
        assert 'SUM("price") AS "total_revenue"' in sql
        assert 'GROUP BY "category"' in sql


class TestOrderByCompilation:
    """Test ORDER BY compilation."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_simple_order_by(self):
        """Test simple ORDER BY."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[SelectColumn(column="total")],
            order_by=[OrderBy(expr="total", direction=SortDirection.DESC)]
        )
        sql = self.compiler.compile(plan)

        assert 'ORDER BY "total" DESC' in sql

    def test_multiple_order_by(self):
        """Test multiple ORDER BY columns."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column="customer_id"),
                SelectColumn(column="order_date")
            ],
            order_by=[
                OrderBy(expr="customer_id", direction=SortDirection.ASC),
                OrderBy(expr="order_date", direction=SortDirection.DESC)
            ]
        )
        sql = self.compiler.compile(plan)

        assert 'ORDER BY "customer_id" ASC, "order_date" DESC' in sql


class TestSQLEscaping:
    """Test SQL escaping and safety features."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_string_value_escaping(self):
        """Test that single quotes are escaped in string values."""
        plan = QueryPlan(
            dataset_id="test",
            table="t",
            filters=[
                Filter(column="name", op=FilterOperator.EQ, value="O'Reilly")
            ]
        )
        sql = self.compiler.compile(plan)

        # Single quote should be escaped as ''
        assert "\'O\'\'Reilly\'" in sql

    def test_like_pattern_escaping(self):
        """Test that LIKE special characters are escaped."""
        plan = QueryPlan(
            dataset_id="test",
            table="t",
            filters=[
                Filter(column="pattern", op=FilterOperator.CONTAINS, value="50%_off")
            ]
        )
        sql = self.compiler.compile(plan)

        # % and _ should be escaped
        assert "50\\%\\_off" in sql

    def test_identifier_validation(self):
        """Test that invalid identifiers are rejected."""
        plan = QueryPlan(
            dataset_id="test",
            table="bad; DROP TABLE",  # SQL injection attempt
            select=[SelectColumn(column="col")]
        )

        with pytest.raises(CompilationError, match="Invalid identifier"):
            self.compiler.compile(plan)

    def test_valid_identifiers_with_underscores(self):
        """Test that underscores in identifiers are allowed."""
        plan = QueryPlan(
            dataset_id="test",
            table="order_items",
            select=[SelectColumn(column="product_id")]
        )
        sql = self.compiler.compile(plan)

        assert '"order_items"' in sql
        assert '"product_id"' in sql


class TestDeterminism:
    """Test that compilation is deterministic."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_same_plan_same_sql(self):
        """Test that the same plan produces the same SQL."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column="order_id"),
                SelectColumn(column="total")
            ],
            filters=[
                Filter(column="status", op=FilterOperator.EQ, value="completed"),
                Filter(column="total", op=FilterOperator.GT, value=100)
            ],
            order_by=[OrderBy(expr="total", direction=SortDirection.DESC)],
            limit=10
        )

        sql1 = self.compiler.compile(plan)
        sql2 = self.compiler.compile(plan)

        assert sql1 == sql2


class TestDataExfilHeuristic:
    """Test data exfiltration heuristic."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_safe_aggregation_query(self):
        """Test that aggregation queries are considered safe."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                Aggregation(func=AggregationFunction.COUNT, column="order_id", alias="count")
            ]
        )
        assert self.compiler.validate_data_exfil_heuristic(plan) is True

    def test_safe_filtered_query(self):
        """Test that queries with filters are considered safe."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column=f"col{i}") for i in range(25)
            ],
            filters=[
                Filter(column="status", op=FilterOperator.EQ, value="completed")
            ]
        )
        # Many columns but with filters: safe
        assert self.compiler.validate_data_exfil_heuristic(plan) is True

    def test_suspicious_many_columns_no_filters(self):
        """Test that many columns without filters is suspicious."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[
                SelectColumn(column=f"col{i}") for i in range(25)
            ]
            # No filters
        )
        assert self.compiler.validate_data_exfil_heuristic(plan) is False

    def test_suspicious_high_limit_no_filters(self):
        """Test that high limit without filters is suspicious."""
        plan = QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[SelectColumn(column="order_id")],
            limit=500
            # No filters
        )
        assert self.compiler.validate_data_exfil_heuristic(plan) is False


class TestGoldenQueries:
    """Test compilation of golden queries from use case specs."""

    def setup_method(self):
        self.compiler = QueryPlanCompiler()

    def test_ecommerce_top_products(self):
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
        sql = self.compiler.compile(plan)

        assert 'SELECT' in sql
        assert '"product_id"' in sql
        assert 'SUM("price") AS "total_revenue"' in sql
        assert 'GROUP BY "product_id"' in sql
        assert 'ORDER BY "total_revenue" DESC' in sql
        assert 'LIMIT 10' in sql

    def test_support_sla_compliance(self):
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
        sql = self.compiler.compile(plan)

        assert '"priority"' in sql
        assert 'COUNT("ticket_id") AS "total_tickets"' in sql
        assert '"status" IN (\'Resolved\', \'Closed\')' in sql
        assert 'GROUP BY "priority"' in sql

    def test_sensors_anomalies(self):
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
        sql = self.compiler.compile(plan)

        assert '"anomaly_flag" = TRUE' in sql
        assert '"timestamp" >= \'2024-01-01\'' in sql
        assert 'ORDER BY "anomaly_count" DESC' in sql


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
