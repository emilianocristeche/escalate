"""API tests against an in-memory SQLite DB (zero infra)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    # Fresh in-memory DB per test. StaticPool keeps ONE connection so every
    # session sees the same in-memory database (otherwise each connection gets
    # its own empty DB and the tables "disappear").
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    # main.lifespan calls init_db() on the real engine; harmless, but skip network.
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _iso(dt):
    return dt.isoformat()


def test_create_ticket_autoclassifies(client):
    r = client.post("/tickets", json={"subject": "Payments API 500 outage", "body": "all down"})
    assert r.status_code == 201
    data = r.json()
    assert data["severity"] == "P1"  # "outage"
    assert data["category"] == "billing"  # "payments"
    assert data["resolved"] is False


def test_at_risk_lists_soon_to_breach(client):
    # P1 budget is 60 min; created 55 min ago -> 5 min to breach -> at risk.
    created = datetime.now(timezone.utc) - timedelta(minutes=55)
    client.post("/tickets", json={
        "subject": "Card reader outage", "created_at": _iso(created),
    })
    # A fresh P4 ticket is nowhere near breach -> not at risk.
    client.post("/tickets", json={"subject": "How do I export invoices?"})

    r = client.get("/tickets/at-risk")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["severity"] == "P1"
    assert rows[0]["minutes_to_breach"] <= 30


def test_resolve_removes_from_metrics_breach(client):
    created = datetime.now(timezone.utc) - timedelta(minutes=200)  # P1 breached long ago
    post = client.post("/tickets", json={
        "subject": "Total outage everyone affected", "created_at": _iso(created),
    })
    tid = post.json()["id"]

    m1 = client.get("/metrics").json()
    assert m1["breached_open"] == 1

    client.post(f"/tickets/{tid}/resolve")
    m2 = client.get("/metrics").json()
    assert m2["breached_open"] == 0
    assert m2["resolved"] == 1
    assert m2["mttr_minutes"] is not None


def test_list_filter_by_category(client):
    client.post("/tickets", json={"subject": "refund on invoice"})       # billing
    client.post("/tickets", json={"subject": "eSIM no signal"})          # connectivity
    r = client.get("/tickets", params={"category": "billing"})
    assert [t["category"] for t in r.json()] == ["billing"]
