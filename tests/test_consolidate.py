"""M3: consolidation — bucketing, merge, style curation. FakeLLM only."""
import json

import memtranslator.llm as llm
from memtranslator.config import CONSOLIDATE_ACTIVE, CONSOLIDATE_ADDS, STYLE_RULE_CAP
from memtranslator.consolidate import buckets, run_consolidation, should_consolidate
from memtranslator.store import Store


def test_should_consolidate_thresholds(tmp_path):
    s = Store(tmp_path / "s.jsonl")
    assert not should_consolidate(s, adds_since=0)
    assert should_consolidate(s, adds_since=CONSOLIDATE_ADDS)
    for i in range(CONSOLIDATE_ACTIVE + 1):
        s.add(f"规则{i}", key=f"facet{i}.attr")
    assert should_consolidate(s, adds_since=0)


def test_unkeyed_entries_form_one_bucket(tmp_path):
    s = Store(tmp_path / "s.jsonl")
    a = s.add("邮件写短点，120词以内")            # manual, no key
    b = s.add("Emails must stay under 120 words")
    only = s.add("代码只给代码", key="code.explanation")
    bs = buckets(s.active())
    assert [set(x.id for x in g) for g in bs] == [{a.id, b.id}]
    assert all(only.id not in {x.id for x in g} for g in bs)


def test_buckets_group_by_key_exact_then_prefix(tmp_path):
    s = Store(tmp_path / "s.jsonl")
    a = s.add("邮件写短点", key="email.length")
    b = s.add("Emails under 120 words", key="email.length")
    c = s.add("邮件语气正式", key="email.tone")
    d = s.add("代码只给代码", key="code.explanation")
    bs = buckets(s.active())
    exact = [set(x.id for x in grp) for grp in bs]
    assert {a.id, b.id} in exact                       # exact key bucket
    assert all({c.id} != g and {d.id} != g for g in exact)  # singletons dropped


def test_no_duplicate_buckets_no_call(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: calls.append(1) or "[]")
    s = Store(tmp_path / "s.jsonl")
    s.add("邮件写短点", key="email.length")
    s.add("代码只给代码", key="code.explanation")
    out = run_consolidation(s)
    assert calls == [] and out["ops"] == []


def test_merge_lands_in_store(monkeypatch, tmp_path):
    s = Store(tmp_path / "s.jsonl")
    a = s.add("邮件写短点，120词以内", key="email.length")
    b = s.add("Emails under 120 words", key="email.length")

    def fake(model, system, user, max_tokens=1024):
        assert "[1]" in user and "[2]" in user
        return json.dumps([{"op": "merge", "targets": [1, 2],
                            "text": "Emails must stay under 120 words.",
                            "key": "email.length", "salience": 4}])
    monkeypatch.setattr(llm, "complete", fake)
    out = run_consolidation(s)
    assert out["store"]["applied"] == 1
    assert s.get(a.id).status == "retired" and s.get(b.id).status == "retired"
    assert any("120" in r.text for r in s.active())


def test_style_curation_retires_over_cap(monkeypatch, tmp_path):
    s = Store(tmp_path / "s.jsonl")
    rules = [s.add(f"style 规则 {i}", kind="style_rule", source="learned")
             for i in range(STYLE_RULE_CAP + 2)]

    def fake(model, system, user, max_tokens=1024):
        assert "style" in user.lower()
        return json.dumps([{"op": "retire", "target": 1, "salience": 4},
                           {"op": "retire", "target": 2, "salience": 4}])
    monkeypatch.setattr(llm, "complete", fake)
    run_consolidation(s)
    active_styles = [r for r in s.active() if r.kind == "style_rule"]
    assert len(active_styles) == STYLE_RULE_CAP
    assert s.get(rules[0].id).status == "retired"
