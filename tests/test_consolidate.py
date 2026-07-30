"""M3: consolidation — bucketing, merge, style curation. FakeLLM only."""
import json

import memtranslator.llm as llm
from memtranslator.config import CONSOLIDATE_ACTIVE, CONSOLIDATE_ADDS, STYLE_RULE_CAP
from memtranslator.consolidate import buckets, run_consolidation, should_consolidate
from memtranslator.schema import Requirement
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

    def fake(model, system, user, max_tokens=1024, **kw):
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

    def fake(model, system, user, max_tokens=1024, **kw):
        assert "style" in user.lower()
        return json.dumps([{"op": "retire", "target": 1, "salience": 4},
                           {"op": "retire", "target": 2, "salience": 4}])
    monkeypatch.setattr(llm, "complete", fake)
    run_consolidation(s)
    active_styles = [r for r in s.active() if r.kind == "style_rule"]
    assert len(active_styles) == STYLE_RULE_CAP
    assert s.get(rules[0].id).status == "retired"


def test_cross_key_overlap_clusters_near_duplicates():
    """Three same-obligation rules under different keys/buckets must still
    reach the merge prompt as one group (the measured miss: triplicate
    email maintenance-window rules invisible to key grouping)."""
    from memtranslator.consolidate import buckets
    a = Requirement(text="Emails must state the maintenance window start and end times.",
                    key="email.content", bucket="deliverables", created_at=1.0)
    b = Requirement(text="State the maintenance window and impact scope in emails.",
                    key="email.maintenance", bucket="output_contract", created_at=2.0)
    c = Requirement(text="Unrelated: keep commit subjects under 60 characters.",
                    key="commit.length", bucket="output_contract", created_at=3.0)
    groups = buckets([a, b, c])
    joined = [{r.id for r in g} for g in groups]
    assert any({a.id, b.id} <= g for g in joined)
    assert not any(c.id in g and len(g) > 1 for g in joined)


def test_overlap_groups_are_oldest_first():
    from memtranslator.consolidate import buckets
    newer = Requirement(text="Reports end with a summary table of findings.",
                        key="report.x", bucket="", created_at=9.0)
    older = Requirement(text="End every report with a findings summary table.",
                        key="report.y", bucket="", created_at=1.0)
    groups = buckets([newer, older])
    grp = next(g for g in groups if len(g) >= 2)
    assert grp[0].created_at <= grp[-1].created_at


def test_merge_losing_numeric_anchor_is_dropped():
    """A merge whose text paraphrases away a numeric cap must not land —
    sources stay live (E1 round-3 measured STATE loss from lossy merges)."""
    from memtranslator.consolidate import _drop_anchor_losing_merges
    a = Requirement(text="Keep summaries under 200 words.")
    b = Requirement(text="Summaries stay within a 200-word cap.")
    by_id = {a.id: a, b.id: b}
    lossy = [{"kind": "merge", "target_ids": [a.id, b.id],
              "text": "Keep summaries short."}]
    kept, flags = _drop_anchor_losing_merges(lossy, by_id)
    assert kept == [] and flags

    faithful = [{"kind": "merge", "target_ids": [a.id, b.id],
                 "text": "Keep summaries under 200 words."}]
    kept, flags = _drop_anchor_losing_merges(faithful, by_id)
    assert len(kept) == 1 and not flags


def test_merge_of_conflicting_numbers_cannot_pass_as_merge():
    from memtranslator.consolidate import _drop_anchor_losing_merges
    a = Requirement(text="Emails stay under 120 words.")
    b = Requirement(text="Emails stay under 78 words.")
    by_id = {a.id: a, b.id: b}
    merged = [{"kind": "merge", "target_ids": [a.id, b.id],
               "text": "Emails stay under 78 words."}]
    kept, flags = _drop_anchor_losing_merges(merged, by_id)
    assert kept == []          # 120 lost -> must go through conflict path
