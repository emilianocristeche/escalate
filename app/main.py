"""Escalate API — FastAPI app.

Routes:
  POST /tickets            ingest + auto-classify a ticket
  GET  /tickets            list tickets (filter by resolved/severity/category)
  POST /tickets/{id}/resolve  mark resolved
  GET  /tickets/at-risk    open tickets breaching within ?window_min (default 30)
  GET  /metrics            aggregate queue health
  GET  /health             liveness probe (+ whether the API is read-only)

Writes go through security.guard_write: rate-limited per client IP and
disabled entirely when ESCALATE_READ_ONLY=true. With ESCALATE_SEED_DEMO=true,
startup fills an empty tickets table with synthetic demo data.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import classifier, demo_seed, metrics, security, sla
from app.db import get_db, init_db
from app.models import Ticket
from app.schemas import Metrics, TicketCreate, TicketOut, TicketRisk


def _now() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Public demo: never start with an empty queue (see app/demo_seed.py).
    if security.env_flag("ESCALATE_SEED_DEMO"):
        demo_seed.seed_demo()
    yield


app = FastAPI(title="Escalate", version="0.1.0", lifespan=lifespan)

log = logging.getLogger(__name__)

# Dashboard is a separate origin (Vercel). Only listed origins may call the API
# from a browser: set CORS_ORIGINS="https://your-dashboard.vercel.app"
# (comma-separated). The default only allows the local Vite dev server.
# CORS is a browser rule, not access control: scripts/curl ignore it, which is
# why writes are also rate-limited and can be disabled (security.py).
_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()]
if "*" in _origins:
    log.warning("CORS_ORIGINS contains '*': any website can call this API from a browser")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health():
    # The dashboard reads read_only to hide the create/resolve controls.
    return {"status": "ok", "read_only": security.read_only()}


@app.post("/tickets", response_model=TicketOut, status_code=201,
          dependencies=[Depends(security.guard_write)])
def create_ticket(payload: TicketCreate, db: Session = Depends(get_db)):
    labels = classifier.classify(payload.subject, payload.body)
    ticket = Ticket(
        subject=payload.subject,
        body=payload.body,
        customer=payload.customer,
        severity=labels["severity"],
        category=labels["category"],
        created_at=_now(),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/tickets", response_model=list[TicketOut])
def list_tickets(
    db: Session = Depends(get_db),
    resolved: bool | None = None,
    severity: str | None = None,
    category: str | None = None,
    limit: int = Query(100, le=1000),
):
    stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(limit)
    if resolved is not None:
        stmt = stmt.where(Ticket.resolved == resolved)
    if severity is not None:
        stmt = stmt.where(Ticket.severity == severity)
    if category is not None:
        stmt = stmt.where(Ticket.category == category)
    return list(db.scalars(stmt))


@app.post("/tickets/{ticket_id}/resolve", response_model=TicketOut,
          dependencies=[Depends(security.guard_write)])
def resolve_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    if not ticket.resolved:
        ticket.resolved = True
        ticket.resolved_at = _now()
        db.commit()
        db.refresh(ticket)
    return ticket


@app.get("/tickets/at-risk", response_model=list[TicketRisk])
def at_risk(
    db: Session = Depends(get_db),
    window_min: int = Query(sla.DEFAULT_RISK_WINDOW_MIN, ge=0, le=10080),
):
    now = _now()
    open_tickets = db.scalars(select(Ticket).where(Ticket.resolved == False))  # noqa: E712
    out = []
    for t in open_tickets:
        if sla.is_at_risk(t.created_at, t.severity, now, window_min=window_min):
            out.append(TicketRisk(
                **TicketOut.model_validate(t).model_dump(),
                minutes_to_breach=round(sla.minutes_to_breach(t.created_at, t.severity, now), 1),
                deadline=sla.deadline(t.created_at, t.severity),
            ))
    out.sort(key=lambda r: r.minutes_to_breach)
    return out


@app.get("/metrics", response_model=Metrics)
def get_metrics(db: Session = Depends(get_db)):
    # Aggregate queries: no ticket rows are loaded (polled every 10s).
    return metrics.compute_metrics_db(db, _now())
