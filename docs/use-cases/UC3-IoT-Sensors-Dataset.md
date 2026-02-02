# Use Case 3: IoT Sensor Monitoring Dataset

## Overview

**Dataset ID**: `sensors`
**Domain**: IoT / Industrial Monitoring / Smart Infrastructure
**Primary Use Cases**: Anomaly detection, location-based analysis, time-series monitoring, environmental tracking

## Business Context

This dataset simulates an IoT sensor network monitoring environmental conditions across multiple locations. Operations teams need to:
- Detect and investigate anomalies in sensor readings
- Monitor environmental conditions by location/zone
- Track sensor health and uptime
- Identify trends and outliers
- Ensure compliance with environmental thresholds
- Plan maintenance based on sensor behavior

## Dataset Schema

### File: `sensors.csv`

**Purpose**: Time-series sensor readings with environmental metrics and anomaly flags

| Column | Type | Description | Sample Values |
|--------|------|-------------|---------------|
| `sensor_id` | VARCHAR(20) | Unique sensor identifier | SEN-001, SEN-002, ... |
| `timestamp` | TIMESTAMP | Reading timestamp | 2024-01-15 14:23:00 |
| `location` | VARCHAR(50) | Physical location/zone | Warehouse-A, Factory-Floor-2 |
| `zone` | VARCHAR(20) | Logical grouping | North, South, East, West |
| `temperature_c` | DECIMAL(5,2) | Temperature in Celsius | 22.5, 18.3, -5.0 |
| `humidity_pct` | DECIMAL(5,2) | Relative humidity (0-100) | 45.2, 78.5 |
| `pressure_hpa` | DECIMAL(6,2) | Atmospheric pressure (hPa) | 1013.25, 1008.50 |
| `vibration_mm_s` | DECIMAL(6,3) | Vibration level (mm/s, NULL for non-industrial) | 2.5, 15.3, NULL |
| `anomaly_flag` | BOOLEAN | Whether reading flagged as anomalous | true, false |
| `anomaly_type` | VARCHAR(50) | Type of anomaly (NULL if none) | high_temp, sensor_fault, NULL |
| `battery_pct` | INTEGER | Battery level (0-100, NULL if powered) | 85, 20, NULL |
| `status` | VARCHAR(20) | Sensor operational status | online, offline, maintenance |

**Row Count**: ~50,000 readings
**Date Range**: Last 30 days
**Reading Frequency**: Varies by location (1-15 minute intervals)

## Data Characteristics

**Distributions**:
- **Locations**: 10 distinct locations (warehouses, factory floors, outdoor)
- **Zones**: North (25%), South (25%), East (25%), West (25%)
- **Sensor Count**: 150 unique sensors
- **Status**: online (90%), offline (5%), maintenance (5%)
- **Anomaly Rate**: 3% overall (varies by location and time)
- **Anomaly Types**: high_temp (40%), low_temp (20%), high_humidity (15%), sensor_fault (15%), other (10%)
- **Battery-Powered**: 40% of sensors (others are NULL for battery_pct)

**Temporal Patterns**:
- Daily temperature cycle (outdoor sensors)
- Higher anomaly rate during night shifts (factory floors)
- Weekend maintenance windows (increased offline status)
- Gradual battery decline (linear discharge)

**Normal Ranges** (location-dependent):
- **Temperature**: 18-28°C (indoor), -10 to 40°C (outdoor)
- **Humidity**: 30-70% (indoor), 20-95% (outdoor)
- **Pressure**: 980-1040 hPa
- **Vibration**: 0-10 mm/s (normal), >10 mm/s (potential issue)

## Golden Queries

### GQ1: Recent Anomalies by Location (Filter + Group + Count)

**Business Question**: "How many anomalies were detected by location in the last 24 hours?"

**Expected Query Plan**:
```json
{
  "dataset_id": "sensors",
  "table": "sensors",
  "select": [
    {"column": "location"},
    {"agg": "count", "column": "sensor_id", "as": "anomaly_count"}
  ],
  "filters": [
    {"column": "anomaly_flag", "op": "=", "value": true},
    {"column": "timestamp", "op": ">=", "value": "2024-12-31 00:00:00"}
  ],
  "group_by": ["location"],
  "order_by": [{"expr": "anomaly_count", "dir": "desc"}],
  "limit": 20
}
```

