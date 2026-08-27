"""M2: pipeline triggers — batch-full and idle-flush, zero-call property,
and the two channels batching independently."""
import json

import memtranslator.llm as llm
from memtranslator.config import BATCH_N, B_BATCH_N, FLUSH_IDLE_S
from memtranslator.pipeline import Pipeline
from memtranslator.schema import Requirement
from memtranslator.store import Store


def _pipe(tmp_path):
    return Pipeline(Store(tmp_path / "store.jsonl"))


def _fake_ops(monkeypatch, calls):
    def fake(model, system, user, max_tokens=1024, **kw):
        calls.append(user)
        if "SIGNALS-A:" in user:
            return json.dumps([{
                "decision": "candidate",
                "kind": "potential_new",
                "item": {"text": "Keep emails concise.",
                         "bucket": "output_contract",
                         "scope_mode": "scoped",
                         "applies_when": None,
                         "work_kinds": ["email"],
                         "key": "length.max", "confidence": 8},
                "change_candidate": None, "sources": [1]}])
        return json.dumps([{"case": 1, "action": "add", "targets": []}])
    monkeypatch.setattr(llm, "complete", fake)


def test_no_flush_below_batch(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    p.add_natural(["以后邮件写短点"], now=1000.0)
    assert p.maybe_flush(now=1000.0) is None
    assert calls == []


def test_plain_task_is_queued_without_lexical_screen(tmp_path):
    p = _pipe(tmp_path)

    assert p.add_natural(
        ["帮我给房东写封邮件催修暖气"], now=1000.0) == 1
    assert p._a == ["帮我给房东写封邮件催修暖气"]


def test_flush_at_batch_n(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    for i in range(BATCH_N):
        p.add_natural([f"以后第{i}类邮件都保持简短"], now=1000.0 + i)
    out = p.maybe_flush(now=1000.0 + BATCH_N)
    # candidate extraction + consolidation; kinds arrive with the candidate
    assert out is not None and len(calls) == 2
    assert out["store"]["applied"] == 1
    assert len(p.store.active()) == 1          # op landed in the store
    assert p.store.active()[0].kinds == ["email"]
    assert p.pending_count() == 0              # queue drained


def test_idle_flush(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    p.add_natural(["以后邮件写短点"], now=1000.0)
    assert p.maybe_flush(now=1000.0 + 60) is None
    out = p.maybe_flush(now=1000.0 + FLUSH_IDLE_S + 1)
    assert out is not None and len(calls) == 2


def _feedback(p, store, text, now):
    req = store.add(text)
    return p.add_feedback(
        [req.to_dict()],
        [{"old": "keep it short.", "new": "keep it very short."}], now)


def test_feedback_without_a_diff_is_never_queued(tmp_path):
    p = _pipe(tmp_path)
    req = p.store.add("Emails must stay under 120 words.")
    assert p.add_feedback([req.to_dict()], [], now=1000.0) is False
    assert p.add_feedback([], [{"op": "replace"}], now=1000.0) is False
    assert p.pending_count() == 0


def test_route_b_flushes_at_its_own_threshold(monkeypatch, tmp_path):
    calls = []

    def fake(model, system, user, max_tokens=1024, **kw):
        calls.append(user)
        return json.dumps([{"signal": n, "entry": 1, "op": "none"}
                           for n in range(1, B_BATCH_N + 1)])
    monkeypatch.setattr(llm, "complete", fake)
    p = _pipe(tmp_path)
    for i in range(B_BATCH_N - 1):
        _feedback(p, p.store, f"rule {i}", now=1000.0 + i)
    assert p.maybe_flush(now=1000.0) is None       # below B_BATCH_N
    _feedback(p, p.store, "rule last", now=1000.0)
    out = p.maybe_flush(now=1000.0)
    assert out is not None and len(calls) == 1     # one call for the batch
    assert p.pending_count("b") == 0


def test_route_b_update_edits_the_attributed_entry(monkeypatch, tmp_path):
    p = _pipe(tmp_path)
    req = p.store.add("Emails must stay under 120 words.")
    p.add_feedback([req.to_dict()], [{
        "old": "keep it under 120 words.",
        "new": "keep it under 80 words."}],
        now=1000.0)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(
        [{"signal": 1, "entry": 1, "op": "update",
          "text": "Keep emails under 80 words."}]))
    out = p.maybe_flush(now=1000.0, force=True)
    assert out["b"]["ops"] == [{"kind": "update", "target_id": req.id,
                                "text": "Keep emails under 80 words."}]
    # same entry, corrected in place — no heir, no supersede chain
    assert [r.text for r in p.store.active()] == ["Keep emails under 80 words."]
    assert p.store.get(req.id).text == "Keep emails under 80 words."


def test_route_a_queue_does_not_trip_the_route_b_threshold(monkeypatch,
                                                           tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    for i in range(B_BATCH_N):
        p.add_natural([f"以后第{i}类邮件都保持简短"], now=1000.0 + i)
    assert p.maybe_flush(now=1000.0 + B_BATCH_N) is None
    assert calls == []


def test_empty_queue_never_calls(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    assert p.maybe_flush(now=99999.0) is None
    assert calls == []


def test_concurrent_capture_is_not_erased_by_an_in_flight_flush(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from memtranslator import pipeline

    started, release, adding = Event(), Event(), Event()

    def extract(messages, _items):
        assert messages == ["first message"]
        started.set()
        assert release.wait(2)
        return {"ops": [], "flags": []}

    monkeypatch.setattr(pipeline, "run_a_extraction", extract)
    p = _pipe(tmp_path)
    p.add_natural(["first message"], now=0)

    def add_next():
        adding.set()
        return p.add_natural(["second message"], now=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        flush = pool.submit(p.maybe_flush, 0, force=True)
        try:
            assert started.wait(2)
            add = pool.submit(add_next)
            assert adding.wait(2)
        finally:
            release.set()
        flush.result(timeout=2)
        assert add.result(timeout=2) == 1
    assert p._a == ["second message"]
