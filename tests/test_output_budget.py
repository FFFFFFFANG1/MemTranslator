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


def test_glm_translator_gets_thinking_headroom():
    import memtranslator.config as cfg
    deepseek = llm.budget_for("ark:deepseek-v4-flash", cfg.PATCH_OUTPUT_TOKENS)
    glm = llm.budget_for("ark:glm-5.2", cfg.PATCH_OUTPUT_TOKENS)
    assert deepseek == cfg.PATCH_OUTPUT_TOKENS
    assert glm == llm.GLM_MAX_TOKENS


def test_translate_passes_the_flat_patch_budget(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["max_tokens"] = max_tokens
        return json.dumps({"decision": "noop"})
    monkeypatch.setattr(llm, "complete", fake)
    long_text = "把下面的记录整理成周报：" + "这一天做了很多事情。" * 200
    import memtranslator.config as cfg
    translate(long_text, [Requirement(text="周报要用 bullet points")])
    assert seen["max_tokens"] == llm.budget_for(
        cfg.MODELS["translator"], cfg.PATCH_OUTPUT_TOKENS)


def test_truncated_output_is_reported_not_anonymous(monkeypatch):
    """A truncated reply still no-ops, but the reason must be visible —
    silent failure is what made this cost a week of wrong diagnosis."""
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: '{"decision": "apply", "hunks": [{"old": "整')
    out = translate("整理周报", [Requirement(text="周报要用 bullet points")])
    assert out["decision"] == "noop" and out["parse_error"] is True
    assert out["reason"] == "unparseable_output"


def test_plain_model_noop_is_labelled_too(monkeypatch):
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: json.dumps({"decision": "noop"}))
    out = translate("整理周报", [Requirement(text="周报要用 bullet points")])
    assert out["decision"] == "noop" and out["parse_error"] is False
    assert out["reason"] == "model_noop"


def test_translator_compacts_long_request_view_from_4096_tokens(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["user"] = user
        return json.dumps({"decision": "noop"})

    monkeypatch.setattr(llm, "complete", fake)
    text = ("REQUEST-BEGIN-" + "甲" * 2500 + "MIDDLE-SENTINEL"
            + "乙" * 2500 + "-REQUEST-END")
    translate(text, [Requirement(text="Use bullet points.")])
    shown = seen["user"].split("User request:\n", 1)[1].split(
        "\n\nJSON:", 1)[0]

    assert shown.startswith("REQUEST-BEGIN-")
    assert shown.endswith("-REQUEST-END")
    assert "MIDDLE-SENTINEL" not in shown
    assert "[truncated]" in shown


def test_translator_patches_the_full_original_not_the_compacted_view(
        monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["user"] = user
        return json.dumps({
            "decision": "apply", "applied": [1],
            "hunks": [{"old": "-REQUEST-END",
                       "new": "-REQUEST-END; keep it concise"}],
        })

    monkeypatch.setattr(llm, "complete", fake)
    text = ("REQUEST-BEGIN-" + "甲" * 2500 + "MIDDLE-SENTINEL"
            + "乙" * 2500 + "-REQUEST-END")
    out = translate(text, [Requirement(text="Keep requests concise.")])
    shown = seen["user"].split("User request:\n", 1)[1].split(
        "\n\nJSON:", 1)[0]

    assert "MIDDLE-SENTINEL" not in shown and "[truncated]" in shown
    assert out["decision"] == "apply"
    assert "MIDDLE-SENTINEL" in out["polished"]
    assert out["polished"].endswith("-REQUEST-END; keep it concise")
