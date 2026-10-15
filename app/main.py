"""Escalate API — FastAPI app.

Routes:
  POST /tickets            ingest + auto-classify a ticket
  GET  /tickets            list tickets (filter by resolved/severity/category)
  POST /tickets/{id}/resolve  mark resolved
  GET  /tickets/at-risk    open tickets breaching within ?window_min (default 30)
  GET  /metrics            aggregate queue health
  GET  /health             liveness probe
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import classifier, metrics, sla
from app.db import get_db, init_db
from app.models import Ticket
from app.schemas import Metrics, TicketCreate, TicketOut, TicketRisk


def _now() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Escalate", version="0.1.0", lifespan=lifespan)

# Dashboard is a separate origin (Vercel). Default to open; lock down in prod via
# CORS_ORIGINS="https://your-dashboard.vercel.app" (comma-separated).
_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tickets", response_model=TicketOut, status_code=201)
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


@app.post("/tickets/{ticket_id}/resolve", response_model=TicketOut)
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
    tickets = list(db.scalars(select(Ticket)))
    return metrics.compute_metrics(tickets, _now())
