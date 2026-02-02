# Use Case 2: Support Ticket Analytics Dataset

## Overview

**Dataset ID**: `support`
**Domain**: Customer Support / Service Operations
**Primary Use Cases**: SLA compliance tracking, CSAT analysis, priority handling, resolution time optimization

## Business Context

This dataset simulates a customer support ticketing system. Support managers need to:
- Monitor SLA compliance rates by priority level
- Analyze resolution times and identify bottlenecks
- Track customer satisfaction (CSAT) scores
- Identify high-priority tickets requiring escalation
- Understand ticket volume patterns by category and time
- Measure team/category performance

## Dataset Schema

### File: `tickets.csv`

**Purpose**: Individual support ticket records with lifecycle and satisfaction metrics

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `ticket_id` | INTEGER | Unique ticket identifier | 5001, 5002, ... |
| `created_at` | TIMESTAMP | Ticket creation timestamp | 2024-01-15 09:23:15 |
| `resolved_at` | TIMESTAMP | Resolution timestamp (NULL if open) | 2024-01-15 14:30:00, NULL |
| `category` | VARCHAR(50) | Ticket category | Technical, Billing, Account, Product |
| `priority` | VARCHAR(20) | Priority level | Low, Medium, High, Critical |
| `csat_score` | INTEGER | Customer satisfaction (1-5, NULL if no response) | 1, 2, 3, 4, 5, NULL |
| `sla_met` | BOOLEAN | Whether SLA was met | true, false |
| `resolution_time_hours` | DECIMAL(8,2) | Time to resolution in hours (NULL if open) | 2.5, 24.0, NULL |
| `status` | VARCHAR(20) | Current ticket status | Open, Resolved, Closed |
| `agent_id` | INTEGER | Assigned support agent | 101, 102, 103 |
| `channel` | VARCHAR(20) | Support channel | Email, Chat, Phone |

**Row Count**: ~8,000 tickets
**Date Range**: Last 90 days

## Data Characteristics

**Distributions**:
- **Categories**: Technical (40%), Billing (25%), Account (20%), Product (15%)
- **Priorities**: Low (50%), Medium (30%), High (15%), Critical (5%)
- **Status**: Resolved (75%), Open (20%), Closed (5%)
- **CSAT Response Rate**: 60% (40% NULL)
- **CSAT Distribution** (of responses): 1★ (10%), 2★ (15%), 3★ (20%), 4★ (35%), 5★ (20%)
- **SLA Compliance**: 85% overall (varies by priority: Critical 70%, High 80%, Medium 90%, Low 95%)
- **Channels**: Email (50%), Chat (35%), Phone (15%)

**Temporal Patterns**:
- Business hours peak (9 AM - 5 PM, Mon-Fri)
- Lower volume on weekends
- Monday morning spike
- End-of-month billing ticket surge

**Resolution Time Targets (SLA)**:
- **Critical**: 4 hours
- **High**: 8 hours
- **Medium**: 24 hours
- **Low**: 72 hours

## Golden Queries

### GQ1: SLA Compliance by Priority (Aggregation + Grouping)

**Business Question**: "What's our SLA compliance rate by priority level?"

**Expected Query Plan**:
```json
{
  "dataset_id": "support",
  "table": "tickets",
  "select": [
    {"column": "priority"},
    {"agg": "count", "column": "ticket_id", "as": "total_tickets"},
    {"agg": "sum", "column": "sla_met", "as": "sla_met_count"}
  ],
  "filters": [
    {"column": "status", "op": "in", "value": ["Resolved", "Closed"]}
  ],
  "group_by": ["priority"],
  "order_by": [{"expr": "priority", "dir": "asc"}],
  "limit": 10
}
```

**Expected SQL**:
```sql
SELECT
  priority,
  COUNT(*) AS total_tickets,
  SUM(CASE WHEN sla_met THEN 1 ELSE 0 END) AS sla_met_count,
  ROUND(100.0 * SUM(CASE WHEN sla_met THEN 1 ELSE 0 END) / COUNT(*), 2) AS sla_compliance_pct
FROM tickets
WHERE status IN ('Resolved', 'Closed')
GROUP BY priority
ORDER BY CASE priority
  WHEN 'Critical' THEN 1
  WHEN 'High' THEN 2
  WHEN 'Medium' THEN 3
  WHEN 'Low' THEN 4
END
LIMIT 10;
```

**Success Criteria**: Returns SLA metrics per priority level, Critical should have lowest compliance %

---

### GQ2: Average CSAT by Category (Aggregation with NULL handling)

**Business Question**: "What's the average customer satisfaction score by ticket category?"

**Expected Query Plan**:
```json
{
  "dataset_id": "support",
  "table": "tickets",
  "select": [
    {"column": "category"},
    {"agg": "avg", "column": "csat_score", "as": "avg_csat"},
    {"agg": "count", "column": "csat_score", "as": "response_count"}
  ],
  "filters": [
    {"column": "csat_score", "op": "!=", "value": null}
  ],
  "group_by": ["category"],
  "order_by": [{"expr": "avg_csat", "dir": "desc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  category,
  ROUND(AVG(csat_score), 2) AS avg_csat,
  COUNT(*) AS response_count,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM tickets WHERE category = t.category), 2) AS response_rate_pct
FROM tickets t
WHERE csat_score IS NOT NULL
GROUP BY category
ORDER BY avg_csat DESC
LIMIT 20;
```

**Success Criteria**: Returns average CSAT scores, all values between 1-5

---

### GQ3: Longest Open Critical Tickets (Filter + Sort + Time)

**Business Question**: "Show me the oldest unresolved critical priority tickets"

