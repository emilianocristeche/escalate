"""Queue-health metrics.

compute_metrics_db() is what GET /metrics uses: it runs aggregate queries
(COUNT / SUM(CASE ...) / GROUP BY / AVG) so the database does the work and
no ticket rows are loaded into Python, however big the table gets.

compute_metrics() is the same calculation as a pure function over a list of
tickets. It is the readable reference: the tests check that both agree.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app import sla
from app.models import Ticket


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


def _count_if(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def compute_metrics_db(db: Session, now: datetime,
                       window_min: int = sla.DEFAULT_RISK_WINDOW_MIN) -> dict:
    """Same payload as compute_metrics(), computed with aggregate SQL.

    A ticket's deadline is created_at + budget(severity), so for each severity
    "breached" is created_at < now - budget and "at risk" (0 <= minutes to
    breach <= window) is now - budget <= created_at <= now - budget + window.
    Severities without a budget fall back to the P3 budget, as in sla.py.
    """
    window = timedelta(minutes=window_min)
    known = list(sla.SLA_MINUTES)
    groups = [(Ticket.severity == sev, now - timedelta(minutes=sla.sla_minutes(sev)))
              for sev in known]
    groups.append((Ticket.severity.not_in(known),
                   now - timedelta(minutes=sla.sla_minutes("P3"))))

    is_open = Ticket.resolved.is_(False)
    breached = or_(*[and_(sev, Ticket.created_at < cutoff) for sev, cutoff in groups])
    at_risk = or_(*[and_(sev, Ticket.created_at >= cutoff, Ticket.created_at <= cutoff + window)
                    for sev, cutoff in groups])

    total, resolved, breached_open, at_risk_open = db.execute(select(
        func.count(Ticket.id),
        _count_if(Ticket.resolved.is_(True)),
        _count_if(and_(is_open, breached)),
        _count_if(and_(is_open, at_risk)),
    )).one()
    open_count = total - resolved

    by_category = dict(db.execute(
        select(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category)).all())
    by_severity = dict(db.execute(
        select(Ticket.severity, func.count(Ticket.id)).group_by(Ticket.severity)).all())

    # Resolution time in minutes; date arithmetic differs per database.
    if db.get_bind().dialect.name == "sqlite":
        minutes = (func.julianday(Ticket.resolved_at) - func.julianday(Ticket.created_at)) * 1440.0
    else:
        minutes = func.extract("epoch", Ticket.resolved_at - Ticket.created_at) / 60.0
    mttr = db.scalar(select(func.avg(minutes))
                     .where(Ticket.resolved.is_(True), Ticket.resolved_at.is_not(None)))

    return {
        "total": total,
        "open": open_count,
        "resolved": resolved,
        "breached_open": breached_open,
        "at_risk": at_risk_open,
        "breach_rate": round(breached_open / open_count, 3) if open_count else 0.0,
        "by_category": by_category,
        "by_severity": by_severity,
        "mttr_minutes": round(float(mttr), 1) if mttr is not None else None,
    }
