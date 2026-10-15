"""Rule-based ticket classifier: severity (P1-P4) + category.

Pure functions, zero dependencies — this is the v1 classifier. The Week-2
plan adds an optional LLM classifier and benchmarks the two (accuracy vs
latency vs cost). Keeping this rule-based path fast and free is the whole
point of that comparison.

Keywords match on word boundaries (so "down" does not fire on "download", nor
"sim" on "simple"), with an optional plural suffix ("outage" also matches
"outages", "breach" matches "breaches").
"""

from __future__ import annotations

import re

# Order matters: first matching severity tier wins, most urgent first.
_SEVERITY_KEYWORDS = {
    "P1": ("outage", "down", "cannot pay", "can't pay", "critical", "all customers",
           "data loss", "breach", "breached", "everyone", "completely broken"),
    "P2": ("error", "failing", "failed", "not working", "doesn't work", "blocked",
           "broken", "timeout", "500", "crash", "crashed", "crashing"),
    "P4": ("how do i", "how to", "question", "request", "feature", "documentation",
           "clarification", "when will"),
}
# Anything that matches no tier above falls through to P3.
_DEFAULT_SEVERITY = "P3"

_CATEGORY_KEYWORDS = {
    "billing": ("invoice", "payment", "charge", "refund", "refunded", "billing",
                "subscription", "price"),
    "connectivity": ("network", "esim", "sim", "signal", "connection", "connectivity", "roaming"),
    "api": ("api", "endpoint", "webhook", "integration", "sdk", "rate limit", "token", "500"),
    "account": ("login", "log in", "password", "access", "account", "2fa", "locked out"),
}
_DEFAULT_CATEGORY = "general"


def _keyword_regex(keywords: tuple[str, ...]) -> re.Pattern:
    """Compile keywords into one case-insensitive, word-bounded alternation.

    Shape: \\b(?:kw1|kw2|...)(?:e?s)?\\b. The optional "s"/"es" covers regular
    plurals; other inflections (crashed, refunded) are listed explicitly in the
    keyword tuples. Spaces inside a keyword match any run of whitespace.
    """
    alts = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keywords)
    return re.compile(rf"\b(?:{alts})(?:e?s)?\b", re.IGNORECASE)


_SEVERITY_RE = {sev: _keyword_regex(kws) for sev, kws in _SEVERITY_KEYWORDS.items()}
_CATEGORY_RE = {cat: _keyword_regex(kws) for cat, kws in _CATEGORY_KEYWORDS.items()}


def classify_severity(text: str) -> str:
    """Return one of P1..P4 from ticket text (case-insensitive keyword match)."""
    t = text or ""
    for severity, pattern in _SEVERITY_RE.items():
        if pattern.search(t):
            return severity
    return _DEFAULT_SEVERITY


def classify_category(text: str) -> str:
    """Return a category label from ticket text."""
    t = text or ""
    for category, pattern in _CATEGORY_RE.items():
        if pattern.search(t):
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
    text = f"{subject}\n{body}"
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
