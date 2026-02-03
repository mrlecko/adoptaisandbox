#!/usr/bin/env python3
"""
Demo script for QueryPlan DSL and SQL Compiler.

Shows how to create query plans and compile them to SQL.
"""

from app.models.query_plan import (
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
from app.validators.compiler import QueryPlanCompiler


def demo_simple_query():
    """Demo: Simple SELECT with filters."""
    print("=" * 60)
    print("DEMO 1: Simple SELECT with filters")
    print("=" * 60)

    plan = QueryPlan(
        dataset_id="ecommerce",
        table="orders",
        select=[
            SelectColumn(column="order_id"),
            SelectColumn(column="customer_id"),
            SelectColumn(column="total"),
        ],
        filters=[
            Filter(column="status", op=FilterOperator.EQ, value="completed"),
            Filter(column="total", op=FilterOperator.GT, value=100),
        ],
        order_by=[OrderBy(expr="total", direction=SortDirection.DESC)],
        limit=10,
    )

    compiler = QueryPlanCompiler()
    sql = compiler.compile(plan)

    print("\nQueryPlan:")
    print(plan.model_dump_json(indent=2))
    print("\nCompiled SQL:")
    print(sql)
    print()


def demo_aggregation_query():
    """Demo: Aggregation with GROUP BY."""
    print("=" * 60)
    print("DEMO 2: Aggregation with GROUP BY")
    print("=" * 60)

    plan = QueryPlan(
        dataset_id="ecommerce",
        table="order_items",
        select=[
            SelectColumn(column="category"),
            Aggregation(
                func=AggregationFunction.SUM, column="price", alias="total_revenue"
            ),
            Aggregation(
                func=AggregationFunction.COUNT, column="item_id", alias="item_count"
            ),
            Aggregation(
                func=AggregationFunction.AVG, column="price", alias="avg_price"
            ),
        ],
        group_by=["category"],
        order_by=[OrderBy(expr="total_revenue", direction=SortDirection.DESC)],
        limit=20,
    )

    compiler = QueryPlanCompiler()
    sql = compiler.compile(plan)

    print("\nQueryPlan:")
    print(plan.model_dump_json(indent=2))
    print("\nCompiled SQL:")
    print(sql)
    print()


def demo_complex_filters():
    """Demo: Complex filters (IN, BETWEEN, NULL checks)."""
    print("=" * 60)
    print("DEMO 3: Complex filters")
    print("=" * 60)

    plan = QueryPlan(
        dataset_id="support",
        table="tickets",
        select=[
            SelectColumn(column="ticket_id"),
            SelectColumn(column="priority"),
            SelectColumn(column="created_at"),
            SelectColumn(column="csat_score"),
        ],
        filters=[
            Filter(column="status", op=FilterOperator.EQ, value="Open"),
            Filter(column="priority", op=FilterOperator.IN, value=["High", "Critical"]),
            Filter(column="csat_score", op=FilterOperator.IS_NULL),
            Filter(column="created_at", op=FilterOperator.GTE, value="2024-01-01"),
        ],
        order_by=[OrderBy(expr="created_at", direction=SortDirection.ASC)],
        limit=50,
    )

    compiler = QueryPlanCompiler()
    sql = compiler.compile(plan)

    print("\nQueryPlan:")
    print(plan.model_dump_json(indent=2))
    print("\nCompiled SQL:")
    print(sql)
    print()


def demo_string_patterns():
    """Demo: String pattern matching (LIKE)."""
    print("=" * 60)
    print("DEMO 4: String pattern matching")
    print("=" * 60)

    plan = QueryPlan(
        dataset_id="ecommerce",
        table="inventory",
        select=[
            SelectColumn(column="product_id"),
            SelectColumn(column="name"),
            SelectColumn(column="category"),
            SelectColumn(column="stock"),
        ],
        filters=[
            Filter(column="name", op=FilterOperator.CONTAINS, value="wireless"),
            Filter(column="stock", op=FilterOperator.LTE, value=20),
        ],
        order_by=[OrderBy(expr="stock", direction=SortDirection.ASC)],
        limit=30,
    )

    compiler = QueryPlanCompiler()
    sql = compiler.compile(plan)

    print("\nQueryPlan:")
    print(plan.model_dump_json(indent=2))
    print("\nCompiled SQL:")
    print(sql)
    print()


def demo_query_request():
    """Demo: QueryRequest envelope."""
    print("=" * 60)
    print("DEMO 5: QueryRequest (extensible envelope)")
    print("=" * 60)

    # QueryPlan request
    request = QueryRequest(
        dataset_id="ecommerce",
        query_type=QueryType.PLAN,
        plan=QueryPlan(
            dataset_id="ecommerce",
            table="orders",
            select=[SelectColumn(column="order_id")],
            limit=5,
        ),
        timeout_seconds=10,
        max_rows=200,
    )

    print("\nQueryRequest (PLAN type):")
    print(request.model_dump_json(indent=2))
    print()

    # Raw SQL request (for future)
    sql_request = QueryRequest(
        dataset_id="ecommerce",
        query_type=QueryType.SQL,
        sql="SELECT * FROM orders WHERE status = 'completed' LIMIT 10",
        timeout_seconds=5,
    )

    print("\nQueryRequest (SQL type):")
    print(sql_request.model_dump_json(indent=2))
    print()


def demo_data_exfil_detection():
    """Demo: Data exfiltration heuristic."""
    print("=" * 60)
    print("DEMO 6: Data exfiltration detection")
    print("=" * 60)

    compiler = QueryPlanCompiler()

    # Safe query: aggregation
    safe_plan = QueryPlan(
        dataset_id="ecommerce",
        table="orders",
        select=[
            Aggregation(
                func=AggregationFunction.COUNT, column="order_id", alias="count"
            )
        ],
    )

    print("\nSafe query (aggregation):")
    is_safe = compiler.validate_data_exfil_heuristic(safe_plan)
    print(f"  Is safe: {is_safe}")

    # Suspicious query: many columns, no filters
    suspicious_plan = QueryPlan(
        dataset_id="ecommerce",
        table="orders",
        select=[SelectColumn(column=f"col{i}") for i in range(25)],
    )

    print("\nSuspicious query (25 columns, no filters):")
    is_safe = compiler.validate_data_exfil_heuristic(suspicious_plan)
    print(f"  Is safe: {is_safe}")

    # Safe query: many columns but with filters
    safe_plan2 = QueryPlan(
        dataset_id="ecommerce",
        table="orders",
        select=[SelectColumn(column=f"col{i}") for i in range(25)],
        filters=[Filter(column="status", op=FilterOperator.EQ, value="completed")],
    )

    print("\nSafe query (25 columns but with filters):")
    is_safe = compiler.validate_data_exfil_heuristic(safe_plan2)
    print(f"  Is safe: {is_safe}")
    print()


def demo_golden_query():
    """Demo: One of the golden queries from use cases."""
    print("=" * 60)
    print("DEMO 7: Golden Query - Top Products by Revenue")
    print("=" * 60)

    plan = QueryPlan(
        dataset_id="ecommerce",
        table="order_items",
        select=[
            SelectColumn(column="product_id"),
            Aggregation(
                func=AggregationFunction.SUM, column="price", alias="total_revenue"
            ),
        ],
        group_by=["product_id"],
        order_by=[OrderBy(expr="total_revenue", direction=SortDirection.DESC)],
        limit=10,
        notes="Find the top 10 products by total revenue",
    )

    compiler = QueryPlanCompiler()
    sql = compiler.compile(plan)

    print("\nBusiness Question:")
    print("  'What are the top 10 products by revenue?'")
    print("\nQueryPlan:")
    print(plan.model_dump_json(indent=2))
    print("\nCompiled SQL:")
    print(sql)
    print()


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "   QueryPlan DSL & SQL Compiler - Demonstration".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "═" * 58 + "╝")
    print("\n")

    demo_simple_query()
    demo_aggregation_query()
    demo_complex_filters()
    demo_string_patterns()
    demo_query_request()
    demo_data_exfil_detection()
    demo_golden_query()

    print("=" * 60)
    print("All demos completed successfully!")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
