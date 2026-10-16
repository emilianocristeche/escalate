"""API tests against an in-memory SQLite DB (zero infra). Fixtures: conftest.py."""

from datetime import datetime, timedelta, timezone

from app.models import Ticket


def _backdate(session_factory, ticket_id, created):
    # created_at is server-set and not part of the public API, so tests that
    # need an old ticket rewind it directly in the DB.
    with session_factory() as s:
        s.get(Ticket, ticket_id).created_at = created
        s.commit()


def test_create_ticket_autoclassifies(client):
    r = client.post("/tickets", json={"subject": "Payments API 500 outage", "body": "all down"})
    assert r.status_code == 201
    data = r.json()
    assert data["severity"] == "P1"  # "outage"
    assert data["category"] == "billing"  # "payments"
    assert data["resolved"] is False


def test_create_ticket_rejects_client_created_at(client):
    created = datetime.now(timezone.utc) - timedelta(days=3)
    r = client.post("/tickets", json={"subject": "x", "created_at": created.isoformat()})
    assert r.status_code == 422


def test_at_risk_lists_soon_to_breach(client, session_factory):
    # P1 budget is 60 min; created 55 min ago -> 5 min to breach -> at risk.
    created = datetime.now(timezone.utc) - timedelta(minutes=55)
    tid = client.post("/tickets", json={"subject": "Card reader outage"}).json()["id"]
    _backdate(session_factory, tid, created)
    # A fresh P4 ticket is nowhere near breach -> not at risk.
    client.post("/tickets", json={"subject": "How do I export invoices?"})

    r = client.get("/tickets/at-risk")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["severity"] == "P1"
    assert rows[0]["minutes_to_breach"] <= 30


def test_resolve_removes_from_metrics_breach(client, session_factory):
    created = datetime.now(timezone.utc) - timedelta(minutes=200)  # P1 breached long ago
    tid = client.post("/tickets", json={"subject": "Total outage everyone affected"}).json()["id"]
    _backdate(session_factory, tid, created)

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
