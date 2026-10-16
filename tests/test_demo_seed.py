"""Automatic demo seed: every run replaces the demo set, never duplicates.

Runs on in-memory SQLite always, and also on the database in
TEST_DATABASE_URL when set (CI points it at Postgres, where the advisory lock
that guards concurrent startups is exercised).
"""

import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import demo_seed, sla
from app.db import Base, normalize_database_url
from app.main import app
from app.models import Ticket

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
N = len(demo_seed.DEMO_TICKETS)

_URLS = ["sqlite://"] + ([os.environ["TEST_DATABASE_URL"]]
                         if os.getenv("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_URLS, ids=lambda u: u.split(":")[0])
def engine(request):
    url = request.param
    kwargs = ({"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
              if url.startswith("sqlite") else {})
    eng = create_engine(url, **kwargs)
    Base.metadata.drop_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


def _count(eng) -> int:
    with Session(eng) as s:
        return s.scalar(select(func.count()).select_from(Ticket))


def _demo_count(eng) -> int:
    with Session(eng) as s:
        return s.scalar(select(func.count()).select_from(Ticket).where(
            Ticket.customer.like(f"{demo_seed.DEMO_CUSTOMER_PREFIX}%")))


def test_seed_on_empty_db_inserts_all_demo_tickets(engine):
    assert demo_seed.seed_demo(engine, now=NOW) == N
    assert _count(engine) == N
    assert 15 <= N <= 20


def test_reseed_replaces_instead_of_duplicating(engine):
    demo_seed.seed_demo(engine, now=NOW)
    demo_seed.seed_demo(engine, now=NOW)  # e.g. a restart
    demo_seed.seed_demo(engine, now=NOW)
    assert _count(engine) == N


def test_reseed_moves_timestamps_to_the_new_boot(engine):
    later = NOW + timedelta(days=3)
    demo_seed.seed_demo(engine, now=NOW)
    demo_seed.seed_demo(engine, now=later)
    with Session(engine) as s:
        tickets = list(s.scalars(select(Ticket)))
    open_t = [t for t in tickets if not t.resolved]
    # Three days after the first boot everything would be breached; after the
    # reseed the demo looks fresh again.
    assert any(sla.is_at_risk(t.created_at, t.severity, later) for t in open_t)
    newest = max(_aware(t.created_at) for t in tickets)
    assert newest > later - timedelta(hours=1)


def test_reseed_keeps_non_demo_tickets(engine):
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Ticket(subject="real ticket", customer="someone-else",
                     severity="P3", category="general", created_at=NOW))
        s.commit()
    demo_seed.seed_demo(engine, now=NOW)
    demo_seed.seed_demo(engine, now=NOW)
    assert _count(engine) == N + 1
    assert _demo_count(engine) == N


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def test_demo_data_feeds_every_dashboard_panel(engine):
    demo_seed.seed_demo(engine, now=NOW)
    with Session(engine) as s:
        tickets = list(s.scalars(select(Ticket)))
    open_t = [t for t in tickets if not t.resolved]
    assert {t.severity for t in tickets} == {"P1", "P2", "P3", "P4"}
    assert any(sla.is_at_risk(t.created_at, t.severity, NOW) for t in open_t)   # "At risk"
    assert any(sla.is_breached(t.created_at, t.severity, NOW) for t in open_t)  # breach rate
    resolved = [t for t in tickets if t.resolved]                               # MTTR
    assert resolved and all(t.resolved_at and t.resolved_at > t.created_at for t in resolved)


def test_concurrent_seeds_do_not_duplicate(engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("advisory lock only exists on Postgres; SQLite runs one process")
    results, errors = [], []

    def run():
        try:
            results.append(demo_seed.seed_demo(engine, now=NOW))
        except Exception as e:  # surfaced below
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results == [N] * 4
    assert _count(engine) == N


@pytest.mark.parametrize("flag, expected_calls", [(None, 0), ("false", 0), ("true", 1)])
def test_startup_seeds_only_when_flag_is_set(monkeypatch, flag, expected_calls):
    calls = []
    monkeypatch.setattr(demo_seed, "seed_demo", lambda *a, **k: calls.append(1) or 0)
    if flag is None:
        monkeypatch.delenv("ESCALATE_SEED_DEMO", raising=False)
    else:
        monkeypatch.setenv("ESCALATE_SEED_DEMO", flag)
    with TestClient(app):
        pass
    assert len(calls) == expected_calls


def test_neon_url_gets_psycopg2_and_sslmode_require():
    url = make_url(normalize_database_url(
        "postgresql://u:p@ep-x-pooler.us-east-2.aws.neon.tech/neondb"))
    assert url.drivername == "postgresql+psycopg2"
    assert url.query["sslmode"] == "require"
    assert url.password == "p"


def test_neon_url_with_sslmode_keeps_its_query():
    raw = "postgresql://u:p@ep-x.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert normalize_database_url(raw) == raw.replace("postgresql://", "postgresql+psycopg2://")


@pytest.mark.parametrize("raw, expected", [
    ("postgres://u:p@db:5432/x", "postgresql+psycopg2://u:p@db:5432/x"),
    ("postgresql://u:p@db:5432/x", "postgresql+psycopg2://u:p@db:5432/x"),
    ("postgresql+psycopg2://u:p@db:5432/x", "postgresql+psycopg2://u:p@db:5432/x"),
    ("sqlite:///./escalate.db", "sqlite:///./escalate.db"),
])
def test_scheme_is_pinned_to_psycopg2(raw, expected):
    assert normalize_database_url(raw) == expected
