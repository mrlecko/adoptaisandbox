#!/usr/bin/env python3
"""
Validate generated datasets for correctness and quality.
"""

import csv
from pathlib import Path
from datetime import datetime


def validate_ecommerce():
    """Validate e-commerce dataset."""
    print("Validating E-commerce Dataset...")
    base_path = Path(__file__).parent.parent / "datasets" / "ecommerce"

    # Load all files
    orders = list(csv.DictReader(open(base_path / "orders.csv")))
    items = list(csv.DictReader(open(base_path / "order_items.csv")))
    inventory = list(csv.DictReader(open(base_path / "inventory.csv")))

    errors = []

    # Check foreign keys
    order_ids = {o["order_id"] for o in orders}
    for item in items:
        if item["order_id"] not in order_ids:
            errors.append(f"Invalid order_id in order_items: {item['order_id']}")

    product_ids = {p["product_id"] for p in inventory}
    for item in items:
        if item["product_id"] not in product_ids:
            errors.append(f"Invalid product_id in order_items: {item['product_id']}")

    # Check for negative values
    for order in orders:
        if float(order["total"]) < 0:
            errors.append(f"Negative total in order: {order['order_id']}")

    for item in items:
        if float(item["price"]) < 0:
            errors.append(f"Negative price in item: {item['item_id']}")
        if int(item["quantity"]) < 1:
            errors.append(f"Invalid quantity in item: {item['item_id']}")
        if not (0 <= int(item["discount"]) <= 100):
            errors.append(f"Invalid discount in item: {item['item_id']}")

    # Check status values
    valid_statuses = {"completed", "returned", "cancelled"}
    for order in orders:
        if order["status"] not in valid_statuses:
            errors.append(f"Invalid status: {order['status']}")

    if errors:
        print(f"  ❌ Found {len(errors)} errors:")
        for err in errors[:10]:
            print(f"     - {err}")
    else:
        print("  ✅ All validations passed!")

    return len(errors) == 0


def validate_support():
    """Validate support tickets dataset."""
    print("Validating Support Tickets Dataset...")
    base_path = Path(__file__).parent.parent / "datasets" / "support"

    tickets = list(csv.DictReader(open(base_path / "tickets.csv")))
    errors = []

    valid_priorities = {"Low", "Medium", "High", "Critical"}
    valid_statuses = {"Open", "Resolved", "Closed"}
    valid_categories = {"Technical", "Billing", "Account", "Product"}
    valid_channels = {"Email", "Chat", "Phone"}

    for ticket in tickets:
        # Check enums
        if ticket["priority"] not in valid_priorities:
            errors.append(f"Invalid priority: {ticket['priority']}")
        if ticket["status"] not in valid_statuses:
            errors.append(f"Invalid status: {ticket['status']}")
        if ticket["category"] not in valid_categories:
            errors.append(f"Invalid category: {ticket['category']}")
        if ticket["channel"] not in valid_channels:
            errors.append(f"Invalid channel: {ticket['channel']}")

        # Check CSAT range
        if ticket["csat_score"] and ticket["csat_score"] != "":
            csat = int(ticket["csat_score"])
            if not (1 <= csat <= 5):
                errors.append(f"Invalid CSAT score: {csat}")

        # Check resolution consistency
        if ticket["resolved_at"] and ticket["resolved_at"] != "":
            created = datetime.strptime(ticket["created_at"], "%Y-%m-%d %H:%M:%S")
            resolved = datetime.strptime(ticket["resolved_at"], "%Y-%m-%d %H:%M:%S")
            if resolved < created:
                errors.append(f"Resolved before created: {ticket['ticket_id']}")

    if errors:
        print(f"  ❌ Found {len(errors)} errors:")
        for err in errors[:10]:
            print(f"     - {err}")
    else:
        print("  ✅ All validations passed!")

    return len(errors) == 0


def validate_sensors():
    """Validate sensors dataset."""
    print("Validating IoT Sensors Dataset...")
    base_path = Path(__file__).parent.parent / "datasets" / "sensors"

    readings = list(csv.DictReader(open(base_path / "sensors.csv")))
    errors = []

    valid_statuses = {"online", "offline", "maintenance"}

    for reading in readings[:1000]:  # Sample validation (full dataset is large)
        # Check status
        if reading["status"] not in valid_statuses:
            errors.append(f"Invalid status: {reading['status']}")

        # Check temperature range
        if reading["temperature_c"] and reading["temperature_c"] != "":
            temp = float(reading["temperature_c"])
            if not (-20 <= temp <= 50):
                errors.append(f"Temperature out of range: {temp}")

        # Check humidity range
        if reading["humidity_pct"] and reading["humidity_pct"] != "":
            humidity = float(reading["humidity_pct"])
            if not (0 <= humidity <= 110):  # Allow slight overshoot for anomalies
                errors.append(f"Humidity out of range: {humidity}")

        # Check battery range
        if reading["battery_pct"] and reading["battery_pct"] != "":
            battery = int(reading["battery_pct"])
            if not (0 <= battery <= 100):
                errors.append(f"Battery out of range: {battery}")

        # Check anomaly consistency
        if reading["anomaly_type"] and reading["anomaly_type"] != "":
            if reading["anomaly_flag"] != "True":
                errors.append("Anomaly type set but flag is False")

    if errors:
        print(f"  ❌ Found {len(errors)} errors (sampled 1000 rows):")
        for err in errors[:10]:
            print(f"     - {err}")
    else:
        print("  ✅ All validations passed!")

    return len(errors) == 0


def main():
    print("=" * 60)
    print("Dataset Validation Report")
    print("=" * 60)
    print()

    results = []
    results.append(("E-commerce", validate_ecommerce()))
    print()
    results.append(("Support", validate_support()))
    print()
    results.append(("Sensors", validate_sensors()))

    print()
    print("=" * 60)
    print("Summary:")
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")
    print("=" * 60)

    if all(r[1] for r in results):
        print("\n✅ All datasets validated successfully!")
        return 0
    else:
        print("\n❌ Some datasets have validation errors")
        return 1


if __name__ == "__main__":
    exit(main())
