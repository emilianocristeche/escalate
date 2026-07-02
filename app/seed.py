"""Seed the DB with synthetic tickets so the dashboard and /metrics have data.

SYNTHETIC ONLY — never seed with real customer or Movistar data.

Run: python -m app.seed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import classifier
from app.db import SessionLocal, init_db
from app.models import Ticket

# (subject, body, customer, minutes_ago) — deterministic, no randomness.
_SAMPLES = [
    ("Payments API returning 500 for all customers", "Every charge fails since 10am", "acme-co", 55),
    ("Cannot pay — card reader offline", "Terminal shows outage", "bluebird-cafe", 40),
    ("eSIM has no signal after activation", "Provisioned but no connectivity", "nomad-tel", 200),
    ("Invoice charge looks wrong", "Refund not processed on last invoice", "green-grocer", 900),
    ("Webhook endpoint timeout", "Integration returns 500 intermittently", "shipfast", 25),
    ("How do I export my invoices?", "Need documentation for billing export", "tiny-studio", 60),
    ("Locked out of my account", "2FA reset needed, cannot log in", "dev-shop", 180),
    ("Feature request: dark mode", "Would like a dark theme", "night-owl", 5000),
    ("Network connection drops on roaming", "Signal lost crossing border", "trek-co", 300),
    ("Login page shows an error", "Blocked at sign in, 500 error", "quickmart", 15),
]


def seed() -> int:
    init_db()
    now = datetime.now(timezone.utc)
    created = 0
    with SessionLocal() as db:
        for subject, body, customer, minutes_ago in _SAMPLES:
            labels = classifier.classify(subject, body)
            db.add(Ticket(
                subject=subject, body=body, customer=customer,
                severity=labels["severity"], category=labels["category"],
                created_at=now - timedelta(minutes=minutes_ago),
            ))
            created += 1
        db.commit()
    print(f"Seeded {created} synthetic tickets.")
    return created


if __name__ == "__main__":
    seed()
