#!/usr/bin/env python3
"""
Generate E-commerce dataset with orders, order_items, and inventory.

Follows UC1-Ecommerce-Dataset.md specification.
Deterministic generation using seeded random.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

# Deterministic seed for reproducibility
RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "datasets" / "ecommerce"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Configuration
NUM_ORDERS = 5000
NUM_PRODUCTS = 500
NUM_CUSTOMERS = 2000
DATE_RANGE_DAYS = 180

# Categories and their properties
CATEGORIES = {
    "Electronics": {"weight": 0.30, "return_rate": 0.15, "discount_rate": 0.45, "price_range": (20, 500)},
    "Clothing": {"weight": 0.35, "return_rate": 0.18, "discount_rate": 0.50, "price_range": (10, 150)},
    "Home": {"weight": 0.20, "return_rate": 0.10, "discount_rate": 0.35, "price_range": (15, 300)},
    "Books": {"weight": 0.10, "return_rate": 0.05, "discount_rate": 0.25, "price_range": (5, 50)},
    "Toys": {"weight": 0.05, "return_rate": 0.12, "discount_rate": 0.40, "price_range": (8, 80)},
}

PRODUCT_NAMES = {
    "Electronics": ["Wireless Mouse", "USB Cable", "Headphones", "Keyboard", "Monitor", "Webcam", "Phone Case", "Charger", "Speaker", "Laptop Stand"],
    "Clothing": ["Cotton T-Shirt", "Jeans", "Sweater", "Jacket", "Sneakers", "Dress", "Polo Shirt", "Shorts", "Hoodie", "Socks"],
    "Home": ["Coffee Maker", "Lamp", "Towel Set", "Pillow", "Blanket", "Storage Box", "Picture Frame", "Candle", "Wall Art", "Rug"],
    "Books": ["Fiction Novel", "Cookbook", "Biography", "Travel Guide", "Self-Help", "Mystery", "Science Fiction", "History", "Poetry", "Children's Book"],
    "Toys": ["Board Game", "Puzzle", "Action Figure", "Building Blocks", "Doll", "RC Car", "Ball", "Stuffed Animal", "Art Set", "Educational Game"],
}

ORDER_STATUSES = ["completed", "returned", "cancelled"]


def generate_products() -> List[Dict]:
    """Generate product inventory."""
    products = []
    product_id = 201

    for category, props in CATEGORIES.items():
        num_products = int(NUM_PRODUCTS * props["weight"])

        for i in range(num_products):
            name_base = random.choice(PRODUCT_NAMES[category])
            variant = random.choice(["", " Pro", " Plus", " Mini", " Classic", " Deluxe"])
            name = f"{name_base}{variant}"

            # Stock distribution: 10% out of stock, 30% low, 60% adequate
            stock_choice = random.random()
            if stock_choice < 0.10:
                stock = 0
            elif stock_choice < 0.40:
                stock = random.randint(1, 19)
            else:
                stock = random.randint(20, 500)

            products.append({
                "product_id": product_id,
                "name": name,
                "category": category,
                "stock": stock,
            })
            product_id += 1

    return products


def generate_orders(products: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """Generate orders and order items."""
    orders = []
    order_items = []

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DATE_RANGE_DAYS)

    order_id = 1001
    item_id = 10001

    for _ in range(NUM_ORDERS):
        # Generate order date with weekend spike
        days_offset = random.randint(0, DATE_RANGE_DAYS)
        order_date = start_date + timedelta(days=days_offset)

        # Weekend spike: 30% more likely
        if order_date.weekday() in [5, 6]:  # Sat, Sun
            if random.random() > 0.3:
                continue  # Skip to create weekend concentration

        customer_id = random.randint(501, 501 + NUM_CUSTOMERS - 1)

        # Determine order status and return
        status_roll = random.random()
        if status_roll < 0.85:
            status = "completed"
            returned = False
        elif status_roll < 0.97:
            status = "returned"
            returned = True
        else:
            status = "cancelled"
            returned = False

        # Generate 1-5 items per order (avg 2.4)
        num_items = random.choices([1, 2, 3, 4, 5], weights=[30, 35, 20, 10, 5])[0]
        order_total = 0

        for _ in range(num_items):
            product = random.choice(products)
            category_props = CATEGORIES[product["category"]]

            # Override return status based on category return rate
            if status == "completed" and random.random() < category_props["return_rate"]:
                status = "returned"
                returned = True

            quantity = random.choices([1, 2, 3], weights=[70, 20, 10])[0]

            # Generate price with some variance
            price_min, price_max = category_props["price_range"]
            base_price = random.uniform(price_min, price_max)
            price = round(base_price, 2)

            # Determine discount
            discount = 0
            if random.random() < category_props["discount_rate"]:
                discount = random.choice([5, 10, 15, 20, 25, 30])

            # Calculate item total
            item_total = price * quantity * (1 - discount / 100)
            order_total += item_total

            order_items.append({
                "item_id": item_id,
                "order_id": order_id,
                "product_id": product["product_id"],
                "category": product["category"],
                "quantity": quantity,
                "price": price,
                "discount": discount,
            })
            item_id += 1

        orders.append({
            "order_id": order_id,
            "customer_id": customer_id,
            "order_date": order_date.strftime("%Y-%m-%d"),
            "total": round(order_total, 2),
            "status": status,
            "returned": returned,
        })
        order_id += 1

    return orders, order_items


def write_csv(filename: str, data: List[Dict], fieldnames: List[str]):
    """Write data to CSV file."""
    filepath = OUTPUT_DIR / filename
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"✓ Generated {filepath} ({len(data)} rows)")


def main():
    print("Generating E-commerce Dataset...")
    print(f"Random seed: {RANDOM_SEED}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    # Generate products
    products = generate_products()
    write_csv("inventory.csv", products, ["product_id", "name", "category", "stock"])

    # Generate orders and items
    orders, order_items = generate_orders(products)
    write_csv("orders.csv", orders, ["order_id", "customer_id", "order_date", "total", "status", "returned"])
    write_csv("order_items.csv", order_items, ["item_id", "order_id", "product_id", "category", "quantity", "price", "discount"])

    # Statistics
    print()
    print("Dataset Statistics:")
    print(f"  Products: {len(products)}")
    print(f"  Orders: {len(orders)}")
    print(f"  Order Items: {len(order_items)}")
    print(f"  Avg items per order: {len(order_items) / len(orders):.2f}")

    # Status distribution
    status_counts = {}
    for order in orders:
        status_counts[order["status"]] = status_counts.get(order["status"], 0) + 1
    print(f"  Order statuses: {status_counts}")

    # Return rate by category
    category_returns = {}
    category_totals = {}
    for item in order_items:
        cat = item["category"]
        category_totals[cat] = category_totals.get(cat, 0) + 1
        # Find if this order was returned
        order = next(o for o in orders if o["order_id"] == item["order_id"])
        if order["returned"]:
            category_returns[cat] = category_returns.get(cat, 0) + 1

    print("  Return rates by category:")
    for cat in CATEGORIES.keys():
        if cat in category_totals and category_totals[cat] > 0:
            rate = (category_returns.get(cat, 0) / category_totals[cat]) * 100
            print(f"    {cat}: {rate:.1f}%")

    # Stock distribution
    out_of_stock = sum(1 for p in products if p["stock"] == 0)
    low_stock = sum(1 for p in products if 0 < p["stock"] < 20)
    print(f"  Stock levels: {out_of_stock} out of stock, {low_stock} low stock")

    print()
    print("✅ E-commerce dataset generation complete!")


if __name__ == "__main__":
    main()
