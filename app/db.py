"""Database engine + session. DB URL is configurable so the same code runs on
Postgres (docker-compose) and SQLite (local/CI, zero infra)."""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Default to a local SQLite file so `uvicorn`/`pytest` work with no Postgres.
# docker-compose overrides this with a Postgres URL.
_DEFAULT_URL = "sqlite:///./escalate.db"

# Key for the Postgres advisory lock that serializes startup work (create_all,
# demo seed) across workers/instances. Any constant bigint works.
STARTUP_LOCK_KEY = 0x45534341  # "ESCA"


def normalize_database_url(url: str) -> str:
    """Make a hosted-Postgres URL usable by SQLAlchemy 2.0 + psycopg2.

    - Managed hosts hand out a scheme with no driver: `postgres://…` (Render,
      Heroku), which SQLAlchemy 2.x rejects, or `postgresql://…` (Neon), which
      SQLAlchemy 2.1+ maps to psycopg 3 — not installed here. Pin both to
      psycopg2, the driver in requirements.txt. An explicit `+driver` is kept.
    - Neon only accepts TLS connections. Its copied connection strings already
      carry `?sslmode=require`; if someone pastes one without it, add it, so
      the failure mode is never a confusing SSL error at startup.
    """
    for bare in ("postgres://", "postgresql://"):
        if url.startswith(bare):
            url = "postgresql+psycopg2://" + url[len(bare):]
    if url.startswith("postgresql"):
        parsed = make_url(url)
        if (parsed.host or "").endswith(".neon.tech") and "sslmode" not in parsed.query:
            url = parsed.update_query_dict({"sslmode": "require"}).render_as_string(
                hide_password=False)
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", _DEFAULT_URL))

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping: Neon's free compute suspends after a few idle minutes and
    # drops open connections; test each pooled connection before use instead
    # of failing the first request after a quiet period.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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


def lock_startup(conn) -> None:
    """Serialize startup work on Postgres with a transaction-scoped advisory lock.

    pg_advisory_xact_lock is released automatically at COMMIT/ROLLBACK, so it
    also works through a transaction-mode pooler (Neon's "-pooler" endpoint).
    SQLite has no equivalent; it is only used for local runs and tests, which
    start a single process.
    """
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": STARTUP_LOCK_KEY})


def init_db(bind=None) -> None:
    """Create tables. Called on app startup and by the seed script.

    On Postgres the DDL runs under the startup lock, so several workers booting
    at once cannot race on CREATE TABLE.
    """
    from app import models  # noqa: F401  (register models on Base)
    with (bind or engine).begin() as conn:
        lock_startup(conn)
        Base.metadata.create_all(bind=conn)
