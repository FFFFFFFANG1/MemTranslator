import json

import memtranslator.llm as llm
import bench.suites.run_translate as rt
from bench.suites.schema import Check, TranslateCase


def _case(**kw):
    base = dict(id="t-1", category="apply-single", source="handwritten",
                requirements=["Emails under 120 words."],
                input="帮我给房东写封邮件", expect_decision="apply",
                must_apply=[0], checks=[])
    base.update(kw)
    return TranslateCase(**base)


def _fake_translate_apply(monkeypatch):
    def fake(model, system, user, max_tokens=1024, **kw):
        prompt = user[-1]["content"]
        num = int(prompt.split("[", 1)[1].split("]", 1)[0])
        records = [
            {"type": "plan", "decision": "apply", "apply": [num],
             "satisfied": [], "skip_kind": [], "skip_condition": [],
             "skip_superseded": []},
            {"type": "patch", "hunks": [{"old": "帮我给房东写封邮件",
                                            "new": "帮我给房东写封不超过120词的邮件"}]},
            {"type": "audit", "entries": [{
                "entry": num, "verdict": "apply",
                "evidence": "不超过120词"}]},
        ]
        return iter(map(json.dumps, records))
    monkeypatch.setattr(llm, "stream_text", fake)


def _fake_translate_noop(monkeypatch):
    records = [
        {"type": "plan", "decision": "noop", "apply": [],
         "satisfied": [], "skip_kind": [1], "skip_condition": [],
         "skip_superseded": []},
        {"type": "patch", "hunks": []},
        {"type": "audit", "entries": [{
            "entry": 1, "verdict": "not_applicable",
            "reason": "work_kind_mismatch"}]},
    ]
    monkeypatch.setattr(
        llm, "stream_text",
        lambda *a, **k: iter(map(json.dumps, records)))


def test_apply_case_passes_with_yes_judge(monkeypatch):
    _fake_translate_apply(monkeypatch)
    monkeypatch.setattr(rt, "judge", lambda crit, ctx: (True, False))
    r = rt.run_case(_case())
    assert r["pass"] is True and r["decision_ok"] and not r["judge_flags"]


def test_apply_case_fails_when_judge_says_no(monkeypatch):
    _fake_translate_apply(monkeypatch)
    monkeypatch.setattr(rt, "judge", lambda crit, ctx: (False, False))
    assert rt.run_case(_case())["pass"] is False


def test_noop_case_needs_no_judge(monkeypatch):
    _fake_translate_noop(monkeypatch)
    monkeypatch.setattr(rt, "judge",
                        lambda *a: (_ for _ in ()).throw(AssertionError))
    r = rt.run_case(_case(expect_decision="noop", must_apply=[]))
    assert r["pass"] is True


def test_mech_check_failure_short_circuits(monkeypatch):
    _fake_translate_apply(monkeypatch)
    monkeypatch.setattr(rt, "judge", lambda crit, ctx: (True, False))
    c = _case(checks=[Check(kind="mech", name="contains_all",
                            args={"keywords": ["水管"]})])
    r = rt.run_case(c)
    assert r["pass"] is False and "水管" in json.dumps(r["failures"],
                                                      ensure_ascii=False)


def test_wrong_decision_fails(monkeypatch):
    _fake_translate_noop(monkeypatch)
    r = rt.run_case(_case())          # expected apply, got noop
    assert r["pass"] is False and r["decision_ok"] is False
