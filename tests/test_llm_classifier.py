"""LLM classifier tests with a fake `anthropic` module (no network, no key)."""

import logging
import sys
import types

import pytest

from app import llm_classifier


def _fake_anthropic(monkeypatch, reply=None, exc=None, enable=True):
    """Install a stub `anthropic` whose messages.create returns `reply` or raises `exc`.

    Also opts in to the LLM (ESCALATE_ENABLE_LLM) unless enable=False. Returns
    the list of create() calls so tests can assert whether the SDK was hit.
    """
    calls = []
    if enable:
        monkeypatch.setenv("ESCALATE_ENABLE_LLM", "true")
    else:
        monkeypatch.delenv("ESCALATE_ENABLE_LLM", raising=False)

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            if exc is not None:
                raise exc
            block = types.SimpleNamespace(text=reply)
            return types.SimpleNamespace(content=[block])

    class _Client:
        messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = lambda: _Client()
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return calls


def test_llm_disabled_by_default_never_calls_sdk(monkeypatch):
    # A key alone must not turn the LLM on: the opt-in flag is required.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    calls = _fake_anthropic(monkeypatch, reply='{"severity": "P1", "category": "billing"}',
                            enable=False)
    assert llm_classifier.available() is False
    r = llm_classifier.classify_llm_or_rules("How do I export invoices?")
    assert r == {"severity": "P4", "category": "billing", "source": "rules"}
    assert calls == []
    with pytest.raises(RuntimeError):
        llm_classifier.classify_llm("x")


def test_llm_available_only_with_flag_and_key(monkeypatch):
    _fake_anthropic(monkeypatch, reply="{}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm_classifier.available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm_classifier.available() is True


def test_valid_llm_reply_is_used(monkeypatch):
    _fake_anthropic(monkeypatch, reply='{"severity": "P1", "category": "billing"}')
    r = llm_classifier.classify_llm_or_rules("Money is not moving")
    assert r == {"severity": "P1", "category": "billing", "source": "llm"}


def test_off_menu_labels_are_clamped(monkeypatch):
    _fake_anthropic(monkeypatch, reply='{"severity": "P0", "category": "sales"}')
    assert llm_classifier.classify_llm("x") == {"severity": "P3", "category": "general"}


@pytest.mark.parametrize("reply", [
    "Sure! Here is the JSON: {\"severity\": \"P1\"}",   # prose around JSON
    '{"severity": "P1", "categ',                         # truncated by max_tokens
    '["P1", "billing"]',                                 # valid JSON, wrong shape
])
def test_malformed_reply_falls_back_to_rules_and_logs(monkeypatch, caplog, reply):
    _fake_anthropic(monkeypatch, reply=reply)
    with caplog.at_level(logging.WARNING, logger="app.llm_classifier"):
        r = llm_classifier.classify_llm_or_rules("Payments API outage")
    assert r == {"severity": "P1", "category": "billing", "source": "rules_fallback"}
    assert "falling back to rules" in caplog.text


def test_api_error_falls_back_to_rules_and_logs(monkeypatch, caplog):
    _fake_anthropic(monkeypatch, exc=TimeoutError("read timed out"))
    with caplog.at_level(logging.WARNING, logger="app.llm_classifier"):
        r = llm_classifier.classify_llm_or_rules("How do I export invoices?")
    assert r["source"] == "rules_fallback"
    assert r["severity"] == "P4"
    assert "TimeoutError" in caplog.text
