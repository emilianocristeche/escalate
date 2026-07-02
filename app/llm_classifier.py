"""v2 LLM classifier (optional, behind a key).

Rules (v1) are fast and free but guess on ambiguous / mixed-language tickets.
This routes such tickets to an LLM. Requires ANTHROPIC_API_KEY; if the key or
SDK is missing, callers should fall back to rules.

The whole design point: you do NOT send every ticket here. The hybrid
classifier (see benchmark.py) only calls the LLM for tickets the rules flag as
low-confidence — typically a small fraction — so you get most of the accuracy
lift at a fraction of the latency and cost.
"""

from __future__ import annotations

import json
import os

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


def available() -> bool:
    """True if an LLM call can be made (key + SDK present)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def classify_llm(subject: str, body: str = "") -> dict[str, str]:
    """Classify one ticket via the LLM. Raises if unavailable."""
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
