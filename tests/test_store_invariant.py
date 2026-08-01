"""Heir-liveness invariant (2026-07-31): no active rule dies without a live
heir or explicit withdrawal evidence; version chains pop when an heir dies.
Measured motivation: a correct cap was superseded by a mis-extracted rule
which then died, leaving the facet with nothing active."""
import sys

sys.path.insert(0, "src")

from memtranslator.store import Store


def _mk(tmp_path):
    return Store(tmp_path / "s.jsonl")


def test_contradict_records_reverse_pointer(tmp_path):
    s = _mk(tmp_path)
    old = s.add("emails under 120 words")
    s.apply_ops([{"kind": "contradict", "target_id": old.id,
                  "text": "emails under 80 words"}])
    assert old.status == "retired"
    heir = next(r for r in s.active())
    assert old.superseded_by == heir.id and heir.supersedes == old.id


def test_heirless_retire_pops_ancestor(tmp_path):
    s = _mk(tmp_path)
    a = s.add("keep it to 11 sentences max")
    s.apply_ops([{"kind": "contradict", "target_id": a.id,
                  "text": "write at least 17 sentences"}])
    wrong = next(r for r in s.active())
    s.apply_ops([{"kind": "retire", "target_id": wrong.id}])
    # the mis-extracted heir died without withdrawal → ancestor pops back
    assert a.status == "active" and a.superseded_by is None
    assert wrong.status == "retired"


def test_withdrawal_retire_terminates_chain(tmp_path):
    s = _mk(tmp_path)
    a = s.add("keep it to 11 sentences max")
    s.apply_ops([{"kind": "contradict", "target_id": a.id,
                  "text": "keep it to 9 sentences max"}])
    heir = next(r for r in s.active())
    s.apply_ops([{"kind": "retire", "target_id": heir.id,
                  "withdrawal": True}])
    # explicit user withdrawal kills the lineage — no resurrection
    assert a.status == "retired" and not s.active()


def test_retire_with_heir_does_not_pop(tmp_path):
    s = _mk(tmp_path)
    a = s.add("keep replies short")
    s.apply_ops([{"kind": "contradict", "target_id": a.id,
                  "text": "keep replies under 50 words"}])
    mid = next(r for r in s.active())
    winner = s.add("keep replies under 30 words")
    s.apply_ops([{"kind": "retire", "target_id": mid.id,
                  "heir_id": winner.id}])
    # conflict resolution with a live winner: facet is governed, no pop
    assert a.status == "retired"
    assert mid.superseded_by == winner.id
    assert [r.id for r in s.active()] == [winner.id]


def test_merge_records_heir_on_every_source(tmp_path):
    s = _mk(tmp_path)
    x = s.add("emails under 120 words")
    y = s.add("keep emails under 120 words please")
    s.apply_ops([{"kind": "merge", "target_ids": [x.id, y.id],
                  "text": "emails under 120 words"}])
    merged = next(r for r in s.active())
    assert x.superseded_by == merged.id and y.superseded_by == merged.id


def test_pop_survives_reload(tmp_path):
    s = _mk(tmp_path)
    a = s.add("keep it to 11 sentences max")
    s.apply_ops([{"kind": "contradict", "target_id": a.id,
                  "text": "write at least 17 sentences"}])
    wrong = next(r for r in s.active())
    s.apply_ops([{"kind": "retire", "target_id": wrong.id}])
    reloaded = Store(tmp_path / "s.jsonl")
    texts = {r.text for r in reloaded.active()}
    assert texts == {"keep it to 11 sentences max"}


def test_heirless_merge_death_unmerges_sources(tmp_path):
    s = _mk(tmp_path)
    x = s.add("single quotes for module names", key="doc.naming")
    y = s.add("identifiers use ASCII only", key="code.identifiers")
    s.apply_ops([{"kind": "merge", "target_ids": [x.id, y.id],
                  "text": "module quotes and ASCII identifiers"}])
    merged = next(r for r in s.active())
    s.apply_ops([{"kind": "retire", "target_id": merged.id}])
    texts = {r.text for r in s.active()}
    assert texts == {"single quotes for module names",
                     "identifiers use ASCII only"}
