import json
import memtranslator.llm as llm
from memtranslator.schema import Requirement
from memtranslator.translate import parse_patch, recall, translate


def _reqs(*texts, status="active"):
    return [Requirement(text=t, status=status) for t in texts]


# ---- parse_patch -----------------------------------------------------------

def test_parse_noop():
    patch, err = parse_patch('{"decision": "noop"}')
    assert patch == {"decision": "noop"} and err is False


def test_parse_apply():
    patch, err = parse_patch(
        '{"decision": "apply", "applied_ids": ["req-1"], "polished": "x"}')
    assert patch["decision"] == "apply" and patch["polished"] == "x"
    assert err is False


def test_parse_fenced_json():
    patch, err = parse_patch(
        '```json\n{"decision": "apply", "applied_ids": [], "polished": "x"}\n```')
    assert patch["decision"] == "apply" and err is False


def test_parse_trailing_prose():
    # observed flash-model pattern: valid JSON followed by chatter
    patch, err = parse_patch(
        '{"decision": "noop"}\n\nI kept the request unchanged because...')
    assert patch == {"decision": "noop"} and err is False


def test_parse_garbage_degrades_to_noop():
    patch, err = parse_patch("not json at all")
    assert patch == {"decision": "noop"} and err is True


def test_parse_apply_without_polished_is_noop():
    patch, err = parse_patch('{"decision": "apply"}')
    assert patch == {"decision": "noop"} and err is True


# ---- recall ----------------------------------------------------------------

def test_recall_filters_retired_and_caps():
    reqs = _reqs(*[f"r{i}" for i in range(40)])
    reqs += _reqs("retired one", status="retired")
    got = recall(reqs)
    assert len(got) == 16         # INJECT_CAP safety valve
    assert all(r.status == "active" for r in got)
    assert got[-1].text == "r39"  # newest kept


# ---- translate -------------------------------------------------------------

def test_translate_apply(monkeypatch):
    reqs = _reqs("Emails under 120 words.")
    rid = reqs[0].id
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (
        f'{{"decision": "apply", "applied_ids": ["{rid}"], '
        f'"polished": "Draft a short email (under 120 words) to my landlord."}}'))
    out = translate("Draft an email to my landlord.", reqs)
    assert out["decision"] == "apply"
    assert out["applied_ids"] == [rid]
    assert "120 words" in out["polished"]
    assert out["parse_error"] is False


def test_translate_filters_unknown_applied_ids(monkeypatch):
    reqs = _reqs("A")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (
        '{"decision": "apply", "applied_ids": ["req-fabricated"], '
        '"polished": "do something, briefly"}'))
    out = translate("do something", reqs)
    assert out["decision"] == "apply"
    assert out["applied_ids"] == []


def test_translate_no_requirements_short_circuits(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return "{}"

    monkeypatch.setattr(llm, "complete", boom)
    out = translate("hello", [])
    assert out["decision"] == "noop"
    assert out["reason"] == "no_active_requirements"
    assert called["n"] == 0  # no LLM call without requirements


def test_translate_malformed_output_noops(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "MALFORMED")
    out = translate("hello", _reqs("A"))
    assert out["decision"] == "noop"
    assert out["parse_error"] is True


# ---- edits wire (2026-07-30 latency tier) ---------------------------------

def test_splice_edits_inserts_and_appends():
    from memtranslator.translate import splice_edits
    out = splice_edits("给房东写封邮件催修暖气",
                       [{"after": "写封邮件", "insert": "（不超过120词）"},
                        {"append": "，语气客气点。"}])
    assert out == "给房东写封邮件（不超过120词）催修暖气，语气客气点。"


def test_splice_edits_rejects_ambiguous_or_missing_anchor():
    from memtranslator.translate import splice_edits
    assert splice_edits("写邮件，再写邮件", [{"after": "写邮件", "insert": "x"}]) is None
    assert splice_edits("写周报", [{"after": "写邮件", "insert": "x"}]) is None
    assert splice_edits("写周报", [{"append": ""}]) is None


def test_translate_edits_wire_assembles_polished(monkeypatch):
    import memtranslator.config as cfg
    monkeypatch.setattr(cfg, "TRANSLATE_WIRE", "edits")
    monkeypatch.setattr(cfg, "EDITS_MIN_TOKENS", 0)
    reqs = _reqs("Emails stay under 120 words")

    def fake(model, system, user, max_tokens=1024, **kw):
        assert "INSERTIONS ONLY" in system
        return json.dumps({"decision": "apply", "applied": [1],
                           "edits": [{"after": "写封邮件", "insert": "（不超过120词）"}]},
                          ensure_ascii=False)
    monkeypatch.setattr(llm, "complete", fake)
    out = translate("帮我给房东写封邮件催修暖气", reqs)
    assert out["decision"] == "apply"
    assert out["polished"] == "帮我给房东写封邮件（不超过120词）催修暖气"
    assert out["applied_ids"] == [reqs[0].id]


def test_translate_edits_wire_bad_anchor_degrades_to_noop(monkeypatch):
    import memtranslator.config as cfg
    monkeypatch.setattr(cfg, "TRANSLATE_WIRE", "edits")
    monkeypatch.setattr(cfg, "EDITS_MIN_TOKENS", 0)

    def fake(model, system, user, max_tokens=1024, **kw):
        return json.dumps({"decision": "apply", "applied": [1],
                           "edits": [{"after": "不存在的锚", "insert": "x"}]},
                          ensure_ascii=False)
    monkeypatch.setattr(llm, "complete", fake)
    out = translate("帮我写封邮件", _reqs("Emails stay short"))
    assert out["decision"] == "noop"
    assert out["reason"] == "edit_splice_failed"


def test_splice_edits_rejects_insert_inside_quoted_span():
    from memtranslator.translate import splice_edits
    text = "帮我看下这段：「All test names use snake_case.」改改语病"
    assert splice_edits(text, [{"after": "「All", "insert": "（中文）"}]) is None
    out = splice_edits(text, [{"after": "改改语病", "insert": "，用简体中文回复"}])
    assert out is not None and "「All test names use snake_case.」" in out
