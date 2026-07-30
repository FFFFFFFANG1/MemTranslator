"""Consolidation op sanitizer (_sanitize_ops): mechanical guards against
over-merging and over-retiring, measured on chained-store replays where
correctly-learned rules were consolidated away."""
import sys

sys.path.insert(0, "src")

from memtranslator.consolidate import _sanitize_ops
from memtranslator.schema import Requirement


def _reqs(*texts):
    return {r.id: r for r in (Requirement(text=t) for t in texts)}


def test_disjoint_merge_dropped():
    by_id = _reqs("enable automatic backups every 6 hours",
                  "send notifications via slack")
    a, b = by_id.keys()
    ops = [{"kind": "merge", "target_ids": [a, b],
            "text": "backups every 6 hours and slack notifications"}]
    out, flags = _sanitize_ops(ops, by_id)
    assert out == [] and any("disjoint" in f for f in flags)


def test_overlapping_merge_kept():
    by_id = _reqs("emails must stay under 120 words",
                  "keep emails under 120 words please")
    a, b = by_id.keys()
    ops = [{"kind": "merge", "target_ids": [a, b],
            "text": "emails must stay under 120 words"}]
    out, _ = _sanitize_ops(ops, by_id)
    assert len(out) == 1


def test_redundant_retire_of_merged_source_dropped():
    by_id = _reqs("emails under 120 words", "keep emails under 120 words")
    a, b = by_id.keys()
    ops = [{"kind": "merge", "target_ids": [a, b],
            "text": "emails under 120 words"},
           {"kind": "retire", "target_id": a}]
    out, flags = _sanitize_ops(ops, by_id)
    assert [o["kind"] for o in out] == ["merge"]
    assert any("redundant retire" in f for f in flags)


def test_contentless_retire_dropped():
    by_id = _reqs("keep every bullet point under 17 words",
                  "give temperatures in celsius")
    a, b = by_id.keys()
    ops = [{"kind": "retire", "target_id": a}]     # nothing survives with
    out, flags = _sanitize_ops(ops, by_id)         # overlapping content
    assert out == [] and any("contentless" in f for f in flags)


def test_conflict_retire_kept():
    by_id = _reqs("keep emails under 120 words",
                  "keep emails under 80 words")
    a, b = by_id.keys()
    ops = [{"kind": "retire", "target_id": a}]     # newer conflicting cap
    out, _ = _sanitize_ops(ops, by_id)             # survives → legit retire
    assert len(out) == 1