**Expected Query Plan**:
```json
{
  "dataset_id": "support",
  "table": "tickets",
  "select": [
    {"column": "ticket_id"},
    {"column": "created_at"},
    {"column": "category"},
    {"column": "priority"}
  ],
  "filters": [
    {"column": "status", "op": "=", "value": "Open"},
    {"column": "priority", "op": "in", "value": ["Critical", "High"]}
  ],
  "order_by": [{"expr": "created_at", "dir": "asc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  ticket_id,
  created_at,
  category,
  priority,
  ROUND((JULIANDAY('now') - JULIANDAY(created_at)) * 24, 1) AS hours_open
FROM tickets
WHERE status = 'Open'
  AND priority IN ('Critical', 'High')
ORDER BY created_at ASC
LIMIT 20;
```

**Success Criteria**: Returns oldest open high-priority tickets

---

### GQ4: Average Resolution Time by Category (Aggregation)

**Business Question**: "What's the average resolution time by ticket category?"

**Expected Query Plan**:
```json
{
  "dataset_id": "support",
  "table": "tickets",
  "select": [
    {"column": "category"},
    {"agg": "avg", "column": "resolution_time_hours", "as": "avg_resolution_hours"},
    {"agg": "count", "column": "ticket_id", "as": "resolved_count"}
  ],
  "filters": [
    {"column": "resolution_time_hours", "op": "!=", "value": null}
  ],
  "group_by": ["category"],
  "order_by": [{"expr": "avg_resolution_hours", "dir": "desc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  category,
  ROUND(AVG(resolution_time_hours), 2) AS avg_resolution_hours,
  COUNT(*) AS resolved_count,
  ROUND(MIN(resolution_time_hours), 2) AS min_hours,
  ROUND(MAX(resolution_time_hours), 2) AS max_hours
FROM tickets
WHERE resolution_time_hours IS NOT NULL
GROUP BY category
ORDER BY avg_resolution_hours DESC
LIMIT 20;
```

**Success Criteria**: Returns resolution time statistics per category

---

### GQ5: SLA Violations in Last Week (Time Filter + Status)

**Business Question**: "Show me tickets that missed SLA in the last 7 days"

**Expected Query Plan**:
```json
{
  "dataset_id": "support",
  "table": "tickets",
  "select": [
    {"column": "ticket_id"},
    {"column": "created_at"},
    {"column": "category"},
    {"column": "priority"},
    {"column": "resolution_time_hours"}
  ],
  "filters": [
    {"column": "sla_met", "op": "=", "value": false},
    {"column": "created_at", "op": ">=", "value": "2024-12-25"}
  ],
  "order_by": [{"expr": "resolution_time_hours", "dir": "desc"}],
  "limit": 50
}
```

**Expected SQL**:
```sql
SELECT
  ticket_id,
  created_at,
  resolved_at,
  category,
  priority,
  resolution_time_hours
FROM tickets
WHERE sla_met = false
  AND created_at >= DATE('now', '-7 days')
ORDER BY resolution_time_hours DESC
LIMIT 50;
```

**Success Criteria**: Returns recent SLA violations, sorted by worst first

---

### GQ6: Low CSAT Tickets Requiring Follow-up (Multi-Filter)

**Business Question**: "Show me resolved tickets with CSAT score of 1 or 2 in the last month"

**Expected Query Plan**:
```json
{
  "dataset_id": "support",
  "table": "tickets",
  "select": [
    {"column": "ticket_id"},
    {"column": "category"},
    {"column": "csat_score"},
    {"column": "resolved_at"}
  ],
  "filters": [
    {"column": "csat_score", "op": "<=", "value": 2},
    {"column": "status", "op": "=", "value": "Resolved"},
    {"column": "resolved_at", "op": ">=", "value": "2024-12-01"}
  ],
  "order_by": [{"expr": "csat_score", "dir": "asc"}],
  "limit": 100
}
```

**Expected SQL**:
```sql
SELECT
  ticket_id,
  category,
  priority,
  csat_score,
  resolved_at
FROM tickets
WHERE csat_score <= 2
  AND status = 'Resolved'
  AND resolved_at >= DATE('now', '-30 days')
ORDER BY csat_score ASC, resolved_at DESC
LIMIT 100;
```

**Success Criteria**: Returns dissatisfied customer tickets for follow-up

---

## Suggested Prompts for UI

1. "What's our SLA compliance rate by priority level?"
2. "Show me average customer satisfaction score by category"
3. "Which critical tickets have been open the longest?"
4. "What's the average resolution time by category?"
5. "Show me tickets that missed SLA in the last week"
6. "Find resolved tickets with low CSAT scores (1-2 stars) from the last month"

## Data Generation Requirements

**Script**: `scripts/generate_support_dataset.py`

**Generation Rules**:
- Deterministic (seeded random)
- ~8,000 tickets over 90 days
- Business hours weighted distribution
- SLA targets vary by priority
- CSAT response rate: 60%
- Resolution times follow realistic distributions (exponential with mean based on priority)
- 20% of tickets currently open
- Critical tickets resolved faster but miss SLA more often (complexity)
- Weekend tickets have longer resolution times

**Validation**:
- All enum values valid (status, priority, category, channel)
- resolved_at >= created_at (if not NULL)
- resolution_time_hours matches timestamp diff (if both not NULL)
- CSAT scores 1-5 or NULL
- sla_met consistent with resolution_time vs target

## Test Assertions

Each golden query should:
1. ✅ Execute without error
2. ✅ Return non-empty result set
3. ✅ Complete within 3 seconds
4. ✅ Handle NULL values correctly
5. ✅ Return expected aggregations
6. ✅ Respect filters and sort order

## Version Hash

**Initial Version**: SHA256 of tickets.csv content
**Update Trigger**: Any change to CSV data requires new hash
