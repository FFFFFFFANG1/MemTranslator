import bench_archive.runner.judge as judge_mod
from bench_archive.runner.judge import judge


def test_yes_verdict(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: '{"verdict": "yes", "reason": "ok"}')
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is True and flag is False


def test_no_verdict(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: '{"verdict": "no", "reason": "missing"}')
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is False and flag is False


def test_garbage_fails_closed(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete", lambda *a, **k: "hmm, maybe?")
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is False and flag is True
