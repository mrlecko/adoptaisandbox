#!/usr/bin/env python3
"""
Generate IoT Sensor Monitoring dataset.

Follows UC3-IoT-Sensors-Dataset.md specification.
Deterministic generation using seeded random.
"""

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

# Deterministic seed for reproducibility
RANDOM_SEED = 44
random.seed(RANDOM_SEED)

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "datasets" / "sensors"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Configuration
NUM_SENSORS = 150
NUM_READINGS = 50000
DATE_RANGE_DAYS = 30

LOCATIONS = [
    "Warehouse-A", "Warehouse-B", "Warehouse-C",
    "Factory-Floor-1", "Factory-Floor-2", "Factory-Floor-3",
    "Outdoor-North", "Outdoor-South", "Outdoor-East", "Outdoor-West"
]

LOCATION_ZONES = {
    "Warehouse-A": "North", "Warehouse-B": "South", "Warehouse-C": "East",
    "Factory-Floor-1": "West", "Factory-Floor-2": "North", "Factory-Floor-3": "South",
    "Outdoor-North": "North", "Outdoor-South": "South", "Outdoor-East": "East", "Outdoor-West": "West"
}

LOCATION_TYPES = {
    "Warehouse-A": "indoor", "Warehouse-B": "indoor", "Warehouse-C": "indoor",
    "Factory-Floor-1": "industrial", "Factory-Floor-2": "industrial", "Factory-Floor-3": "industrial",
    "Outdoor-North": "outdoor", "Outdoor-South": "outdoor", "Outdoor-East": "outdoor", "Outdoor-West": "outdoor"
}

ANOMALY_TYPES = ["high_temp", "low_temp", "high_humidity", "sensor_fault", "vibration_alarm"]
ANOMALY_WEIGHTS = [40, 20, 15, 15, 10]


def get_baseline_temp(location_type: str, hour: int) -> float:
    """Get baseline temperature with diurnal cycle."""
    if location_type == "outdoor":
        # Outdoor: strong diurnal cycle (15-30°C)
        daily_variation = 7.5 * math.sin((hour - 6) * math.pi / 12)
        return 22.5 + daily_variation
    elif location_type == "industrial":
        # Factory: slight variation due to operations (22-26°C)
        return 24 + random.uniform(-2, 2)
    else:  # indoor (warehouse)
        # Warehouse: stable (20-24°C)
        return 22 + random.uniform(-2, 2)


def get_baseline_humidity(location_type: str, temp: float) -> float:
    """Get baseline humidity (inversely correlated with temp)."""
    if location_type == "outdoor":
        # Outdoor: 20-95%
        base = 60 - (temp - 22) * 2  # Inverse correlation
        return max(20, min(95, base + random.uniform(-15, 15)))
    elif location_type == "industrial":
        # Factory: 35-65%
        return 50 + random.uniform(-15, 15)
    else:  # indoor
        # Warehouse: 40-60%
        return 50 + random.uniform(-10, 10)


def generate_sensors() -> List[str]:
    """Generate sensor IDs."""
    return [f"SEN-{i:03d}" for i in range(1, NUM_SENSORS + 1)]


