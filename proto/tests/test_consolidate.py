import json

from memtranslator import FakeLLM, MemoryEntry, MemoryStore, Scope
from memtranslator.consolidate import consolidate
from memtranslator.schema import Candidate


def cand(req="New requirement.", **over):
    d = dict(requirement=req, scope_condition="the user asks for X",
             quote="do X please", signal="explicit_instruction", keywords=["x"])
    d.update(over)
    return Candidate(**d)


def existing(store, req="Old requirement."):
    return store.add(MemoryEntry(requirement=req, scope=Scope(condition="the user asks for X")))


def _resp(ops):
    return json.dumps({"ops": ops})


def test_add_creates_entry(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    consolidate(FakeLLM([_resp([{"candidate_idx": 0, "op": "ADD"}])]), [cand()], [], store, "s1")
    assert [e.requirement for e in store.active()] == ["New requirement."]


def test_reinforce_targets_existing(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    old = existing(store)
    consolidate(FakeLLM([_resp([{"candidate_idx": 0, "op": "REINFORCE", "target_mid": old.mid}])]),
                [cand()], [old], store, "s1")
    assert store.get(old.mid).strength == 2
    assert len(store.active()) == 1


def test_supersede_chains_and_merges_provenance(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    old = existing(store, req="Write short emails.")
    consolidate(FakeLLM([_resp([{"candidate_idx": 0, "op": "SUPERSEDE", "target_mid": old.mid,
                                 "merged_requirement": "Write detailed emails."}])]),
                [cand(req="Emails should be detailed.")], [old], store, "s1")
    active = store.active()
    assert [e.requirement for e in active] == ["Write detailed emails."]
    assert active[0].supersedes == [old.mid]
    assert store.get(old.mid).status == "superseded"
    # old provenance carried forward + the candidate's own
    assert len(active[0].provenance) == len(old.provenance) + 1


def test_drop_writes_nothing(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    applied = consolidate(FakeLLM([_resp([{"candidate_idx": 0, "op": "DROP", "reason": "one-off"}])]),
                          [cand()], [], store, "s1")
    assert store.active() == []
    assert applied[0][1].op == "DROP"


def test_unknown_target_degrades_to_add(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    consolidate(FakeLLM([_resp([{"candidate_idx": 0, "op": "REINFORCE", "target_mid": "m-ghost"}])]),
                [cand()], [], store, "s1")
    assert [e.requirement for e in store.active()] == ["New requirement."]


def test_unparseable_output_drops_whole_batch_to_quarantine(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    applied = consolidate(FakeLLM(["let me think about these ops..."]), [cand()], [], store, "s1")
    assert applied == [] and store.active() == []
    assert "whole batch dropped" in store.quarantine_path.read_text()


def test_unmentioned_candidate_is_implicit_drop(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    applied = consolidate(FakeLLM([_resp([{"candidate_idx": 0, "op": "ADD"}])]),
                          [cand(), cand(req="Never mentioned.")], [], store, "s1")
    assert [e.requirement for e in store.active()] == ["New requirement."]
    assert len(applied) == 1


def test_empty_candidates_no_llm_call(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    llm = FakeLLM([])
    assert consolidate(llm, [], [], store, "s1") == []
    assert llm.calls == []