**Expected SQL**:
```sql
SELECT
  location,
  COUNT(*) AS anomaly_count,
  COUNT(DISTINCT sensor_id) AS affected_sensors
FROM sensors
WHERE anomaly_flag = true
  AND timestamp >= DATETIME('now', '-24 hours')
GROUP BY location
ORDER BY anomaly_count DESC
LIMIT 20;
```

**Success Criteria**: Returns locations with anomaly counts, sorted by most anomalies

---

### GQ2: Average Environmental Conditions by Zone (Multi-column Aggregation)

**Business Question**: "What are the average temperature and humidity levels by zone?"

**Expected Query Plan**:
```json
{
  "dataset_id": "sensors",
  "table": "sensors",
  "select": [
    {"column": "zone"},
    {"agg": "avg", "column": "temperature_c", "as": "avg_temp"},
    {"agg": "avg", "column": "humidity_pct", "as": "avg_humidity"}
  ],
  "filters": [
    {"column": "status", "op": "=", "value": "online"},
    {"column": "timestamp", "op": ">=", "value": "2024-12-31 00:00:00"}
  ],
  "group_by": ["zone"],
  "order_by": [{"expr": "avg_temp", "dir": "desc"}],
  "limit": 10
}
```

**Expected SQL**:
```sql
SELECT
  zone,
  ROUND(AVG(temperature_c), 2) AS avg_temp,
  ROUND(AVG(humidity_pct), 2) AS avg_humidity,
  ROUND(AVG(pressure_hpa), 2) AS avg_pressure,
  COUNT(*) AS reading_count
FROM sensors
WHERE status = 'online'
  AND timestamp >= DATETIME('now', '-24 hours')
GROUP BY zone
ORDER BY avg_temp DESC
LIMIT 10;
```

**Success Criteria**: Returns environmental averages per zone

---

### GQ3: High Temperature Anomalies (Specific Anomaly Type)

**Business Question**: "Show me all high temperature anomalies in the last week"

**Expected Query Plan**:
```json
{
  "dataset_id": "sensors",
  "table": "sensors",
  "select": [
    {"column": "sensor_id"},
    {"column": "timestamp"},
    {"column": "location"},
    {"column": "temperature_c"}
  ],
  "filters": [
    {"column": "anomaly_type", "op": "=", "value": "high_temp"},
    {"column": "timestamp", "op": ">=", "value": "2024-12-25 00:00:00"}
  ],
  "order_by": [{"expr": "temperature_c", "dir": "desc"}],
  "limit": 50
}
```

**Expected SQL**:
```sql
SELECT
  sensor_id,
  timestamp,
  location,
  temperature_c,
  humidity_pct
FROM sensors
WHERE anomaly_type = 'high_temp'
  AND timestamp >= DATETIME('now', '-7 days')
ORDER BY temperature_c DESC
LIMIT 50;
```

**Success Criteria**: Returns high temperature anomaly events, hottest first

---

### GQ4: Low Battery Sensors Requiring Attention (Filter + Sort)

**Business Question**: "Which sensors have battery below 20% and are still online?"

**Expected Query Plan**:
```json
{
  "dataset_id": "sensors",
  "table": "sensors",
  "select": [
    {"column": "sensor_id"},
    {"column": "location"},
    {"column": "battery_pct"}
  ],
  "filters": [
    {"column": "battery_pct", "op": "<", "value": 20},
    {"column": "battery_pct", "op": "!=", "value": null},
    {"column": "status", "op": "=", "value": "online"}
  ],
  "order_by": [{"expr": "battery_pct", "dir": "asc"}],
  "limit": 50
}
```

**Expected SQL**:
```sql
SELECT DISTINCT
  sensor_id,
  location,
  battery_pct,
  MAX(timestamp) AS last_reading
FROM sensors
WHERE battery_pct < 20
  AND battery_pct IS NOT NULL
  AND status = 'online'
GROUP BY sensor_id, location, battery_pct
ORDER BY battery_pct ASC
LIMIT 50;
```

**Success Criteria**: Returns sensors needing battery replacement, lowest first

---

### GQ5: Sensor Uptime Status (Aggregation by Status)

