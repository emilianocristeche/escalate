"""Shared fixtures: fresh in-memory DB + TestClient, clean security state."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.security import write_limiter


@pytest.fixture()
def session_factory():
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
    return TestingSession


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    # main.lifespan calls init_db() on the real engine; harmless, but skip network.
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clean_security_state(monkeypatch):
    # Rate-limit counters are process-global; env flags must not leak between tests.
    for var in ("ESCALATE_READ_ONLY", "ESCALATE_WRITE_RATE_LIMIT",
                "ESCALATE_RATE_WINDOW_SEC", "ESCALATE_TRUST_PROXY", "ESCALATE_ENABLE_LLM",
                "ESCALATE_SEED_DEMO"):
        monkeypatch.delenv(var, raising=False)
    write_limiter.reset()
    yield
    write_limiter.reset()
