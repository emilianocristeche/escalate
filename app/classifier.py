"""Rule-based ticket classifier: severity (P1-P4) + category.

Pure functions, zero dependencies — this is the v1 classifier. The Week-2
plan adds an optional LLM classifier and benchmarks the two (accuracy vs
latency vs cost). Keeping this rule-based path fast and free is the whole
point of that comparison.

ponytail: keyword heuristics, not ML. Upgrade path is the v2 LLM classifier
behind a flag, routing only low-confidence tickets to the model.
"""

from __future__ import annotations

# Order matters: first matching severity tier wins, most urgent first.
_SEVERITY_KEYWORDS = {
    "P1": ("outage", "down", "cannot pay", "can't pay", "critical", "all customers",
           "data loss", "breach", "everyone", "completely broken"),
    "P2": ("error", "failing", "failed", "not working", "doesn't work", "blocked",
           "broken", "timeout", "500", "crash"),
    "P4": ("how do i", "how to", "question", "request", "feature", "documentation",
           "clarification", "when will"),
}
# Anything that matches no tier above falls through to P3.
_DEFAULT_SEVERITY = "P3"

_CATEGORY_KEYWORDS = {
    "billing": ("invoice", "payment", "charge", "refund", "billing", "subscription", "price"),
    "connectivity": ("network", "esim", "sim", "signal", "connection", "connectivity", "roaming"),
    "api": ("api", "endpoint", "webhook", "integration", "sdk", "rate limit", "token", "500"),
    "account": ("login", "log in", "password", "access", "account", "2fa", "locked out"),
}
_DEFAULT_CATEGORY = "general"


def classify_severity(text: str) -> str:
    """Return one of P1..P4 from ticket text (case-insensitive keyword match)."""
    t = (text or "").lower()
    for severity, keywords in _SEVERITY_KEYWORDS.items():
        if any(k in t for k in keywords):
            return severity
    return _DEFAULT_SEVERITY


def classify_category(text: str) -> str:
    """Return a category label from ticket text."""
    t = (text or "").lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(k in t for k in keywords):
            return category
    return _DEFAULT_CATEGORY


def classify(subject: str, body: str = "") -> dict[str, str]:
    """Classify a ticket from its subject + body. Returns {severity, category}."""
    text = f"{subject}\n{body}"
    return {"severity": classify_severity(text), "category": classify_category(text)}


def classify_with_confidence(subject: str, body: str = "") -> dict:
    """Like classify(), plus a `confident` flag.

    Confidence proxy: True when an actual keyword matched, False when the text
    fell through to a default (P3 / general). This is the routing signal for the
    hybrid classifier — only low-confidence tickets are worth an LLM call.
    """
    text = (f"{subject}\n{body}").lower()
    sev = classify_severity(text)
    cat = classify_category(text)
    sev_matched = sev != _DEFAULT_SEVERITY
    cat_matched = cat != _DEFAULT_CATEGORY
    return {
        "severity": sev,
        "category": cat,
        # Confident only if BOTH axes hit a keyword — a default on either is a
        # signal the rules are guessing.
        "confident": sev_matched and cat_matched,
    }


def _selfcheck() -> None:
    assert classify_severity("Payment API is completely broken, all customers affected") == "P1"
    assert classify_severity("Login returns a 500 error") == "P2"
    assert classify_severity("How do I export my invoices?") == "P4"
    assert classify_severity("The dashboard colors look off") == "P3"  # no keyword -> default
    assert classify_category("Refund not processed on my invoice") == "billing"
    assert classify_category("eSIM has no signal") == "connectivity"
    assert classify_category("Webhook endpoint returns 500") == "api"
    assert classify_category("I am locked out of my account") == "account"
    assert classify_category("General feedback") == "general"
    assert classify("500 on the payments endpoint") == {"severity": "P2", "category": "billing"}
    print("classifier self-check OK")


if __name__ == "__main__":
    _selfcheck()