def generate_readings(sensors: List[str]) -> List[Dict]:
    """Generate sensor readings."""
    readings = []

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DATE_RANGE_DAYS)

    # Initialize sensor states (for random walk)
    sensor_states = {}
    for sensor in sensors:
        location = random.choice(LOCATIONS)
        sensor_states[sensor] = {
            "location": location,
            "location_type": LOCATION_TYPES[location],
            "zone": LOCATION_ZONES[location],
            "battery_powered": random.random() < 0.40,
            "battery_pct": random.randint(50, 100) if random.random() < 0.40 else None,
            "has_vibration": LOCATION_TYPES[location] == "industrial",
            "status": "online",
        }

    readings_per_sensor = NUM_READINGS // NUM_SENSORS

    for sensor in sensors:
        state = sensor_states[sensor]

        # Determine reading interval (1-15 minutes)
        if state["location_type"] == "industrial":
            interval_minutes = 1  # High frequency for industrial
        elif state["location_type"] == "outdoor":
            interval_minutes = 5
        else:
            interval_minutes = 15  # Lower frequency for warehouses

        current_time = start_date

        for _ in range(readings_per_sensor):
            # Advance time
            current_time += timedelta(minutes=interval_minutes)
            if current_time > end_date:
                break

            # Sensor status (90% online, 5% offline, 5% maintenance)
            status_roll = random.random()
            if status_roll < 0.90:
                status = "online"
            elif status_roll < 0.95:
                status = "offline"
            else:
                status = "maintenance"

            state["status"] = status

            if status != "online":
                # Offline/maintenance sensors don't produce valid readings
                readings.append({
                    "sensor_id": sensor,
                    "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "location": state["location"],
                    "zone": state["zone"],
                    "temperature_c": "",
                    "humidity_pct": "",
                    "pressure_hpa": "",
                    "vibration_mm_s": "",
                    "anomaly_flag": False,
                    "anomaly_type": "",
                    "battery_pct": state["battery_pct"] if state["battery_pct"] else "",
                    "status": status,
                })
                continue

            # Generate normal readings
            hour = current_time.hour
            temp = get_baseline_temp(state["location_type"], hour)
            humidity = get_baseline_humidity(state["location_type"], temp)
            pressure = 1013.25 + random.uniform(-20, 20)

            # Add random walk
            temp += random.uniform(-0.5, 0.5)
            humidity += random.uniform(-2, 2)

            # Vibration (only for industrial sensors)
            vibration = None
            if state["has_vibration"]:
                vibration = random.uniform(0, 10) + random.expovariate(1/2)  # Most values 0-10, some spikes

            # Anomaly detection (3% rate)
            anomaly_flag = False
            anomaly_type = None

            if random.random() < 0.03:
                anomaly_flag = True
                anomaly_type = random.choices(ANOMALY_TYPES, weights=ANOMALY_WEIGHTS)[0]

                # Adjust readings based on anomaly type
                if anomaly_type == "high_temp":
                    temp += random.uniform(10, 20)
                elif anomaly_type == "low_temp":
                    temp -= random.uniform(5, 15)
                elif anomaly_type == "high_humidity":
                    humidity += random.uniform(20, 30)
                elif anomaly_type == "sensor_fault":
                    # Erratic readings
                    temp = random.uniform(-10, 50)
                    humidity = random.uniform(0, 100)
                elif anomaly_type == "vibration_alarm" and vibration is not None:
                    vibration = random.uniform(15, 40)

            # Battery discharge (1% per day for battery-powered)
            if state["battery_pct"] is not None:
                days_elapsed = (current_time - start_date).days
                state["battery_pct"] = max(5, 100 - days_elapsed)

            # Night shift has higher anomaly rate for factory floors
            if state["location_type"] == "industrial" and (hour < 6 or hour >= 22):
                if random.random() < 0.01:
                    anomaly_flag = True
                    anomaly_type = random.choice(["high_temp", "vibration_alarm"])

            # Keep generated values in physically valid bounds.
            temp = max(-20.0, min(50.0, temp))
            humidity = max(0.0, min(100.0, humidity))

            readings.append({
                "sensor_id": sensor,
                "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                "location": state["location"],
                "zone": state["zone"],
                "temperature_c": round(temp, 2),
                "humidity_pct": round(humidity, 2),
                "pressure_hpa": round(pressure, 2),
                "vibration_mm_s": round(vibration, 3) if vibration is not None else "",
                "anomaly_flag": anomaly_flag,
                "anomaly_type": anomaly_type if anomaly_type else "",
                "battery_pct": state["battery_pct"] if state["battery_pct"] is not None else "",
                "status": status,
            })

    return readings


def write_csv(filename: str, data: List[Dict], fieldnames: List[str]):
    """Write data to CSV file."""
    filepath = OUTPUT_DIR / filename
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"✓ Generated {filepath} ({len(data)} rows)")


def main():
    print("Generating IoT Sensors Dataset...")
    print(f"Random seed: {RANDOM_SEED}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    # Generate sensors
    sensors = generate_sensors()
    print(f"  Generated {len(sensors)} sensors")

    # Generate readings
    readings = generate_readings(sensors)

    fieldnames = [
        "sensor_id", "timestamp", "location", "zone",
        "temperature_c", "humidity_pct", "pressure_hpa", "vibration_mm_s",
        "anomaly_flag", "anomaly_type", "battery_pct", "status"
    ]
    write_csv("sensors.csv", readings, fieldnames)

    # Statistics
    print()
    print("Dataset Statistics:")
    print(f"  Total readings: {len(readings)}")
    print(f"  Unique sensors: {len(set(r['sensor_id'] for r in readings))}")

    # Status distribution
    status_counts = {}
    for reading in readings:
        status_counts[reading["status"]] = status_counts.get(reading["status"], 0) + 1
    print(f"  Status distribution: {status_counts}")

    # Anomaly rate
    anomalies = sum(1 for r in readings if r["anomaly_flag"])
    anomaly_rate = (anomalies / len(readings)) * 100
    print(f"  Anomaly rate: {anomaly_rate:.2f}% ({anomalies} readings)")

    # Anomaly types
    if anomalies > 0:
        anomaly_type_counts = {}
        for reading in readings:
            if reading["anomaly_flag"] and reading["anomaly_type"]:
                atype = reading["anomaly_type"]
                anomaly_type_counts[atype] = anomaly_type_counts.get(atype, 0) + 1
        print("  Anomaly types:")
        for atype, count in sorted(anomaly_type_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / anomalies) * 100
            print(f"    {atype}: {pct:.1f}%")

    # Location distribution
    location_counts = {}
    for reading in readings:
        location_counts[reading["location"]] = location_counts.get(reading["location"], 0) + 1
    print(f"  Readings per location:")
    for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"    {loc}: {count}")

    # Battery-powered sensors
    battery_readings = [r for r in readings if r["battery_pct"] != ""]
    if battery_readings:
        low_battery = sum(1 for r in battery_readings if r["battery_pct"] != "" and int(r["battery_pct"]) < 20)
        print(f"  Battery-powered readings: {len(battery_readings)}")
        print(f"  Low battery (<20%): {low_battery}")

    # Temperature range
    temps = [float(r["temperature_c"]) for r in readings if r["temperature_c"] != ""]
    if temps:
        print(f"  Temperature range: {min(temps):.1f}°C to {max(temps):.1f}°C")

    print()
    print("✅ IoT Sensors dataset generation complete!")


if __name__ == "__main__":
    main()
