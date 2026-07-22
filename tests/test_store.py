from memtranslator.store import EventLog, Store


def test_add_and_list(tmp_path):
    store = Store(tmp_path / "s.jsonl")
    a = store.add("Emails under 120 words.")
    b = store.add("Code without explanations.")
    assert [r.id for r in store.list()] == [a.id, b.id]
    assert all(r.status == "active" for r in store.list())


def test_retire_and_active_filter(tmp_path):
    store = Store(tmp_path / "s.jsonl")
    a = store.add("A")
    store.add("B")
    store.update(a.id, status="retired")
    assert [r.text for r in store.active()] == ["B"]
    assert len(store.list()) == 2


def test_persistence_last_record_wins(tmp_path):
    path = tmp_path / "s.jsonl"
    store = Store(path)
    a = store.add("original")
    store.update(a.id, text="edited")
    store.update(a.id, status="retired")

    reloaded = Store(path)
    req = reloaded.get(a.id)
    assert req.text == "edited"
    assert req.status == "retired"
    # append-only: three records on disk, one live item
    assert len(path.read_text().splitlines()) == 3
    assert len(reloaded.list()) == 1


def test_empty_text_rejected(tmp_path):
    store = Store(tmp_path / "s.jsonl")
    try:
        store.add("   ")
        assert False, "should have raised"
    except ValueError:
        pass


def test_event_log_roundtrip(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    log.append("translate", {"translate_id": "tr-1", "decision": "noop"})
    log.append("send", {"text": "hi"})
    events = log.read_all()
    assert [e["kind"] for e in events] == ["translate", "send"]
    assert all("at" in e for e in events)
