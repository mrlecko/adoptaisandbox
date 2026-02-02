# Use Case Specifications

This directory contains detailed specifications for the three MVP datasets.

## Overview

Each use case document defines:
- **Dataset schema** (tables, columns, types, distributions)
- **Golden queries** (canonical analytics questions with expected SQL)
- **Suggested prompts** (natural language versions for UI)
- **Data generation requirements** (for reproducibility)
- **Test assertions** (for validation)

## Use Cases

### 1. E-commerce Analytics (`ecommerce`)
**File**: [UC1-Ecommerce-Dataset.md](UC1-Ecommerce-Dataset.md)

**Domain**: Retail/E-commerce
**Files**: `orders.csv`, `order_items.csv`, `inventory.csv`
**Row Count**: ~5,000 orders, ~12,000 items, ~500 products
**Key Queries**:
- Top products by revenue
- Return rate by category
- Average discount analysis
- Low stock alerts
- Customer lifetime value
- High-value returns

**Tests Query DSL Features**: Joins, aggregations, filters, sorting, multi-table queries

---

### 2. Support Ticket Analytics (`support`)
**File**: [UC2-Support-Tickets-Dataset.md](UC2-Support-Tickets-Dataset.md)

**Domain**: Customer Support
**File**: `tickets.csv`
**Row Count**: ~8,000 tickets
**Key Queries**:
- SLA compliance by priority
- CSAT scores by category
- Longest open critical tickets
- Average resolution time
- Recent SLA violations
- Low CSAT tickets for follow-up

**Tests Query DSL Features**: NULL handling, time windows, complex filters, aggregations, percentage calculations

---

### 3. IoT Sensor Monitoring (`sensors`)
**File**: [UC3-IoT-Sensors-Dataset.md](UC3-IoT-Sensors-Dataset.md)

**Domain**: IoT/Industrial Monitoring
**File**: `sensors.csv`
**Row Count**: ~50,000 readings
**Key Queries**:
- Anomaly detection by location
- Environmental conditions by zone
- High temperature anomalies
- Low battery sensors
- Sensor uptime status
- Extreme vibration readings

**Tests Query DSL Features**: Time-series queries, anomaly detection, multi-column aggregations, NULL handling, temporal filters

---

## Golden Query Coverage

The 18 golden queries across all three datasets comprehensively test:

**Query Capabilities**:
- ✅ Simple SELECT with filters
- ✅ Aggregations (COUNT, SUM, AVG, MIN, MAX)
- ✅ GROUP BY (single and multiple columns)
- ✅ ORDER BY (ASC/DESC)
- ✅ LIMIT enforcement
- ✅ JOINs (inner joins across tables)
- ✅ Time-based filters (last N days, date ranges)
- ✅ NULL handling (IS NULL, IS NOT NULL)
- ✅ IN operator (multiple values)
- ✅ Comparison operators (=, !=, <, <=, >, >=)
- ✅ Boolean filters
- ✅ CASE expressions (for calculations)

**Data Patterns**:
- ✅ Transactional data (e-commerce)
- ✅ Operational metrics (support tickets)
- ✅ Time-series sensor data (IoT)
- ✅ Categorical data
- ✅ Temporal patterns
- ✅ Hierarchical groupings

**Business Scenarios**:
- ✅ Performance metrics (SLA, resolution time)
- ✅ Customer satisfaction analysis
- ✅ Inventory management
- ✅ Anomaly detection
- ✅ Trend analysis
- ✅ Operational alerts

---

## Dataset Generation

Each dataset must be generated using the specifications in its use case document.

**Scripts** (to be created):
```
scripts/
├── generate_ecommerce_dataset.py
├── generate_support_dataset.py
├── generate_sensors_dataset.py
└── validate_datasets.py
```

**Requirements**:
- Deterministic generation (seeded random for reproducibility)
- Follow specified distributions and patterns
- Generate realistic but synthetic data
- Validate against schema constraints
- Calculate SHA256 version hashes

