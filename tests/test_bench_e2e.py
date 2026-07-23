import bench.runner.run_e2e as re2e
from bench.runner.providers import NullProvider


class _LearnsRound4:
    """Fake provider: extracts everything it has seen on the first flush."""
    def extract(self, events, existing):
        have = {r.text for r in existing}
        out = []
        for e in events:
            if e["type"] == "natural" and e["text"] not in have:
                out.append({"kind": "new", "target_id": None, "text": e["text"]})
        return out


def _persona():
    rounds = [{"n": i, "task": f"task {i}", "applicable": [0],
               "final": f"task {i} + constraint",
               "natural_correction": "以后都要X" if i == 1 else None}
              for i in range(1, 17)]
    return {"id": "p", "requirements": ["都要X"], "rounds": rounds}


def test_null_provider_scores_zero(monkeypatch):
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    r = re2e.run_persona(_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 0.0 and r["pass"] is False


def test_perfect_carry_scores_one(monkeypatch):
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (True, False))
    monkeypatch.setattr(re2e, "_polish", lambda text, reqs: {
        "decision": "apply", "polished": text + " polished",
        "applied_ids": [], "parse_error": False, "latency_ms": 0})
    r = re2e.run_persona(_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 1.0 and r["pass"] is True


def test_learning_provider_updates_store(monkeypatch):
    seen_sizes = []
    def fake_polish(text, reqs):
        seen_sizes.append(len(reqs))
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}
    monkeypatch.setattr(re2e, "_polish", fake_polish)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    re2e.run_persona(_persona(), _LearnsRound4(), flush_every=4)
    assert seen_sizes[0] == 0 and seen_sizes[-1] >= 1   # store grew mid-run


def test_dir_hash_snapshot(tmp_path, monkeypatch):
    import bench.runner.report as report
    monkeypatch.setattr(report, "RESULTS", tmp_path / "results")
    d = tmp_path / "personas"
    d.mkdir()
    (d / "a.json").write_text("{}")
    out = report.write_snapshot("E", str(d), [
        {"id": "p", "category": "persona", "pass": True}])
    import json
    snap = json.loads(out.read_text())
    assert len(snap["cases_hash"]) == 12
