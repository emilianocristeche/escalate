"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = ""
    customer: str = ""
    # Optional: lets the seed script backdate tickets. Defaults to now server-side.
    created_at: datetime | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject: str
    body: str
    customer: str
    severity: str
    category: str
    resolved: bool
    created_at: datetime
    resolved_at: datetime | None


class TicketRisk(TicketOut):
    minutes_to_breach: float
    deadline: datetime


class Metrics(BaseModel):
    total: int
    open: int
    resolved: int
    breached_open: int
    at_risk: int
    breach_rate: float
    by_category: dict[str, int]
    by_severity: dict[str, int]
    mttr_minutes: float | None
