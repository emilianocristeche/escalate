from datetime import datetime, timedelta, timezone

from app import sla

BASE = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def test_sla_budget_lookup():
    assert sla.sla_minutes("P1") == 60
    assert sla.sla_minutes("P3") == 1440
    assert sla.sla_minutes("unknown") == 1440  # fallback to P3


def test_deadline():
    assert sla.deadline(BASE, "P1") == datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc)


def test_minutes_to_breach_positive_and_negative():
    assert round(sla.minutes_to_breach(BASE, "P1", BASE + timedelta(minutes=50))) == 10
    assert round(sla.minutes_to_breach(BASE, "P1", BASE + timedelta(minutes=70))) == -10


def test_at_risk_window():
    now = BASE + timedelta(minutes=50)  # 10 min to breach on P1
    assert sla.is_at_risk(BASE, "P1", now) is True
    assert sla.is_at_risk(BASE, "P1", now, window_min=5) is False  # 10 > 5


def test_breached_and_resolved_exclusion():
    breached_now = BASE + timedelta(minutes=70)
    assert sla.is_breached(BASE, "P1", breached_now) is True
    assert sla.is_at_risk(BASE, "P1", breached_now) is False  # past deadline != at risk
    # resolved tickets never count
    assert sla.is_breached(BASE, "P1", breached_now, resolved=True) is False
    assert sla.is_at_risk(BASE, "P1", BASE + timedelta(minutes=50), resolved=True) is False


def test_naive_datetime_treated_as_utc():
    now = BASE + timedelta(minutes=50)
    assert round(sla.minutes_to_breach(BASE.replace(tzinfo=None), "P1", now)) == 10
