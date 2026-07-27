"""The six-bucket taxonomy landing in the product (docs/2026-07-26-bucket-taxonomy.md).

A bucket says WHICH PART of the request a requirement rewrites; scope says when
it applies; status says whether it still counts. The controlled top level is
what the free-form `key` never gave us: `email.length` and `mail.length` were
invented per entry by the model and never bucketed together for dedup.
"""
import json

import memtranslator.llm as llm
from memtranslator.extraction import parse_ops
from memtranslator.schema import BUCKETS, Requirement
from memtranslator.store import Store


# ---------- schema ----------

def test_new_fields_default_and_roundtrip(tmp_path):
    s = Store(tmp_path / "s.jsonl")
    r = s.add("邮件不超过120词")
    assert (r.bucket, r.binding, r.polarity, r.evidence_id) == ("", "", "", "")
    assert Requirement.from_dict(r.to_dict()).to_dict() == r.to_dict()


def test_v1_records_load_without_migration():
    """Records written before the taxonomy must load untouched — the store is
    append-only and there is no rewrite pass."""
    v1 = {"id": "req-old", "text": "旧条目", "status": "active",
          "kind": "requirement", "key": "email.length", "scope": {},
          "strength": 2, "salience": 4, "supersedes": None,
          "source": "learned", "created_at": 1.0, "updated_at": 2.0}
    r = Requirement.from_dict(v1)
    assert r.bucket == "" and r.binding == "" and r.polarity == ""
    assert r.key == "email.length" and r.strength == 2   # untouched


def test_bucket_is_validated(tmp_path):
    s = Store(tmp_path / "s.jsonl")
    s.add("x", bucket="output_contract")
    try:
        s.add("y", bucket="domain_criteria")     # deleted on 2026-07-26
        raise AssertionError("retired bucket must be rejected")
    except ValueError:
        pass


def test_domain_criteria_is_gone():
    assert "domain_criteria" not in BUCKETS
    assert set(BUCKETS) == {"task_goal", "reasoning_policy", "deliverables",
                            "output_contract", "communication_style",
                            "execution_policy"}


# ---------- extraction output ----------

def test_bucket_and_polarity_survive_parsing():
    ops, flags = parse_ops(json.dumps([
        {"op": "new", "text": "调研结论先行", "bucket": "output_contract",
         "polarity": "require", "key": "research.order", "salience": 4},
    ]), [])
    assert ops[0]["bucket"] == "output_contract"
    assert ops[0]["polarity"] == "require"
    assert flags == []


def test_unknown_bucket_is_dropped_not_guessed():
    ops, flags = parse_ops(json.dumps([
        {"op": "new", "text": "x", "bucket": "vibes", "salience": 4},
    ]), [])
    assert ops == [] and flags


def test_atomisation_shares_one_evidence_id():
    """One utterance, several rules, independent lifecycles — otherwise a
    later "这次不要表格" cannot be resolved against a compound entry."""
    ops, _ = parse_ops(json.dumps([
        {"op": "new", "text": "论文分析用中文", "bucket": "output_contract",
         "salience": 4, "evidence_id": "ev-1"},
        {"op": "new", "text": "先给比较表", "bucket": "output_contract",
         "salience": 4, "evidence_id": "ev-1"},
        {"op": "new", "text": "明确判断 novelty", "bucket": "deliverables",
         "salience": 4, "evidence_id": "ev-1"},
    ]), [])
    assert len(ops) == 3
    assert {o["evidence_id"] for o in ops} == {"ev-1"}
    assert {o["bucket"] for o in ops} == {"output_contract", "deliverables"}


def test_ops_land_in_the_store_with_their_bucket(tmp_path):
    s = Store(tmp_path / "s.jsonl")
    s.apply_ops([{"kind": "new", "text": "结论先行",
                  "bucket": "output_contract", "polarity": "require",
                  "evidence_id": "ev-9", "salience": 4}])
    r = s.active()[0]
    assert r.bucket == "output_contract" and r.polarity == "require"
    assert r.evidence_id == "ev-9" and r.source == "learned"


# ---------- consolidation bucketing ----------

def test_dedup_never_crosses_buckets(tmp_path):
    """Two rules can share a facet word and still be different rules —
    "cite sources" as a reasoning standard is not "cite in APA" as a format."""
    from memtranslator.consolidate import buckets as group
    s = Store(tmp_path / "s.jsonl")
    a = s.add("引用要给出处", bucket="reasoning_policy", key="cite.sourcing")
    b = s.add("引用查证到一手来源", bucket="reasoning_policy", key="cite.sourcing")
    c = s.add("引用用 APA 格式", bucket="output_contract", key="cite.format")
    groups = [set(x.id for x in g) for g in group(s.active())]
    assert {a.id, b.id} in groups
    assert not any(c.id in g for g in groups)


def test_same_key_different_bucket_stays_apart(tmp_path):
    from memtranslator.consolidate import buckets as group
    s = Store(tmp_path / "s.jsonl")
    s.add("权衡时算上 latency", bucket="reasoning_policy", key="tradeoff.axes")
    s.add("给一张各维度对比表", bucket="deliverables", key="tradeoff.axes")
    assert group(s.active()) == []      # same key, different bucket → no merge


# ---------- the noop-bias conflict task_goal creates ----------

def test_prompt_lets_task_goal_complete_a_vague_request():
    """translate rule 1 prefers noop when a request is underspecified, but
    completing exactly those requests is what task_goal is FOR. The prompt has
    to carve the exception or the bucket can never fire in production."""
    from memtranslator.translate import TRANSLATOR_SYSTEM
    low = TRANSLATOR_SYSTEM.lower()
    assert "supply that task verb" in low
    assert "underspecified" in low        # the original bias is still stated
