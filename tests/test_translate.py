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
    assert len(got) == 8          # INJECT_CAP pre-screen
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
