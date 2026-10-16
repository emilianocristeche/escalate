"""v2 LLM classifier (optional, OFF by default).

Rules (v1) are fast and free but guess on ambiguous / mixed-language tickets.
This routes such tickets to an LLM. It only runs when explicitly enabled with
ESCALATE_ENABLE_LLM=true AND ANTHROPIC_API_KEY is set AND the SDK is installed;
otherwise callers get the rule-based labels. Having a key in the environment is
not enough on its own, so a deploy never spends on LLM calls by accident.

The whole design point: you do NOT send every ticket here. The hybrid
classifier (see benchmark.py) only calls the LLM for tickets the rules flag as
low-confidence — typically a small fraction — so you get most of the accuracy
lift at a fraction of the latency and cost.
"""

from __future__ import annotations

import json
import logging
import os

from app import classifier
from app.security import env_flag

log = logging.getLogger(__name__)

SEVERITIES = ("P1", "P2", "P3", "P4")
CATEGORIES = ("billing", "connectivity", "api", "account", "general")

_SYSTEM = (
    "You triage customer support tickets. Return ONLY compact JSON: "
    '{"severity": one of P1|P2|P3|P4, "category": one of '
    "billing|connectivity|api|account|general}. "
    "P1=outage/cannot-transact, P2=broken feature/error, P3=normal issue, "
    "P4=question/request."
)

_MODEL = os.getenv("ESCALATE_LLM_MODEL", "claude-haiku-4-5-20251001")


def enabled() -> bool:
    """The explicit opt-in switch. Default: off."""
    return env_flag("ESCALATE_ENABLE_LLM")


def available() -> bool:
    """True if an LLM call can be made (opted in + key + SDK present)."""
    if not enabled() or not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def classify_llm(subject: str, body: str = "") -> dict[str, str]:
    """Classify one ticket via the LLM. Raises if disabled or unavailable."""
    if not enabled():
        raise RuntimeError("LLM classifier is disabled (set ESCALATE_ENABLE_LLM=true)")
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=_MODEL,
        max_tokens=64,
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"Subject: {subject}\nBody: {body}"}],
    )
    text = msg.content[0].text.strip()
    data = json.loads(text)
    sev = data.get("severity", "P3")
    cat = data.get("category", "general")
    # Guard against off-menu labels.
    if sev not in SEVERITIES:
        sev = "P3"
    if cat not in CATEGORIES:
        cat = "general"
    return {"severity": sev, "category": cat}


def classify_llm_or_rules(subject: str, body: str = "") -> dict[str, str]:
    """LLM classification with a logged fallback to the rule-based classifier.

    If the LLM is not enabled (ESCALATE_ENABLE_LLM), rules answer directly and
    no call is attempted (source "rules"). Otherwise any LLM failure (API error, timeout, non-JSON or truncated reply, missing
    SDK) is logged with its traceback and the ticket is classified by rules
    instead, so one bad response never drops a ticket. `source` says which
    path produced the labels ("rules", "llm" or "rules_fallback").
    """
    if not enabled():
        return {**classifier.classify(subject, body), "source": "rules"}
    try:
        return {**classify_llm(subject, body), "source": "llm"}
    except Exception:
        log.warning("LLM classification failed for %r; falling back to rules",
                    subject, exc_info=True)
        return {**classifier.classify(subject, body), "source": "rules_fallback"}
