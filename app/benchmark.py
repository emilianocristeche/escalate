"""Benchmark: rules-only vs LLM-only vs hybrid.

Runs the labeled set (app/eval_data.py) through each classifier and prints a
markdown table of accuracy / latency / cost. The hybrid uses the rules'
confidence flag to route only low-confidence tickets to the LLM.

Usage:
  python -m app.benchmark              # rules always; LLM+hybrid if ANTHROPIC_API_KEY set
  python -m app.benchmark --mock-llm   # verify the harness with a stubbed "perfect" LLM

Cost model: Haiku pricing (~$1/Mtok in, $5/Mtok out). Overridable via env
ESCALATE_LLM_IN_COST / ESCALATE_LLM_OUT_COST.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from app import classifier, llm_classifier
from app.eval_data import LABELED

# Rough per-ticket token footprint for the cost estimate.
_TOK_IN = 90
_TOK_OUT = 20
_IN_COST = float(os.getenv("ESCALATE_LLM_IN_COST", "1.0")) / 1_000_000
_OUT_COST = float(os.getenv("ESCALATE_LLM_OUT_COST", "5.0")) / 1_000_000
_LLM_COST_PER_CALL = _TOK_IN * _IN_COST + _TOK_OUT * _OUT_COST


def _score(preds) -> dict:
    """preds: list of (pred_sev, pred_cat) aligned with LABELED."""
    n = len(LABELED)
    sev_ok = sum(1 for (ps, _), (_, _, gs, _) in zip(preds, LABELED) if ps == gs)
    cat_ok = sum(1 for (_, pc), (_, _, _, gc) in zip(preds, LABELED) if pc == gc)
    both_ok = sum(
        1 for (ps, pc), (_, _, gs, gc) in zip(preds, LABELED)
        if ps == gs and pc == gc
    )
    return {"severity": sev_ok / n, "category": cat_ok / n, "both": both_ok / n}


def _run_rules():
    preds, t0 = [], time.perf_counter()
    for subj, body, _, _ in LABELED:
        r = classifier.classify(subj, body)
        preds.append((r["severity"], r["category"]))
    ms = (time.perf_counter() - t0) * 1000
    return preds, ms, 0.0, 0


def _run_llm(llm_fn):
    preds, t0 = [], time.perf_counter()
    for subj, body, gold_s, gold_c in LABELED:
        r = llm_fn(subj, body, gold_s, gold_c)
        preds.append((r["severity"], r["category"]))
    ms = (time.perf_counter() - t0) * 1000
    return preds, ms, _LLM_COST_PER_CALL * len(LABELED), len(LABELED)


def _run_hybrid(llm_fn):
    preds, routed, t0 = [], 0, time.perf_counter()
    for subj, body, gold_s, gold_c in LABELED:
        rc = classifier.classify_with_confidence(subj, body)
        if rc["confident"]:
            preds.append((rc["severity"], rc["category"]))
        else:
            routed += 1
            r = llm_fn(subj, body, gold_s, gold_c)
            preds.append((r["severity"], r["category"]))
    ms = (time.perf_counter() - t0) * 1000
    return preds, ms, _LLM_COST_PER_CALL * routed, routed


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    mock = "--mock-llm" in sys.argv
    n = len(LABELED)

    rows = []
    preds, ms, cost, calls = _run_rules()
    s = _score(preds)
    rows.append(("rules-only", s, ms, cost, calls, 0))

    llm_fn = None
    label = None
    fallbacks = []  # tickets where the real LLM failed and rules answered
    if mock:
        # Stub "perfect oracle" — verifies the harness; not a real accuracy claim.
        def llm_fn(subj, body, gold_s, gold_c):  # noqa: E731
            return {"severity": gold_s, "category": gold_c}
        label = "MOCK (perfect oracle)"
    elif llm_classifier.available():
        def llm_fn(subj, body, gold_s, gold_c):  # noqa: E731
            r = llm_classifier.classify_llm_or_rules(subj, body)
            if r["source"] == "rules_fallback":
                fallbacks.append(subj)
            return r
        label = os.getenv("ESCALATE_LLM_MODEL", "claude-haiku-4-5")

    if llm_fn is not None:
        p, ms, cost, calls = _run_llm(llm_fn)
        rows.append((f"llm-only [{label}]", _score(p), ms, cost, calls, calls))
        p, ms, cost, calls = _run_hybrid(llm_fn)
        rows.append((f"hybrid [{label}]", _score(p), ms, cost, calls, calls))

    print(f"\n# Classifier benchmark ({n} labeled tickets)\n")
    print("| Classifier | Severity acc | Category acc | Both acc | Latency | LLM calls | Est. cost |")
    print("|---|---|---|---|---|---|---|")
    for name, sc, ms, cost, calls, llm_calls in rows:
        print(f"| {name} | {_pct(sc['severity'])} | {_pct(sc['category'])} | "
              f"{_pct(sc['both'])} | {ms:.1f} ms | {llm_calls}/{n} | ${cost:.4f} |")

    if fallbacks:
        print(f"\n_{len(fallbacks)} LLM call(s) failed and fell back to rules "
              "(see warnings above); those rows are partly rules-scored._")

    if llm_fn is None:
        print("\n_LLM rows skipped: set ANTHROPIC_API_KEY (and `pip install anthropic`), "
              "or run with `--mock-llm` to verify the harness._")


if __name__ == "__main__":
    main()