**Execution**:
```bash
# Generate all datasets
make generate-datasets

# Validate datasets
make validate-datasets

# Generate version hashes
make gen-dataset-hashes
```

---

## Dataset Registry

After generation, update `datasets/registry.json` with:

```json
{
  "version": "1.0",
  "datasets": [
    {
      "id": "ecommerce",
      "name": "E-commerce Orders",
      "description": "Retail transaction data with orders, items, and inventory",
      "version_hash": "sha256:...",
      "files": [...],
      "prompts": [...]
    },
    {
      "id": "support",
      "name": "Support Tickets",
      "description": "Customer support ticket lifecycle and satisfaction data",
      "version_hash": "sha256:...",
      "files": [...],
      "prompts": [...]
    },
    {
      "id": "sensors",
      "name": "IoT Sensor Network",
      "description": "Environmental monitoring sensor readings with anomaly detection",
      "version_hash": "sha256:...",
      "files": [...],
      "prompts": [...]
    }
  ]
}
```

---

## Testing Strategy

### Unit Tests
Each golden query should have a unit test that:
1. Validates the query plan JSON schema
2. Compiles the plan to SQL
3. Validates the SQL against security policies
4. Asserts expected column names in result

### Integration Tests
Each golden query should have an integration test that:
1. Executes end-to-end (plan → SQL → runner → result)
2. Asserts non-empty result set
3. Asserts row count > 0
4. Asserts execution time < 3 seconds
5. Validates result shape (columns, types)
6. Checks sort order if specified
7. Validates LIMIT respected

### Acceptance Tests
Run all 18 golden queries in sequence:
- All must succeed
- All must return results within 3 seconds
- Total execution time < 1 minute

**Command**:
```bash
make test-golden-queries
```

---

## PRD Alignment

These use cases satisfy Core PRD requirements:

- **FR-D1**: ✅ 3 built-in datasets defined
- **FR-D2**: ✅ Each has ID, description, files, schema, prompts
- **FR-D3**: ✅ Version hashing specified
- **FR-Q1**: ✅ Query DSL covers all specified operations
- **Section 12**: ✅ All dataset requirements met
  - 12.2: Ecommerce (orders, items, inventory, time windows)
  - 12.3: Support tickets (timestamps, SLA, CSAT)
  - 12.4: Sensors (time-series, anomalies, grouping)
- **Section 12.5**: ✅ 4-6 prompts per dataset (18 total)

---

## Next Steps

1. **Implement data generation scripts** (Phase 1.1 in TODO.md)
2. **Generate datasets** and validate
3. **Create registry.json** with metadata
4. **Write unit tests** for query plan validation
5. **Write integration tests** for golden queries
6. **Document in README** with example outputs

---

## Appendix: Query Complexity Distribution

**Simple** (5 queries): Basic SELECT with filters, no aggregation
- UC1-GQ4: Low stock products
- UC2-GQ3: Oldest open tickets
- UC3-GQ3: High temp anomalies
- UC3-GQ4: Low battery sensors
- UC3-GQ6: Extreme vibration

**Medium** (8 queries): Single-table aggregations
- UC1-GQ3: Average discount by category
- UC1-GQ5: Customer lifetime value
- UC1-GQ6: Recent high-value returns
- UC2-GQ2: CSAT by category
- UC2-GQ4: Resolution time by category
- UC2-GQ5: SLA violations
- UC3-GQ1: Anomalies by location
- UC3-GQ5: Sensor status distribution

**Complex** (5 queries): Multi-table joins, complex aggregations
- UC1-GQ1: Top products by revenue (join)
- UC1-GQ2: Return rate by category (join + calculation)
- UC2-GQ1: SLA compliance by priority (complex aggregation)
- UC2-GQ6: Low CSAT with filters
- UC3-GQ2: Multi-column environmental aggregation

This distribution ensures the query DSL is tested across difficulty levels.
