"""Database engine + session. DB URL is configurable so the same code runs on
Postgres (docker-compose) and SQLite (local/CI, zero infra)."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Default to a local SQLite file so `uvicorn`/`pytest` work with no Postgres.
# docker-compose overrides this with a Postgres URL.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./escalate.db")

# Managed hosts (Render, Heroku) hand out `postgres://…`, which SQLAlchemy 2.0
# no longer accepts. Normalize to the driver-qualified scheme.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yield a session, always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables. Called on app startup and by the seed script."""
    from app import models  # noqa: F401  (register models on Base)
    Base.metadata.create_all(bind=engine)