**Business Question**: "What's the distribution of sensor statuses across all locations?"

**Expected Query Plan**:
```json
{
  "dataset_id": "sensors",
  "table": "sensors",
  "select": [
    {"column": "status"},
    {"agg": "count", "column": "sensor_id", "as": "reading_count"}
  ],
  "group_by": ["status"],
  "order_by": [{"expr": "reading_count", "dir": "desc"}],
  "limit": 10
}
```

**Expected SQL**:
```sql
SELECT
  status,
  COUNT(*) AS reading_count,
  COUNT(DISTINCT sensor_id) AS unique_sensors,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM sensors), 2) AS pct_of_total
FROM sensors
WHERE timestamp >= DATETIME('now', '-24 hours')
GROUP BY status
ORDER BY reading_count DESC
LIMIT 10;
```

**Success Criteria**: Returns status distribution, online should be majority

---

### GQ6: Extreme Vibration Readings (Industrial Monitoring)

**Business Question**: "Show sensors with vibration levels above 15 mm/s in the last 6 hours"

**Expected Query Plan**:
```json
{
  "dataset_id": "sensors",
  "table": "sensors",
  "select": [
    {"column": "sensor_id"},
    {"column": "timestamp"},
    {"column": "location"},
    {"column": "vibration_mm_s"}
  ],
  "filters": [
    {"column": "vibration_mm_s", "op": ">", "value": 15},
    {"column": "timestamp", "op": ">=", "value": "2024-12-31 18:00:00"}
  ],
  "order_by": [{"expr": "vibration_mm_s", "dir": "desc"}],
  "limit": 30
}
```

**Expected SQL**:
```sql
SELECT
  sensor_id,
  timestamp,
  location,
  vibration_mm_s,
  anomaly_flag
FROM sensors
WHERE vibration_mm_s > 15.0
  AND timestamp >= DATETIME('now', '-6 hours')
ORDER BY vibration_mm_s DESC
LIMIT 30;
```

**Success Criteria**: Returns high vibration events (potential equipment issues)

---

## Suggested Prompts for UI

1. "How many anomalies were detected by location in the last 24 hours?"
2. "What are the average temperature and humidity levels by zone?"
3. "Show me all high temperature anomalies from the last week"
4. "Which sensors have battery below 20%?"
5. "What's the current sensor status distribution?"
6. "Find sensors with dangerous vibration levels in the last 6 hours"

## Data Generation Requirements

**Script**: `scripts/generate_sensors_dataset.py`

**Generation Rules**:
- Deterministic (seeded random)
- ~50,000 readings over 30 days
- 150 unique sensors across 10 locations
- Reading frequency varies: 1-15 minute intervals
- Temperature follows daily sinusoidal pattern (outdoor) + random walk
- Humidity inversely correlated with temperature
- 3% anomaly injection rate (various types)
- Battery discharge: 1% per day for battery-powered sensors
- Realistic pressure variations
- Industrial sensors (40%) have vibration data
- Sensor offline events (5% of readings)

**Validation**:
- All timestamps in valid range
- Temperature: -20 to 50°C
- Humidity: 0-100%
- Pressure: 900-1100 hPa
- Vibration: 0-50 mm/s (if not NULL)
- Battery: 0-100 or NULL
- Status enum valid
- anomaly_type NULL if anomaly_flag = false

## Test Assertions

Each golden query should:
1. ✅ Execute without error
2. ✅ Return non-empty result set
3. ✅ Complete within 3 seconds
4. ✅ Handle NULL values correctly (vibration, battery)
5. ✅ Return time-series data in correct order
6. ✅ Aggregate across timestamps correctly

## Version Hash

**Initial Version**: SHA256 of sensors.csv content
**Update Trigger**: Any change to CSV data requires new hash

## Special Considerations

**Time-Series Queries**: This dataset is ideal for testing:
- Time window filters (last 24h, last week, etc.)
- Temporal aggregations
- Anomaly detection patterns
- Missing data handling (NULL vibration/battery)

**Real-World Patterns**: Generated data should exhibit:
- Diurnal temperature cycles
- Correlated environmental variables
- Realistic sensor drift
- Maintenance windows (predictable offline periods)
- Battery decay curves
