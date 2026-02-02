#!/usr/bin/env python3
"""
Generate Support Tickets dataset.

Follows UC2-Support-Tickets-Dataset.md specification.
Deterministic generation using seeded random.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

# Deterministic seed for reproducibility
RANDOM_SEED = 43
random.seed(RANDOM_SEED)

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "datasets" / "support"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Configuration
NUM_TICKETS = 8000
DATE_RANGE_DAYS = 90

# Categories and properties
CATEGORIES = {
    "Technical": {"weight": 0.40},
    "Billing": {"weight": 0.25},
    "Account": {"weight": 0.20},
    "Product": {"weight": 0.15},
}

PRIORITIES = {
    "Low": {"weight": 0.50, "sla_hours": 72, "sla_compliance": 0.95},
    "Medium": {"weight": 0.30, "sla_hours": 24, "sla_compliance": 0.90},
    "High": {"weight": 0.15, "sla_hours": 8, "sla_compliance": 0.80},
    "Critical": {"weight": 0.05, "sla_hours": 4, "sla_compliance": 0.70},
}

CHANNELS = {
    "Email": 0.50,
    "Chat": 0.35,
    "Phone": 0.15,
}

STATUSES = {
    "Resolved": 0.75,
    "Open": 0.20,
    "Closed": 0.05,
}

# CSAT distribution (of responses): 1★ (10%), 2★ (15%), 3★ (20%), 4★ (35%), 5★ (20%)
CSAT_DISTRIBUTION = [1, 2, 3, 4, 5]
CSAT_WEIGHTS = [10, 15, 20, 35, 20]


def generate_resolution_time(priority: str, sla_met: bool) -> float:
    """Generate realistic resolution time based on priority and SLA status."""
    sla_hours = PRIORITIES[priority]["sla_hours"]

    if sla_met:
        # Resolution within SLA: exponential distribution below SLA
        mean = sla_hours * 0.5
        resolution = random.expovariate(1 / mean)
        return min(resolution, sla_hours * 0.95)
    else:
        # SLA violation: resolution time above SLA
        overage = random.uniform(sla_hours * 1.1, sla_hours * 3.0)
        return overage


def is_business_hours(dt: datetime) -> bool:
    """Check if datetime is during business hours (Mon-Fri 9-5)."""
    return dt.weekday() < 5 and 9 <= dt.hour < 17


def generate_tickets() -> List[Dict]:
    """Generate support tickets."""
    tickets = []

    end_date = datetime.now()
    start_date = end_date - timedelta(days=DATE_RANGE_DAYS)

    ticket_id = 5001
    agent_id_start = 101
    num_agents = 20

    for _ in range(NUM_TICKETS):
        # Generate created_at with business hours weighting
        days_offset = random.randint(0, DATE_RANGE_DAYS)
        base_date = start_date + timedelta(days=days_offset)

        # Business hours peak
        if is_business_hours(base_date):
            hour = random.randint(9, 16)
        else:
            # Lower volume outside hours
            if random.random() < 0.7:
                continue  # Skip to create business hours concentration
            hour = random.randint(0, 23)

        created_at = base_date.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))

        # Monday morning spike
        if created_at.weekday() == 0 and 9 <= created_at.hour <= 11:
            if random.random() > 0.4:  # Extra tickets
                pass

        # End-of-month billing spike
        if created_at.day >= 28 and random.random() < 0.3:
            category = "Billing"
        else:
            category = random.choices(list(CATEGORIES.keys()), weights=[c["weight"] for c in CATEGORIES.values()])[0]

        priority = random.choices(list(PRIORITIES.keys()), weights=[p["weight"] for p in PRIORITIES.values()])[0]
        channel = random.choices(list(CHANNELS.keys()), weights=list(CHANNELS.values()))[0]
        status = random.choices(list(STATUSES.keys()), weights=list(STATUSES.values()))[0]

        agent_id = random.randint(agent_id_start, agent_id_start + num_agents - 1)

        # Determine SLA compliance based on priority
        sla_compliance_rate = PRIORITIES[priority]["sla_compliance"]
        sla_met = random.random() < sla_compliance_rate

        # Generate resolution data if not open
        resolved_at = None
        resolution_time_hours = None

        if status in ["Resolved", "Closed"]:
            resolution_time_hours = generate_resolution_time(priority, sla_met)
            max_resolution_hours = (end_date - created_at).total_seconds() / 3600

            if max_resolution_hours <= 0:
                # Ticket can't be resolved in the available time window.
                status = "Open"
                sla_met = False
                resolution_time_hours = None
                resolved_at = None
            else:
                if resolution_time_hours > max_resolution_hours:
                    # Keep resolution strictly after creation and before "now".
                    resolution_time_hours = max(
                        0.01,
                        random.uniform(0.01, max_resolution_hours)
                    )

                resolved_at = created_at + timedelta(hours=resolution_time_hours)

                # Adjust sla_met based on actual resolution time.
                sla_hours = PRIORITIES[priority]["sla_hours"]
                sla_met = resolution_time_hours <= sla_hours
        else:
            sla_met = False  # Open tickets don't have SLA status yet

        # Generate CSAT score (60% response rate)
        csat_score = None
        if status == "Resolved" and random.random() < 0.60:
            csat_score = random.choices(CSAT_DISTRIBUTION, weights=CSAT_WEIGHTS)[0]

        # Format timestamps
        created_at_str = created_at.strftime("%Y-%m-%d %H:%M:%S")
        resolved_at_str = resolved_at.strftime("%Y-%m-%d %H:%M:%S") if resolved_at else None

        tickets.append({
            "ticket_id": ticket_id,
            "created_at": created_at_str,
            "resolved_at": resolved_at_str,
            "category": category,
            "priority": priority,
            "csat_score": csat_score if csat_score else "",
            "sla_met": sla_met,
            "resolution_time_hours": round(resolution_time_hours, 2) if resolution_time_hours else "",
            "status": status,
            "agent_id": agent_id,
            "channel": channel,
        })
        ticket_id += 1

    return tickets


def write_csv(filename: str, data: List[Dict], fieldnames: List[str]):
    """Write data to CSV file."""
    filepath = OUTPUT_DIR / filename
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"✓ Generated {filepath} ({len(data)} rows)")


def main():
    print("Generating Support Tickets Dataset...")
    print(f"Random seed: {RANDOM_SEED}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    # Generate tickets
    tickets = generate_tickets()

    fieldnames = [
        "ticket_id", "created_at", "resolved_at", "category", "priority",
        "csat_score", "sla_met", "resolution_time_hours", "status", "agent_id", "channel"
    ]
    write_csv("tickets.csv", tickets, fieldnames)

    # Statistics
    print()
    print("Dataset Statistics:")
    print(f"  Total tickets: {len(tickets)}")

    # Status distribution
    status_counts = {}
    for ticket in tickets:
        status_counts[ticket["status"]] = status_counts.get(ticket["status"], 0) + 1
    print(f"  Status distribution: {status_counts}")

    # Priority distribution
    priority_counts = {}
    for ticket in tickets:
        priority_counts[ticket["priority"]] = priority_counts.get(ticket["priority"], 0) + 1
    print(f"  Priority distribution: {priority_counts}")

    # SLA compliance by priority
    print("  SLA Compliance by priority:")
    for priority in PRIORITIES.keys():
        priority_tickets = [t for t in tickets if t["priority"] == priority and t["status"] in ["Resolved", "Closed"]]
        if priority_tickets:
            sla_met_count = sum(1 for t in priority_tickets if t["sla_met"])
            compliance_rate = (sla_met_count / len(priority_tickets)) * 100
            print(f"    {priority}: {compliance_rate:.1f}% ({sla_met_count}/{len(priority_tickets)})")

    # CSAT response rate
    resolved_tickets = [t for t in tickets if t["status"] == "Resolved"]
    csat_responses = sum(1 for t in resolved_tickets if t["csat_score"] != "")
    if resolved_tickets:
        response_rate = (csat_responses / len(resolved_tickets)) * 100
        print(f"  CSAT response rate: {response_rate:.1f}%")

    # CSAT distribution
    if csat_responses > 0:
        csat_counts = {}
        for ticket in resolved_tickets:
            if ticket["csat_score"] != "":
                score = ticket["csat_score"]
                csat_counts[score] = csat_counts.get(score, 0) + 1
        print("  CSAT distribution:")
        for score in sorted(csat_counts.keys()):
            pct = (csat_counts[score] / csat_responses) * 100
            print(f"    {score}★: {pct:.1f}%")

    # Average resolution time by priority
    print("  Average resolution time by priority:")
    for priority in PRIORITIES.keys():
        priority_resolved = [t for t in tickets if t["priority"] == priority and t["resolution_time_hours"] != ""]
        if priority_resolved:
            avg_time = sum(float(t["resolution_time_hours"]) for t in priority_resolved) / len(priority_resolved)
            sla_hours = PRIORITIES[priority]["sla_hours"]
            print(f"    {priority}: {avg_time:.2f}h (SLA: {sla_hours}h)")

    print()
    print("✅ Support Tickets dataset generation complete!")


if __name__ == "__main__":
    main()
