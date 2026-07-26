"""A long paste must not silently swallow the hotkey.

Regression cover for a P1 found on 2026-07-26. `translate` inherited
`llm.complete`'s default `max_tokens=1024`, but the rewrite is ADDITIVE — the
reply always contains the whole request — so any paste past roughly two
thousand Chinese characters was truncated mid-payload, failed to parse, and
degraded to a no-op with no signal to the user at all. Measured on the product
path: a 2,074-character Chinese request came back parse_error=True, decision
noop. The bench never caught it because the longest preserve-long input is
619 characters.
"""
import json

import memtranslator.llm as llm
from memtranslator.config import MAX_OUTPUT_TOKENS, MIN_OUTPUT_TOKENS
from memtranslator.schema import Requirement
from memtranslator.translate import _estimate_tokens, output_budget, translate


def test_short_request_keeps_the_floor():
    assert output_budget("帮我写封邮件") == MIN_OUTPUT_TOKENS


def test_budget_grows_with_a_long_paste():
    short, long = "整理成周报：" + "记录。" * 20, "整理成周报：" + "记录。" * 800
    assert output_budget(long) > output_budget(short) > 0
    # a 2400-char Chinese paste must clear the old fixed cap that broke it
    assert output_budget("周" * 2400) > 1024


def test_budget_is_capped():
    assert output_budget("周" * 100_000) == MAX_OUTPUT_TOKENS


def test_budget_always_exceeds_the_input_itself():
    """The reply restates the whole request, so the ceiling must sit above
    the request's own token count or truncation is structural."""
    for n in (200, 1000, 3000):
        text = "记" * n
        assert output_budget(text) > _estimate_tokens(text)


def test_cjk_costs_more_than_latin():
    assert _estimate_tokens("周" * 100) > _estimate_tokens("a" * 100)


def test_translate_passes_the_scaled_budget(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["max_tokens"] = max_tokens
        return json.dumps({"decision": "noop"})
    monkeypatch.setattr(llm, "complete", fake)
    long_text = "把下面的记录整理成周报：" + "这一天做了很多事情。" * 200
    translate(long_text, [Requirement(text="周报要用 bullet points")])
    assert seen["max_tokens"] == output_budget(long_text) > MIN_OUTPUT_TOKENS


def test_truncated_output_is_reported_not_anonymous(monkeypatch):
    """A truncated reply still no-ops, but the reason must be visible —
    silent failure is what made this cost a week of wrong diagnosis."""
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: '{"decision": "apply", "polished": "抱歉这段被截')
    out = translate("整理周报", [Requirement(text="周报要用 bullet points")])
    assert out["decision"] == "noop" and out["parse_error"] is True
    assert out["reason"] == "unparseable_output"


def test_plain_model_noop_is_labelled_too(monkeypatch):
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: json.dumps({"decision": "noop"}))
    out = translate("整理周报", [Requirement(text="周报要用 bullet points")])
    assert out["decision"] == "noop" and out["parse_error"] is False
    assert out["reason"] == "model_noop"
