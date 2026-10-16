"""The aggregate-SQL metrics must match the pure reference implementation.

Runs on in-memory SQLite always, and also on the database in
TEST_DATABASE_URL when set (CI points it at Postgres, the production DB).
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import metrics, sla
from app.db import Base
from app.models import Ticket

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
WINDOW = sla.DEFAULT_RISK_WINDOW_MIN

_URLS = ["sqlite://"] + ([os.environ["TEST_DATABASE_URL"]]
                         if os.getenv("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_URLS, ids=lambda u: u.split(":")[0])
def session(request):
    url = request.param
    kwargs = ({"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
              if url.startswith("sqlite") else {})
    engine = create_engine(url, **kwargs)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _dataset():
    """Open tickets right at / around each severity's breach and at-risk
    boundaries, an unknown severity (P3 budget), and resolved tickets."""
    tickets = []
    for sev in ["P1", "P2", "P3", "P4", "PX"]:
        budget = sla.sla_minutes(sev)
        for offset in [
            budget + 120,          # long breached
            budget + 1,            # just breached
            budget,                # exactly at deadline: at risk, not breached
            budget - 1,            # at risk
            budget - WINDOW,       # exactly at the edge of the risk window
            budget - WINDOW - 1,   # just outside the window
            5,                     # fresh
        ]:
            tickets.append(Ticket(subject=f"{sev}-{offset}", severity=sev, category="api",
                                  resolved=False, created_at=NOW - timedelta(minutes=offset)))
    for i, (sev, cat, age, took) in enumerate([
        ("P1", "billing", 300, 45), ("P2", "account", 900, 125.5), ("P3", "general", 3000, 61),
    ]):
        created = NOW - timedelta(minutes=age)
        tickets.append(Ticket(subject=f"done-{i}", severity=sev, category=cat, resolved=True,
                              created_at=created, resolved_at=created + timedelta(minutes=took)))
    return tickets


def test_sql_metrics_match_reference(session):
    tickets = _dataset()
    session.add_all(tickets)
    session.commit()

    expected = metrics.compute_metrics(tickets, NOW)
    got = metrics.compute_metrics_db(session, NOW)
    assert got == expected
    # Sanity: the dataset really exercises the edges.
    assert got["breached_open"] == 10 and got["at_risk"] == 15
    assert got["mttr_minutes"] == round((45 + 125.5 + 61) / 3, 1)


def test_sql_metrics_on_empty_table(session):
    assert metrics.compute_metrics_db(session, NOW) == metrics.compute_metrics([], NOW)


def test_sql_metrics_do_not_load_ticket_rows(session):
    session.add_all(_dataset())
    session.commit()
    statements = []
    event.listen(session.get_bind(), "before_cursor_execute",
                 lambda conn, cur, stmt, *a: statements.append(stmt))
    metrics.compute_metrics_db(session, NOW)
    assert statements, "expected queries to run"
    # Only aggregates: the ticket text columns are never selected.
    assert not any("tickets.subject" in st or "tickets.body" in st for st in statements)
