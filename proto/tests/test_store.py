import json

from memtranslator import MemoryEntry, MemoryStore, Provenance, Scope


def entry(req="Always run the linter.", cond="the user asks for code changes", **kw):
    return MemoryEntry(requirement=req, scope=Scope(condition=cond, keywords=kw.pop("keywords", ["lint"])), **kw)


def test_add_and_roundtrip(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    e = store.add(entry())
    reloaded = MemoryStore(tmp_path / "mem.jsonl")
    assert reloaded.get(e.mid).requirement == "Always run the linter."
    assert reloaded.get(e.mid).scope.condition == "the user asks for code changes"


def test_reinforce_bumps_strength_and_appends_provenance(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    e = store.add(entry())
    store.reinforce(e.mid, Provenance(session_id="s2", turn=3, signal="repeated_requirement", quote="lint it"))
    reloaded = MemoryStore(tmp_path / "mem.jsonl").get(e.mid)
    assert reloaded.strength == 2
    assert [p.session_id for p in reloaded.provenance] == ["s2"]


def test_supersede_links_chain_and_hides_old_from_active(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    old = store.add(entry(req="Write short emails."))
    new = store.supersede(old.mid, entry(req="Write detailed emails."))
    reloaded = MemoryStore(tmp_path / "mem.jsonl")
    assert reloaded.get(old.mid).status == "superseded"
    assert reloaded.get(old.mid).superseded_by == new.mid
    assert reloaded.get(new.mid).supersedes == [old.mid]
    assert [e.mid for e in reloaded.active()] == [new.mid]


def test_retire_and_expiry_filter(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    kept = store.add(entry())
    gone = store.add(entry(req="Temporary rule."))
    store.retire(gone.mid)
    expired = store.add(entry(req="Expired rule."))
    expired.expires_at = "2000-01-01T00:00:00+00:00"
    store._append(expired)
    assert {e.mid for e in store.active()} == {kept.mid}


def test_append_only_file_never_shrinks_and_survives_torn_line(tmp_path):
    path = tmp_path / "mem.jsonl"
    store = MemoryStore(path)
    e = store.add(entry())
    store.reinforce(e.mid, Provenance(session_id="s", turn=0, signal="repeated_requirement", quote="q"))
    lines = path.read_text().splitlines()
    assert len(lines) == 2  # one snapshot per mutation, nothing rewritten
    path.write_text(path.read_text() + '{"mid": "m-torn", "requirement"')
    reloaded = MemoryStore(path)
    assert reloaded.get(e.mid).strength == 2  # torn tail skipped, state intact


def test_mark_applied_writes_back(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    e = store.add(entry())
    store.mark_applied([e.mid, "m-unknown"])
    assert MemoryStore(tmp_path / "mem.jsonl").get(e.mid).last_applied_at is not None


def test_recall_prefers_keyword_hits_then_strength(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    weak = store.add(entry(req="About papers.", keywords=["paper", "review"]))
    strong = store.add(entry(req="About papers, stronger.", keywords=["paper", "review"]))
    store.reinforce(strong.mid, Provenance(session_id="s", turn=0, signal="repeated_requirement", quote="q"))
    off_topic = store.add(entry(req="About emails.", keywords=["email"]))
    got = store.recall("please review this paper", k=2)
    assert [e.mid for e in got] == [strong.mid, weak.mid]
    assert off_topic.mid not in {e.mid for e in got}


def test_quarantine_appends_jsonl(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    store.quarantine("raw-llm-garbage", stage="extract", reason="test")
    rows = [json.loads(l) for l in store.quarantine_path.read_text().splitlines()]
    assert rows[0]["stage"] == "extract" and rows[0]["raw"] == "raw-llm-garbage"
