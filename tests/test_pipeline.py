"""M2: pipeline triggers — batch-full and idle-flush, zero-call property."""
import json

import memtranslator.llm as llm
from memtranslator.config import BATCH_N, FLUSH_IDLE_S
from memtranslator.pipeline import Pipeline
from memtranslator.store import Store


def _pipe(tmp_path):
    return Pipeline(Store(tmp_path / "store.jsonl"))


def _fake_ops(monkeypatch, calls):
    def fake(model, system, user, max_tokens=1024, **kw):
        calls.append(user)
        return json.dumps([{"op": "new", "text": "学到的规则",
                            "key": "email.length", "salience": 4}])
    monkeypatch.setattr(llm, "complete", fake)


def test_no_flush_below_batch(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    p.add_natural(["以后邮件写短点"], now=1000.0)
    assert p.maybe_flush(now=1000.0) is None
    assert calls == []


def test_flush_at_batch_n(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    for i in range(BATCH_N):
        p.add_natural([f"以后规则{i}"], now=1000.0 + i)
    out = p.maybe_flush(now=1000.0 + BATCH_N)
    assert out is not None and len(calls) == 1
    assert out["store"]["applied"] == 1
    assert len(p.store.active()) == 1          # op landed in the store
    assert p.pending_count() == 0              # queue drained


def test_idle_flush(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    p.add_natural(["以后邮件写短点"], now=1000.0)
    assert p.maybe_flush(now=1000.0 + 60) is None
    out = p.maybe_flush(now=1000.0 + FLUSH_IDLE_S + 1)
    assert out is not None and len(calls) == 1


def test_diff_candidates_join_the_batch(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    p.add_diff({"raw": "r", "polished": "p", "final": "f",
                "applied": [], "survival": "mixed"}, now=1000.0)
    out = p.maybe_flush(now=1000.0 + FLUSH_IDLE_S + 1)
    assert out is not None and len(calls) == 1


def test_empty_queue_never_calls(monkeypatch, tmp_path):
    calls = []
    _fake_ops(monkeypatch, calls)
    p = _pipe(tmp_path)
    assert p.maybe_flush(now=99999.0) is None
    assert calls == []
