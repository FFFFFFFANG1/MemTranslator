"""M0: v1 schema fields + mechanical strength rules + op application."""
import json

from memtranslator.schema import Requirement
from memtranslator.store import Store


def test_new_fields_defaults_and_roundtrip(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("邮件不超过120词")
    assert (r.kind, r.key, r.scope, r.strength, r.confidence,
            r.sources, r.supersedes, r.source) == (
        "requirement", "", {}, 1, 0, [], None, "manual")
    back = Requirement.from_dict(r.to_dict())
    assert back.to_dict() == r.to_dict()


def test_from_dict_tolerates_v0_records():
    v0 = {"id": "req-old00001", "text": "旧条目", "status": "active",
          "created_at": 1.0, "updated_at": 2.0}
    r = Requirement.from_dict(v0)
    assert r.kind == "requirement" and r.strength == 1 and r.scope == {}
    assert r.source == "manual" and r.supersedes is None


def test_add_learned_with_metadata(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("代码只给代码", kind="requirement", key="code.explanation",
              scope={"task": "code"}, source="learned", confidence=8,
              sources=["以后代码只给代码"])
    assert r.key == "code.explanation" and r.source == "learned"
    # Legacy scope.task genre migrates into kinds on write.
    assert r.kinds == ["code"] and r.scope == {}
    reloaded = Store(tmp_path / "store.jsonl").get(r.id)
    assert reloaded.kinds == ["code"] and reloaded.scope == {}
    assert reloaded.confidence == 8
    assert reloaded.sources == ["以后代码只给代码"]


def test_legacy_salience_maps_into_confidence(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("x", salience=4)
    assert r.confidence == 8
    legacy = Requirement.from_dict({
        "id": "req-legacy", "text": "旧", "status": "active",
        "salience": 5, "created_at": 1.0, "updated_at": 1.0})
    assert legacy.confidence == 10


def test_bump_strength_and_auto_retire(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("x")
    s.bump_strength([r.id], +1)
    assert s.get(r.id).strength == 2
    s.bump_strength([r.id], -1)
    s.bump_strength([r.id], -1)
    s.bump_strength([r.id], -1)
    s.bump_strength([r.id], -1)          # 2→1→0→-1→-2
    assert s.get(r.id).strength == -2
    assert s.get(r.id).status == "retired"          # ≤-2 → auto retire


def test_apply_ops_new_and_reinforce(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("周报用 bullet")
    before = s.get(r.id).strength
    out = s.apply_ops([
        {"kind": "new", "text": "邮件写短", "key": "email.length",
         "scope": {}, "salience": 4},
        {"kind": "reinforce", "target_id": r.id},
    ])
    assert len(s.active()) == 2
    assert s.get(r.id).strength == before + 1
    added = [x for x in s.active() if x.text == "邮件写短"][0]
    assert added.source == "learned" and added.key == "email.length"
    assert out["applied"] == 2 and out["skipped"] == []


def test_apply_ops_contradict_supersedes(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    old = s.add("邮件不超过120词")
    s.apply_ops([{"kind": "contradict", "target_id": old.id,
                  "text": "邮件不超过80词", "key": "email.length"}])
    assert s.get(old.id).status == "retired"
    new = [x for x in s.active() if x.text == "邮件不超过80词"][0]
    assert new.supersedes == old.id


def test_apply_ops_retire_and_merge(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    a = s.add("邮件写短点，120词以内")
    b = s.add("Emails under 120 words")
    c = s.add("代码只给代码")
    s.apply_ops([{"kind": "retire", "target_id": c.id}])
    assert s.get(c.id).status == "retired"
    s.apply_ops([{"kind": "merge", "target_ids": [a.id, b.id],
                  "text": "Emails must stay under 120 words.",
                  "key": "email.length"}])
    assert s.get(a.id).status == "retired"
    assert s.get(b.id).status == "retired"
    merged = [x for x in s.active() if "120" in x.text]
    assert len(merged) == 1 and merged[0].supersedes == a.id


def test_apply_ops_unknown_target_skipped_not_fatal(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    out = s.apply_ops([{"kind": "reinforce", "target_id": "req-nope"},
                       {"kind": "new", "text": "有效条目"}])
    assert out["applied"] == 1 and len(out["skipped"]) == 1
    assert len(s.active()) == 1


def test_style_rule_kind_persisted(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("保留用户原句式，约束以从句追加", kind="style_rule",
              source="learned")
    reloaded = Store(tmp_path / "store.jsonl")
    assert reloaded.get(r.id).kind == "style_rule"
    raw = (tmp_path / "store.jsonl").read_text().splitlines()
    assert json.loads(raw[-1])["kind"] == "style_rule"


def test_feedback_retire_requires_two_votes_and_survives_reload(tmp_path):
    """One dropped constraint is not a withdrawal: an edit can leave a rule
    out for reasons that have nothing to do with wanting it gone."""
    path = tmp_path / "store.jsonl"
    s = Store(path)
    r = s.add("Emails under 120 words")
    s.apply_feedback_ops([{"kind": "retire", "target_id": r.id}])
    assert s.get(r.id).status == "active"
    assert Store(path).get(r.id).feedback_score == -1
    s.apply_feedback_ops([{"kind": "retire", "target_id": r.id}])
    assert s.get(r.id).feedback_score == -2
    assert s.get(r.id).status == "retired"


def test_feedback_update_refines_in_place_and_clears_negative_score(tmp_path):
    s = Store(tmp_path / "store.jsonl")
    r = s.add("Emails under 120 words")
    s.apply_feedback_ops([{"kind": "retire", "target_id": r.id}])
    out = s.apply_feedback_ops([{"kind": "update", "target_id": r.id,
                                 "text": "Emails under 80 words"}])
    assert out["applied"] == 1
    # same id, no heir: the user corrected this rule, they did not add one
    assert s.get(r.id).text == "Emails under 80 words"
    assert s.get(r.id).supersedes is None and len(s.active()) == 1
    assert s.get(r.id).feedback_score == 0


def test_feedback_ops_skip_entries_route_a_already_retired(tmp_path):
    """The two channels flush independently, so B can judge an entry A just
    replaced. The executor is where that settles — a retired entry takes no
    more feedback."""
    s = Store(tmp_path / "store.jsonl")
    r = s.add("Emails under 120 words")
    s.apply_ops([{"kind": "contradict", "target_id": r.id,
                  "text": "Emails under 80 words"}])
    out = s.apply_feedback_ops([{"kind": "update", "target_id": r.id,
                                 "text": "Emails under 60 words"}])
    assert out["applied"] == 0 and len(out["skipped"]) == 1
    assert [x.text for x in s.active()] == ["Emails under 80 words"]
