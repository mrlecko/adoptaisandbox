# Use Case 1: E-commerce Analytics Dataset

## Overview

**Dataset ID**: `ecommerce`
**Domain**: Retail/E-commerce
**Primary Use Cases**: Return rate analysis, discount effectiveness, inventory management, customer behavior

## Business Context

This dataset simulates a typical e-commerce platform's transactional data. Analysts need to:
- Monitor return rates and identify problematic product categories
- Analyze discount effectiveness and profitability
- Track inventory levels and reorder needs
- Understand customer ordering patterns
- Identify high-value customers and segments

## Dataset Schema

### File 1: `orders.csv`

**Purpose**: Core order-level transactions

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `order_id` | INTEGER | Unique order identifier | 1001, 1002, ... |
| `customer_id` | INTEGER | Customer identifier (for grouping) | 501, 502, ... |
| `order_date` | DATE | Order placement date | 2024-01-15, 2024-02-20 |
| `total` | DECIMAL(10,2) | Total order value ($) | 125.50, 89.99 |
| `status` | VARCHAR(20) | Order status | completed, returned, cancelled |
| `returned` | BOOLEAN | Whether order was returned | true, false |

**Row Count**: ~5,000 orders
**Date Range**: Last 180 days

### File 2: `order_items.csv`

**Purpose**: Line-item details for multi-item orders

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `item_id` | INTEGER | Unique line item identifier | 10001, 10002, ... |
| `order_id` | INTEGER | FK to orders.order_id | 1001, 1002, ... |
| `product_id` | INTEGER | Product identifier | 201, 202, ... |
| `category` | VARCHAR(50) | Product category | Electronics, Clothing, Home |
| `quantity` | INTEGER | Items ordered | 1, 2, 3 |
| `price` | DECIMAL(10,2) | Unit price ($) | 49.99, 19.95 |
| `discount` | DECIMAL(5,2) | Discount percentage (0-100) | 0, 10, 25 |

**Row Count**: ~12,000 line items (avg 2.4 items per order)

### File 3: `inventory.csv`

**Purpose**: Current inventory levels for products

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `product_id` | INTEGER | Unique product identifier | 201, 202, ... |
| `name` | VARCHAR(100) | Product name | Wireless Mouse, Cotton T-Shirt |
| `category` | VARCHAR(50) | Product category | Electronics, Clothing, Home |
| `stock` | INTEGER | Current stock level | 0, 15, 250 |

**Row Count**: ~500 products

## Data Characteristics

**Distributions**:
- Categories: Electronics (30%), Clothing (35%), Home (20%), Books (10%), Toys (5%)
- Return rate: 12% overall (higher for Clothing ~18%, lower for Books ~5%)
- Discount presence: 40% of items have discounts (range 5-30%)
- Order status: 85% completed, 12% returned, 3% cancelled
- Stock levels: 10% out of stock (0), 30% low stock (<20), 60% adequate

**Temporal patterns**:
- Weekend spike in orders (Sat-Sun +30%)
- Month-end discount campaigns
- Seasonal variation (more clothing in spring/fall)

## Golden Queries

These queries represent canonical analytics tasks and test query DSL capabilities.

### GQ1: Top Products by Revenue (Simple Aggregation + Sort)

**Business Question**: "What are our top 10 products by revenue in the last 30 days?"

**Expected Query Plan**:
```json
{
  "dataset_id": "ecommerce",
  "table": "order_items",
  "select": [
    {"column": "product_id"},
    {"agg": "sum", "column": "price", "as": "total_revenue"}
  ],
  "filters": [
    {"column": "order_date", "op": ">=", "value": "2024-12-01"}
  ],
  "group_by": ["product_id"],
  "order_by": [{"expr": "total_revenue", "dir": "desc"}],
  "limit": 10
}
```

**Expected SQL**:
```sql
SELECT
  product_id,
  SUM(price * quantity) AS total_revenue
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
WHERE o.order_date >= '2024-12-01'
GROUP BY product_id
ORDER BY total_revenue DESC
LIMIT 10;
```

**Success Criteria**: Returns 10 rows with product_id and revenue

---

### GQ2: Return Rate by Category (Join + Aggregation + Calculation)

**Business Question**: "What's the return rate by product category?"

**Expected Query Plan**:
```json
{
  "dataset_id": "ecommerce",
  "table": "orders",
  "select": [
    {"column": "category"},
    {"agg": "count", "column": "order_id", "as": "total_orders"},
    {"agg": "sum", "column": "returned", "as": "returned_orders"}
  ],
  "group_by": ["category"],
  "order_by": [{"expr": "returned_orders", "dir": "desc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  oi.category,
  COUNT(DISTINCT o.order_id) AS total_orders,
  SUM(CASE WHEN o.returned THEN 1 ELSE 0 END) AS returned_orders,
  ROUND(100.0 * SUM(CASE WHEN o.returned THEN 1 ELSE 0 END) / COUNT(DISTINCT o.order_id), 2) AS return_rate_pct
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
GROUP BY oi.category
ORDER BY return_rate_pct DESC
LIMIT 20;
```

**Success Criteria**: Returns category-level return statistics, Clothing should have highest return rate

