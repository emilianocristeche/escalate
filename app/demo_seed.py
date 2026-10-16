"""Automatic demo seed: refresh the synthetic demo tickets on every startup.

Runs on app startup only when ESCALATE_SEED_DEMO=true (off by default, so local
runs and tests never seed unless asked). Meant for the public read-only demo,
where nobody can create tickets through the API.

Each run deletes the demo tickets (customer "demo-acct-*") and inserts them
again with timestamps relative to *now*, so the demo never ages: every boot
has tickets about to breach, some already breached and a recent MTTR. Tickets
from any other customer are never touched.

Safe to repeat and to run concurrently:
  - delete + insert happen in ONE transaction, so readers see the old set or
    the new one, never an empty or doubled queue;
  - on Postgres that transaction first takes an advisory lock
    (app.db.lock_startup), so several workers or instances booting at once
    run the refresh one after another and always end with exactly one set;
  - on SQLite (the public demo: an ephemeral file, one uvicorn worker) it runs
    once in the app lifespan, before the first request is served.

All data is fictional and generic: no real customers, carriers or companies.
Severity and category come from the same rule-based classifier the API uses
at ingest, so the demo shows the classifier's real output.

`python -m app.seed` is a separate manual script and keeps working as before.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert

from app import classifier
from app.db import engine as default_engine
from app.db import init_db, lock_startup
from app.models import Ticket

# uvicorn only configures its own loggers; log there so the outcome shows up
# in the Render logs ("demo seed refreshed: removed 18, inserted 18 …").
log = logging.getLogger("uvicorn.error")

# Every demo ticket belongs to a "demo-acct-NN" customer: that prefix is how a
# refresh finds (and only touches) the demo rows.
DEMO_CUSTOMER_PREFIX = "demo-acct-"

# (subject, body, customer, minutes_ago, resolved_after_minutes or None)
# SLA budgets: P1 60 min, P2 4 h, P3 1 day, P4 2 days; "at risk" = breaches
# within 30 min. The ages below are picked against those budgets.
DEMO_TICKETS: list[tuple[str, str, str, int, int | None]] = [
    # Open, at risk right after the seed.
    ("Checkout outage: payments failing for all customers",
     "Every card payment is declined since the last deploy.", "demo-acct-01", 45, None),
    ("Login service down for everyone",
     "Users get a blank page after entering their password.", "demo-acct-02", 52, None),
    ("Webhook deliveries failing with timeout",
     "Our integration stopped receiving events about an hour ago.", "demo-acct-03", 220, None),
    ("Order export endpoint returns 500",
     "The nightly export job aborts halfway through.", "demo-acct-04", 228, None),
    # Open, inside their SLA.
    ("Critical: data sync completely broken",
     "Records created today are missing from the reports.", "demo-acct-05", 10, None),
    ("Mobile app crashing on startup",
     "Happens on the latest version, right after the splash screen.", "demo-acct-06", 60, None),
    ("Password reset email not working",
     "The reset link never arrives for several users.", "demo-acct-07", 90, None),
    ("Signal drops intermittently in one region",
     "Devices reconnect after a few minutes, several times a day.", "demo-acct-08", 300, None),
    ("Roaming data slower than expected",
     "Speeds are far below the plan while travelling.", "demo-acct-09", 600, None),
    ("Refund still pending after a week",
     "The credit note was issued but the money has not arrived.", "demo-acct-10", 1000, None),
    ("How do I add a second admin to our account?",
     "We need another person to manage users.", "demo-acct-11", 120, None),
    ("Question about API rate limit tiers",
     "Which plan allows more requests per minute?", "demo-acct-12", 400, None),
    ("Feature request: CSV export for invoices",
     "Finance would like to download invoices as a spreadsheet.", "demo-acct-13", 2000, None),
    # Open, already past its SLA (feeds the breach rate).
    ("Subscription renewal date looks wrong",
     "The renewal shows next month instead of next year.", "demo-acct-14", 1600, None),
    # Resolved (feed MTTR).
    ("Status page down during maintenance",
     "The public status page did not load for a while.", "demo-acct-15", 600, 35),
    ("SDK upload failing with error 413",
     "Large files are rejected by the upload helper.", "demo-acct-16", 1500, 150),
    ("eSIM profile not showing in device settings",
     "The profile was downloaded but does not appear.", "demo-acct-17", 2500, 600),
    ("Clarification on invoice line items",
     "Two line items have the same description.", "demo-acct-18", 3000, 900),
]


def demo_rows(now: datetime) -> list[dict]:
    """Build insert rows for DEMO_TICKETS, timestamps relative to `now`."""
    rows = []
    for subject, body, customer, minutes_ago, resolved_after in DEMO_TICKETS:
        labels = classifier.classify(subject, body)
        created_at = now - timedelta(minutes=minutes_ago)
        rows.append({
            "subject": subject,
            "body": body,
            "customer": customer,
            "severity": labels["severity"],
            "category": labels["category"],
            "resolved": resolved_after is not None,
            "created_at": created_at,
            "resolved_at": (created_at + timedelta(minutes=resolved_after)
                            if resolved_after is not None else None),
        })
    return rows


def seed_demo(bind=None, now: datetime | None = None) -> int:
    """Replace the demo tickets with a fresh set, timestamps relative to `now`.

    Returns how many demo tickets were inserted (always len(DEMO_TICKETS)).
    """
    bind = bind or default_engine
    init_db(bind)
    now = now or datetime.now(timezone.utc)
    rows = demo_rows(now)
    with bind.begin() as conn:
        lock_startup(conn)  # held until this transaction commits (Postgres only)
        removed = conn.execute(
            delete(Ticket).where(Ticket.customer.like(f"{DEMO_CUSTOMER_PREFIX}%"))
        ).rowcount
        conn.execute(insert(Ticket), rows)
    log.info("demo seed refreshed: removed %d, inserted %d synthetic tickets",
             removed, len(rows))
    return len(rows)
