#!/usr/bin/env python3
"""
Generate datasets/registry.json with metadata, schemas, and version hashes.
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List


def sha256_file(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def sha256_dataset(files: List[Path]) -> str:
    """Calculate combined SHA256 hash for multiple files."""
    sha256 = hashlib.sha256()
    for filepath in sorted(files):
        with open(filepath, 'rb') as f:
            sha256.update(f.read())
    return sha256.hexdigest()


def generate_registry() -> Dict:
    """Generate the complete registry."""
    base_path = Path(__file__).parent.parent / "datasets"

    registry = {
        "version": "1.0",
        "generated_at": "2026-02-02T15:17:00Z",
        "description": "CSV Analyst Chat - Curated datasets for natural language analytics",
        "datasets": []
    }

    # Dataset 1: E-commerce
    ecommerce_path = base_path / "ecommerce"
    ecommerce_files = [
        ecommerce_path / "orders.csv",
        ecommerce_path / "order_items.csv",
        ecommerce_path / "inventory.csv"
    ]

    registry["datasets"].append({
        "id": "ecommerce",
        "name": "E-commerce Orders",
        "description": "Retail transaction data with orders, order items, and product inventory. Supports analysis of sales performance, return rates, discount effectiveness, and inventory management.",
        "domain": "Retail/E-commerce",
        "version_hash": f"sha256:{sha256_dataset(ecommerce_files)}",
        "row_count": 13526,
        "size_bytes": 510976,
        "files": [
            {
                "name": "orders.csv",
                "path": "ecommerce/orders.csv",
                "description": "Core order-level transactions",
                "row_count": 4018,
                "schema": {
                    "order_id": {"type": "INTEGER", "description": "Unique order identifier"},
                    "customer_id": {"type": "INTEGER", "description": "Customer identifier"},
                    "order_date": {"type": "DATE", "description": "Order placement date"},
                    "total": {"type": "DECIMAL", "description": "Total order value ($)"},
                    "status": {"type": "VARCHAR", "description": "Order status", "values": ["completed", "returned", "cancelled"]},
                    "returned": {"type": "BOOLEAN", "description": "Whether order was returned"}
                }
            },
            {
                "name": "order_items.csv",
                "path": "ecommerce/order_items.csv",
                "description": "Line-item details for orders",
                "row_count": 9008,
                "schema": {
                    "item_id": {"type": "INTEGER", "description": "Unique line item identifier"},
                    "order_id": {"type": "INTEGER", "description": "FK to orders.order_id"},
                    "product_id": {"type": "INTEGER", "description": "Product identifier"},
                    "category": {"type": "VARCHAR", "description": "Product category", "values": ["Electronics", "Clothing", "Home", "Books", "Toys"]},
                    "quantity": {"type": "INTEGER", "description": "Items ordered"},
                    "price": {"type": "DECIMAL", "description": "Unit price ($)"},
                    "discount": {"type": "INTEGER", "description": "Discount percentage (0-100)"}
                }
            },
            {
                "name": "inventory.csv",
                "path": "ecommerce/inventory.csv",
                "description": "Current product inventory levels",
                "row_count": 500,
                "schema": {
                    "product_id": {"type": "INTEGER", "description": "Unique product identifier"},
                    "name": {"type": "VARCHAR", "description": "Product name"},
                    "category": {"type": "VARCHAR", "description": "Product category"},
                    "stock": {"type": "INTEGER", "description": "Current stock level"}
                }
            }
        ],
        "relationships": [
            {"from": "order_items.order_id", "to": "orders.order_id", "type": "many-to-one"},
            {"from": "order_items.product_id", "to": "inventory.product_id", "type": "many-to-one"}
        ],
        "prompts": [
            "What are the top 10 products by revenue?",
            "Show me the return rate by category",
            "What's the average discount by product category?",
            "Which Electronics products have low stock (under 20)?",
            "Who are our top 20 customers by total spend?",
            "Show me returned orders over $100 in the last month"
        ],
        "tags": ["retail", "ecommerce", "sales", "inventory", "returns"]
    })

    # Dataset 2: Support Tickets
    support_path = base_path / "support"
    support_files = [support_path / "tickets.csv"]

    registry["datasets"].append({
        "id": "support",
        "name": "Support Tickets",
        "description": "Customer support ticket lifecycle and satisfaction data. Supports analysis of SLA compliance, resolution times, customer satisfaction, and support team performance.",
        "domain": "Customer Support",
        "version_hash": f"sha256:{sha256_dataset(support_files)}",
        "row_count": 6417,
        "size_bytes": 548864,
        "files": [
            {
                "name": "tickets.csv",
                "path": "support/tickets.csv",
                "description": "Support ticket records with lifecycle metrics",
                "row_count": 6417,
                "schema": {
                    "ticket_id": {"type": "INTEGER", "description": "Unique ticket identifier"},
                    "created_at": {"type": "TIMESTAMP", "description": "Ticket creation timestamp"},
                    "resolved_at": {"type": "TIMESTAMP", "description": "Resolution timestamp (NULL if open)", "nullable": True},
                    "category": {"type": "VARCHAR", "description": "Ticket category", "values": ["Technical", "Billing", "Account", "Product"]},
                    "priority": {"type": "VARCHAR", "description": "Priority level", "values": ["Low", "Medium", "High", "Critical"]},
                    "csat_score": {"type": "INTEGER", "description": "Customer satisfaction (1-5, NULL if no response)", "nullable": True},
                    "sla_met": {"type": "BOOLEAN", "description": "Whether SLA was met"},
                    "resolution_time_hours": {"type": "DECIMAL", "description": "Time to resolution in hours (NULL if open)", "nullable": True},
                    "status": {"type": "VARCHAR", "description": "Current ticket status", "values": ["Open", "Resolved", "Closed"]},
                    "agent_id": {"type": "INTEGER", "description": "Assigned support agent"},
                    "channel": {"type": "VARCHAR", "description": "Support channel", "values": ["Email", "Chat", "Phone"]}
                }
            }
        ],
        "relationships": [],
        "prompts": [
            "What's our SLA compliance rate by priority level?",
            "Show me average customer satisfaction score by category",
            "Which critical tickets have been open the longest?",
            "What's the average resolution time by category?",
            "Show me tickets that missed SLA in the last week",
            "Find resolved tickets with low CSAT scores (1-2 stars) from the last month"
        ],
        "tags": ["support", "sla", "csat", "customer-service", "tickets"]
    })

    # Dataset 3: IoT Sensors
    sensors_path = base_path / "sensors"
    sensors_files = [sensors_path / "sensors.csv"]

    registry["datasets"].append({
        "id": "sensors",
        "name": "IoT Sensor Network",
        "description": "Environmental monitoring sensor readings with anomaly detection. Supports analysis of sensor health, environmental conditions, anomaly patterns, and predictive maintenance.",
        "domain": "IoT/Industrial Monitoring",
        "version_hash": f"sha256:{sha256_dataset(sensors_files)}",
        "row_count": 49950,
        "size_bytes": 4296704,
        "files": [
            {
                "name": "sensors.csv",
                "path": "sensors/sensors.csv",
                "description": "Time-series sensor readings with environmental metrics",
                "row_count": 49950,
                "schema": {
                    "sensor_id": {"type": "VARCHAR", "description": "Unique sensor identifier"},
                    "timestamp": {"type": "TIMESTAMP", "description": "Reading timestamp"},
                    "location": {"type": "VARCHAR", "description": "Physical location/zone"},
                    "zone": {"type": "VARCHAR", "description": "Logical grouping", "values": ["North", "South", "East", "West"]},
                    "temperature_c": {"type": "DECIMAL", "description": "Temperature in Celsius", "nullable": True},
                    "humidity_pct": {"type": "DECIMAL", "description": "Relative humidity (0-100)", "nullable": True},
                    "pressure_hpa": {"type": "DECIMAL", "description": "Atmospheric pressure (hPa)", "nullable": True},
                    "vibration_mm_s": {"type": "DECIMAL", "description": "Vibration level (mm/s, NULL for non-industrial)", "nullable": True},
                    "anomaly_flag": {"type": "BOOLEAN", "description": "Whether reading flagged as anomalous"},
                    "anomaly_type": {"type": "VARCHAR", "description": "Type of anomaly (NULL if none)", "nullable": True, "values": ["high_temp", "low_temp", "high_humidity", "sensor_fault", "vibration_alarm"]},
                    "battery_pct": {"type": "INTEGER", "description": "Battery level (0-100, NULL if powered)", "nullable": True},
                    "status": {"type": "VARCHAR", "description": "Sensor operational status", "values": ["online", "offline", "maintenance"]}
                }
            }
        ],
        "relationships": [],
        "prompts": [
            "How many anomalies were detected by location in the last 24 hours?",
            "What are the average temperature and humidity levels by zone?",
            "Show me all high temperature anomalies from the last week",
            "Which sensors have battery below 20%?",
            "What's the current sensor status distribution?",
            "Find sensors with dangerous vibration levels in the last 6 hours"
        ],
        "tags": ["iot", "sensors", "anomaly-detection", "time-series", "monitoring"]
    })

    return registry


def main():
    print("Generating dataset registry...")
    print()

    registry = generate_registry()

    # Write to file
    output_path = Path(__file__).parent.parent / "datasets" / "registry.json"
    with open(output_path, 'w') as f:
        json.dump(registry, f, indent=2)

    print(f"✓ Generated {output_path}")
    print()
    print("Registry Summary:")
    print(f"  Version: {registry['version']}")
    print(f"  Total datasets: {len(registry['datasets'])}")
    print()

    for dataset in registry["datasets"]:
        print(f"  {dataset['id']}:")
        print(f"    Name: {dataset['name']}")
        print(f"    Files: {len(dataset['files'])}")
        print(f"    Rows: {dataset['row_count']:,}")
        print(f"    Size: {dataset['size_bytes'] / 1024:.1f} KB")
        print(f"    Hash: {dataset['version_hash'][:20]}...")
        print(f"    Prompts: {len(dataset['prompts'])}")
        print()

    print("✅ Registry generation complete!")


if __name__ == "__main__":
    main()
