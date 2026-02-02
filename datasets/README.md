# Datasets

This directory contains the curated CSV datasets for CSV Analyst Chat.

## Quick Reference

| Dataset | Files | Rows | Size | Prompts |
|---------|-------|------|------|---------|
| **ecommerce** | 3 | 13,526 | 499 KB | 6 |
| **support** | 1 | 6,417 | 536 KB | 6 |
| **sensors** | 1 | 49,950 | 4.2 MB | 6 |
| **TOTAL** | **5** | **69,893** | **~5.2 MB** | **18** |

## Dataset Catalog

### 1. E-commerce Orders (`ecommerce`)

**Domain**: Retail/E-commerce
**Use Cases**: Sales analysis, return rates, discount effectiveness, inventory management

**Files**:
- `orders.csv` - 4,018 orders over 180 days
- `order_items.csv` - 9,008 line items
- `inventory.csv` - 500 products across 5 categories

**Sample Prompts**:
- "What are the top 10 products by revenue?"
- "Show me the return rate by category"
- "Which Electronics products have low stock (under 20)?"

**Version**: `sha256:ee605a8c40c2dbd63ddff5589299e654766a8670079e99104283a4e564dafa59`

---

### 2. Support Tickets (`support`)

**Domain**: Customer Support
**Use Cases**: SLA compliance, CSAT analysis, resolution time optimization

**Files**:
- `tickets.csv` - 6,417 tickets over 90 days

**Sample Prompts**:
- "What's our SLA compliance rate by priority level?"
- "Show me average customer satisfaction score by category"
- "Which critical tickets have been open the longest?"

**Version**: `sha256:76d7954c42615caba26fc03f92c62ec51bb8acc6bf45ab8dda1d17d2f9dc6c2a`

---

### 3. IoT Sensor Network (`sensors`)

**Domain**: IoT/Industrial Monitoring
**Use Cases**: Anomaly detection, environmental monitoring, predictive maintenance

**Files**:
- `sensors.csv` - 49,950 readings from 150 sensors over 30 days

**Sample Prompts**:
- "How many anomalies were detected by location in the last 24 hours?"
- "What are the average temperature and humidity levels by zone?"
- "Find sensors with dangerous vibration levels in the last 6 hours"

**Version**: `sha256:d18bc06193f8f1099cc6f0e4e77d5a13cb5e3f8c8bfe45e84ebae54f85f8c85d`

---

## Registry File

**Location**: `registry.json`

The registry contains complete metadata for all datasets:
- Dataset IDs, names, descriptions
- File schemas with column types and descriptions
- Suggested prompts for each dataset
- Version hashes for reproducibility
- Foreign key relationships
- Tags for discovery

**Access the registry**:
```python
import json
with open('datasets/registry.json') as f:
    registry = json.load(f)

# List all datasets
for dataset in registry['datasets']:
    print(f"{dataset['id']}: {dataset['name']}")
```

---

## Data Generation

All datasets are **deterministically generated** using seeded random:

**Scripts** (in `scripts/`):
- `generate_ecommerce_dataset.py` (seed: 42)
- `generate_support_dataset.py` (seed: 43)
- `generate_sensors_dataset.py` (seed: 44)
- `generate_registry.py` (creates registry.json with hashes)
- `validate_datasets.py` (quality checks)

**Regenerate datasets**:
```bash
# Generate all datasets
python3 scripts/generate_ecommerce_dataset.py
python3 scripts/generate_support_dataset.py
python3 scripts/generate_sensors_dataset.py

# Create registry with version hashes
python3 scripts/generate_registry.py

# Validate
python3 scripts/validate_datasets.py
```

Same seeds = identical data every time!

---

## Schema Overview

### E-commerce

**orders.csv**:
- `order_id`, `customer_id`, `order_date`, `total`, `status`, `returned`

**order_items.csv**:
- `item_id`, `order_id`, `product_id`, `category`, `quantity`, `price`, `discount`

**inventory.csv**:
- `product_id`, `name`, `category`, `stock`

### Support

**tickets.csv**:
- `ticket_id`, `created_at`, `resolved_at`, `category`, `priority`
- `csat_score`, `sla_met`, `resolution_time_hours`, `status`, `agent_id`, `channel`

### Sensors

**sensors.csv**:
- `sensor_id`, `timestamp`, `location`, `zone`
- `temperature_c`, `humidity_pct`, `pressure_hpa`, `vibration_mm_s`
- `anomaly_flag`, `anomaly_type`, `battery_pct`, `status`

---

## Usage in Agent

The agent server will:
1. Load `registry.json` at startup
2. Provide dataset metadata via `GET /datasets` API
3. Provide schema details via `GET /datasets/{id}/schema`
4. Show suggested prompts in UI
5. Verify dataset versions using SHA256 hashes

**Loading datasets** (DuckDB in runner):
```sql
-- Load CSV into DuckDB
SELECT * FROM read_csv_auto('datasets/ecommerce/orders.csv');

-- Multi-table queries
SELECT oi.category, COUNT(*)
FROM read_csv_auto('datasets/ecommerce/order_items.csv') oi
JOIN read_csv_auto('datasets/ecommerce/orders.csv') o
  ON oi.order_id = o.order_id
GROUP BY oi.category;
```

---

## Data Quality

**Validation Status**:
- ✅ E-commerce: All checks pass
- ⚠️ Support: 53 timestamp anomalies (minor, doesn't affect queries)
- ⚠️ Sensors: Some humidity >100% (realistic for anomalies)

**See**: `GENERATION_REPORT.md` for detailed statistics

---

## Version History

- **v1.0** (2026-02-02): Initial dataset generation
  - E-commerce: 13,526 rows
  - Support: 6,417 rows
  - Sensors: 49,950 rows
  - 18 golden queries defined

---

## Next Steps

- [ ] Implement dataset loader utility
- [ ] Test golden queries manually with DuckDB
- [ ] Create integration tests for each dataset
- [ ] Add dataset to runner Docker image
- [ ] Document any dataset updates in CHANGELOG

---

**For detailed specifications**, see `docs/use-cases/`:
- UC1-Ecommerce-Dataset.md
- UC2-Support-Tickets-Dataset.md
- UC3-IoT-Sensors-Dataset.md
