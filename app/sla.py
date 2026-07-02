"""SLA deadline + breach-risk math.

Pure functions over timezone-aware UTC datetimes. This is the logic most
likely to break silently (off-by-one on units, naive vs aware datetimes), so
it carries the heaviest tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Resolution SLA per severity, in minutes.
SLA_MINUTES = {
    "P1": 60,      # 1 hour
    "P2": 240,     # 4 hours
    "P3": 1440,    # 1 day
    "P4": 2880,    # 2 days
}

# A ticket is "at risk" if it will breach within this window (minutes).
DEFAULT_RISK_WINDOW_MIN = 30


def _as_utc(dt: datetime) -> datetime:
    """Coerce to timezone-aware UTC; treat naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sla_minutes(severity: str) -> int:
    """SLA budget in minutes for a severity. Unknown severity falls back to P3."""
    return SLA_MINUTES.get(severity, SLA_MINUTES["P3"])


def deadline(created_at: datetime, severity: str) -> datetime:
    """Absolute SLA deadline = created_at + budget."""
    return _as_utc(created_at) + timedelta(minutes=sla_minutes(severity))


def minutes_to_breach(created_at: datetime, severity: str, now: datetime) -> float:
    """Minutes until (positive) or since (negative) the SLA deadline."""
    delta = deadline(created_at, severity) - _as_utc(now)
    return delta.total_seconds() / 60.0


def is_breached(created_at: datetime, severity: str, now: datetime,
                resolved: bool = False) -> bool:
    """True if an unresolved ticket is past its deadline."""
    if resolved:
        return False
    return minutes_to_breach(created_at, severity, now) < 0


def is_at_risk(created_at: datetime, severity: str, now: datetime,
               resolved: bool = False, window_min: int = DEFAULT_RISK_WINDOW_MIN) -> bool:
    """True if an unresolved, not-yet-breached ticket breaches within window_min."""
    if resolved:
        return False
    mtb = minutes_to_breach(created_at, severity, now)
    return 0 <= mtb <= window_min


def _selfcheck() -> None:
    base = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    assert sla_minutes("P1") == 60
    assert sla_minutes("bogus") == 1440  # unknown -> P3 budget
    assert deadline(base, "P1") == datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc)
    # 50 min in, P1 (60 min budget) -> 10 min left -> at risk (window 30)
    now = base + timedelta(minutes=50)
    assert round(minutes_to_breach(base, "P1", now)) == 10
    assert is_at_risk(base, "P1", now) is True
    assert is_breached(base, "P1", now) is False
    # 70 min in -> breached
    now2 = base + timedelta(minutes=70)
    assert is_breached(base, "P1", now2) is True
    assert is_at_risk(base, "P1", now2) is False  # already breached, not "at risk"
    # resolved tickets are never at risk or breached
    assert is_breached(base, "P1", now2, resolved=True) is False
    assert is_at_risk(base, "P1", now, resolved=True) is False
    # naive datetime is treated as UTC (no crash)
    assert round(minutes_to_breach(base.replace(tzinfo=None), "P1", now)) == 10
    print("sla self-check OK")


if __name__ == "__main__":
    _selfcheck()
