"""Aggregate metrics over a list of tickets. Pure function of (tickets, now)
so it is trivially testable without a database."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from app import sla


def compute_metrics(tickets, now: datetime) -> dict:
    """Return the metrics payload for a collection of Ticket-like objects.

    Each ticket needs: severity, category, resolved, created_at, resolved_at.
    """
    total = len(tickets)
    resolved = [t for t in tickets if t.resolved]
    open_tickets = [t for t in tickets if not t.resolved]

    breached_open = sum(
        1 for t in open_tickets
        if sla.is_breached(t.created_at, t.severity, now)
    )
    at_risk = sum(
        1 for t in open_tickets
        if sla.is_at_risk(t.created_at, t.severity, now)
    )

    # Mean time to resolution (minutes), over resolved tickets that have a timestamp.
    durations = [
        (t.resolved_at - t.created_at).total_seconds() / 60.0
        for t in resolved
        if t.resolved_at is not None
    ]
    mttr = round(sum(durations) / len(durations), 1) if durations else None

    return {
        "total": total,
        "open": len(open_tickets),
        "resolved": len(resolved),
        "breached_open": breached_open,
        "at_risk": at_risk,
        "breach_rate": round(breached_open / len(open_tickets), 3) if open_tickets else 0.0,
        "by_category": dict(Counter(t.category for t in tickets)),
        "by_severity": dict(Counter(t.severity for t in tickets)),
        "mttr_minutes": mttr,
    }