---

### GQ3: Average Discount by Category (Simple Aggregation)

**Business Question**: "What's the average discount offered by product category?"

**Expected Query Plan**:
```json
{
  "dataset_id": "ecommerce",
  "table": "order_items",
  "select": [
    {"column": "category"},
    {"agg": "avg", "column": "discount", "as": "avg_discount"},
    {"agg": "count", "column": "item_id", "as": "item_count"}
  ],
  "filters": [
    {"column": "discount", "op": ">", "value": 0}
  ],
  "group_by": ["category"],
  "order_by": [{"expr": "avg_discount", "dir": "desc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  category,
  ROUND(AVG(discount), 2) AS avg_discount,
  COUNT(*) AS item_count
FROM order_items
WHERE discount > 0
GROUP BY category
ORDER BY avg_discount DESC
LIMIT 20;
```

**Success Criteria**: Returns average discount per category (only items with discounts)

---

### GQ4: Low Stock Products (Filter + Simple Select)

**Business Question**: "Which products in Electronics category have stock below 20?"

**Expected Query Plan**:
```json
{
  "dataset_id": "ecommerce",
  "table": "inventory",
  "select": [
    {"column": "product_id"},
    {"column": "name"},
    {"column": "stock"}
  ],
  "filters": [
    {"column": "category", "op": "=", "value": "Electronics"},
    {"column": "stock", "op": "<", "value": 20}
  ],
  "order_by": [{"expr": "stock", "dir": "asc"}],
  "limit": 50
}
```

**Expected SQL**:
```sql
SELECT
  product_id,
  name,
  stock
FROM inventory
WHERE category = 'Electronics'
  AND stock < 20
ORDER BY stock ASC
LIMIT 50;
```

**Success Criteria**: Returns products with low stock, sorted by stock level

---

### GQ5: Customer Lifetime Value (Complex Aggregation)

**Business Question**: "Show me the top 20 customers by total spend"

**Expected Query Plan**:
```json
{
  "dataset_id": "ecommerce",
  "table": "orders",
  "select": [
    {"column": "customer_id"},
    {"agg": "sum", "column": "total", "as": "lifetime_value"},
    {"agg": "count", "column": "order_id", "as": "order_count"}
  ],
  "filters": [
    {"column": "status", "op": "=", "value": "completed"}
  ],
  "group_by": ["customer_id"],
  "order_by": [{"expr": "lifetime_value", "dir": "desc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  customer_id,
  SUM(total) AS lifetime_value,
  COUNT(order_id) AS order_count,
  ROUND(AVG(total), 2) AS avg_order_value
FROM orders
WHERE status = 'completed'
GROUP BY customer_id
ORDER BY lifetime_value DESC
LIMIT 20;
```

**Success Criteria**: Returns top 20 customers with spend metrics

---

### GQ6: Recent High-Value Returns (Time Filter + Value Filter)

**Business Question**: "Show returned orders over $100 in the last 30 days"

**Expected Query Plan**:
```json
{
  "dataset_id": "ecommerce",
  "table": "orders",
  "select": [
    {"column": "order_id"},
    {"column": "customer_id"},
    {"column": "order_date"},
    {"column": "total"}
  ],
  "filters": [
    {"column": "returned", "op": "=", "value": true},
    {"column": "total", "op": ">", "value": 100},
    {"column": "order_date", "op": ">=", "value": "2024-12-01"}
  ],
  "order_by": [{"expr": "total", "dir": "desc"}],
  "limit": 50
}
```

**Expected SQL**:
```sql
SELECT
  order_id,
  customer_id,
  order_date,
  total
FROM orders
WHERE returned = true
  AND total > 100
  AND order_date >= '2024-12-01'
ORDER BY total DESC
LIMIT 50;
```

**Success Criteria**: Returns high-value returned orders

---

## Suggested Prompts for UI

These are natural language prompts that should map to the golden queries:

1. "What are the top 10 products by revenue?"
2. "Show me the return rate by category"
3. "What's the average discount by product category?"
4. "Which Electronics products have low stock (under 20)?"
5. "Who are our top 20 customers by total spend?"
6. "Show me returned orders over $100 in the last month"

## Data Generation Requirements

**Script**: `scripts/generate_ecommerce_dataset.py`

**Generation Rules**:
- Deterministic (seeded random for reproducibility)
- ~5,000 orders over 180 days
- 500 unique products across 5 categories
- 12% overall return rate with category variations
- 40% of items have discounts (5-30% range)
- Realistic price distributions by category
- Weekend ordering spike
- Some stock-outs and low-stock scenarios

**Validation**:
- All foreign keys valid (order_id, product_id)
- Dates within range
- No negative values
- Status enum valid
- Category enum valid

## Test Assertions

For integration testing, each golden query should:
1. ✅ Execute without error
2. ✅ Return non-empty result set
3. ✅ Complete within 3 seconds
4. ✅ Return expected column names
5. ✅ Respect LIMIT clause
6. ✅ Return results in expected sort order

## Version Hash

**Initial Version**: SHA256 of concatenated file contents
**Update Trigger**: Any change to CSV data requires new hash
