import bench.suites.run_e2e as re2e
from bench.suites.providers import NullProvider


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


def test_seed_absorbs_first_finals_before_translate(monkeypatch):
    """First five finals plus seed naturals; translate starts at 6."""
    seen = []
    polish_ns = []

    class _Spy:
        def extract(self, events, existing):
            seen.append([(e.get("type"), e.get("text")) for e in events])
            return [{"kind": "new", "channel": "a", "text": "都要X"}]

    def polish(text, reqs, context=None):
        polish_ns.append(text)
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}

    monkeypatch.setattr(re2e, "_polish", polish)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    re2e.run_persona(_persona(), _Spy(), flush_every=4, seed_rounds=5)
    seed = []
    for i in range(1, 6):
        seed.append(("natural", f"task {i} + constraint"))
        if i == 1:
            seed.append(("natural", "以后都要X"))
    assert seen[0] == seed
    assert polish_ns == [f"task {i}" for i in range(6, 17)]


def test_miss_without_applied_ids_skips_b_signal(monkeypatch):
    """B requires attributed entries; a noop translate must not invent a
    route-B event from polished→final alone."""
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    monkeypatch.setattr(re2e, "_polish", lambda text, reqs, context=None: {
        "decision": "noop", "polished": None, "applied_ids": [],
        "parse_error": False, "latency_ms": 0})

    seen = []

    class _Spy:
        def extract(self, events, existing):
            seen.append([e.get("type") for e in events])
            return []

    persona = {"id": "p", "requirements": ["规则"],
               "rounds": [{"n": i, "task": f"t{i}", "applicable": [0],
                           "final": f"t{i} + x",
                           "natural_correction": "要X" if i == 6 else None}
                          for i in range(1, 9)]}
    re2e.run_persona(persona, _Spy(), flush_every=4, seed_rounds=5)
    # Seed flush first (5 naturals), then scored flush at n=8: A-only
    # (natural_correction on r6 + final on each miss), never edited_diff.
    assert seen[0] == ["natural"] * 5
    assert seen[1] == ["natural"] * 4
    assert "edited_diff" not in seen[1]


def test_b_update_goes_through_feedback_ops(monkeypatch, tmp_path):
    monkeypatch.setattr(re2e, "RUN_DIR", tmp_path)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))

    store_box = {}

    def polish(text, reqs, context=None):
        if reqs:
            store_box["id"] = reqs[0].id
            return {"decision": "apply", "polished": text + " woven",
                    "applied_ids": [reqs[0].id], "parse_error": False,
                    "latency_ms": 0}
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}

    monkeypatch.setattr(re2e, "_polish", polish)

    class _TeachThenUpdate:
        def __init__(self):
            self.n = 0

        def extract(self, events, existing):
            self.n += 1
            if self.n == 1:
                return [{"kind": "new", "channel": "a", "text": "都要X"}]
            # Second flush: B update on the woven entry
            return [{"kind": "update", "channel": "b",
                     "target_id": existing[0].id, "text": "都要Y"}]

    persona = {"id": "p", "requirements": ["都要X"],
               "rounds": [
                   {"n": i, "task": f"t{i}", "applicable": [0],
                    "final": f"t{i}+Y", "natural_correction": None}
                   for i in range(1, 9)
               ]}
    r = re2e.run_persona(persona, _TeachThenUpdate(), flush_every=4,
                         seed_rounds=5)
    assert r["store_final"]["active"] == 1
    assert r["peak_active"] == 1


def test_null_provider_scores_zero(monkeypatch):
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    r = re2e.run_persona(_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 0.0 and r["pass"] is False


def test_perfect_carry_scores_one(monkeypatch):
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (True, False))
    monkeypatch.setattr(re2e, "_polish", lambda text, reqs, context=None: {
        "decision": "apply", "polished": text + " polished",
        "applied_ids": [], "parse_error": False, "latency_ms": 0})
    r = re2e.run_persona(_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 1.0 and r["pass"] is True
    assert all(row["n"] >= 6 for row in r["rounds"])


def test_learning_provider_updates_store(monkeypatch):
    seen_sizes = []
    def fake_polish(text, reqs, **kw):
        seen_sizes.append(len(reqs))
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}
    monkeypatch.setattr(re2e, "_polish", fake_polish)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    re2e.run_persona(_persona(), _LearnsRound4(), flush_every=4)
    # Seed flush learns before the first scored translate.
    assert seen_sizes[0] >= 1


def test_dir_hash_snapshot(tmp_path, monkeypatch):
    import bench.suites.report as report
    monkeypatch.setattr(report, "RESULTS", tmp_path / "results")
    d = tmp_path / "personas"
    d.mkdir()
    (d / "a.json").write_text("{}")
    out = report.write_snapshot("E", str(d), [
        {"id": "p", "category": "persona", "pass": True}])
    import json
    snap = json.loads(out.read_text())
    assert len(snap["cases_hash"]) == 12


# ---------- scoring protocol v2 (2026-07-25) ----------

def _multi_req_persona():
    """Two applicable requirements per round — the case v1 scoring threw away:
    carrying one of two scored exactly the same as carrying neither."""
    rounds = [{"n": i, "task": f"task {i}", "applicable": [0, 1],
               "final": f"task {i} + both",
               # Keep a natural on every miss so the write path still flushes
               # under B-alignment (edited_diff alone cannot create memory).
               "natural_correction": "以后都要遵守规则"}
              for i in range(1, 17)]
    return {"id": "p2", "requirements": ["规则A", "规则B"], "rounds": rounds}


def test_partial_credit_within_round(monkeypatch):
    # carries 规则A, never 规则B → 0.5, not 0.0
    monkeypatch.setattr(re2e, "_carries",
                        lambda req, polished: (req == "规则A", False))
    monkeypatch.setattr(re2e, "_polish", lambda text, reqs, context=None: {
        "decision": "apply", "polished": text, "applied_ids": [],
        "parse_error": False, "latency_ms": 0})
    r = re2e.run_persona(_multi_req_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 0.5
    assert r["second_half_round_rate"] == 0.0      # all-or-nothing view kept
    assert r["score"] == r["second_half_rate"]


def test_repeats_average_and_report_spread(monkeypatch):
    calls = {"n": 0}

    def alternating(req, polished):
        calls["n"] += 1
        return (calls["n"] % 2 == 0, False)       # deterministic alternation
    monkeypatch.setattr(re2e, "_carries", alternating)
    monkeypatch.setattr(re2e, "_polish", lambda text, reqs, context=None: {
        "decision": "apply", "polished": text, "applied_ids": [],
        "parse_error": False, "latency_ms": 0})
    r = re2e.run_persona_repeats(_persona(), NullProvider(), repeats=3)
    assert r["repeats"] == 3 and len(r["rates"]) == 3
    assert r["score"] == sum(r["rates"]) / 3
    assert r["spread"] == max(r["rates"]) - min(r["rates"])


def test_repaired_mode_resets_store_to_gold(monkeypatch):
    sizes = []

    def fake_polish(text, reqs, **kw):
        sizes.append(len(reqs))
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}
    monkeypatch.setattr(re2e, "_polish", fake_polish)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))

    class _Garbage:
        """Learns nothing useful — repaired mode must still restore gold."""
        def extract(self, events, existing):
            return [{"kind": "new", "target_id": None, "text": "垃圾规则"}]

    r = re2e.run_persona(_multi_req_persona(), _Garbage(), flush_every=4,
                         mode="repaired")
    assert r["mode"] == "repaired"
    assert sizes[-1] == 2          # exactly the two gold rules, junk discarded


def test_chained_mode_keeps_junk(monkeypatch):
    sizes = []

    def fake_polish(text, reqs, **kw):
        sizes.append(len(reqs))
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}
    monkeypatch.setattr(re2e, "_polish", fake_polish)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))

    class _Garbage:
        def extract(self, events, existing):
            return [{"kind": "new", "target_id": None, "text": "垃圾规则"}]

    re2e.run_persona(_multi_req_persona(), _Garbage(), flush_every=4)
    assert sizes[-1] > 2           # chained mode lets the junk accumulate


def test_continuous_score_reaches_the_report(tmp_path, monkeypatch):
    import bench.suites.report as report
    rates = report.category_rates([
        {"id": "a", "category": "persona", "score": 0.75, "pass": False},
        {"id": "b", "category": "persona", "score": 0.25, "pass": False},
    ])
    assert rates["persona"] == 0.5      # v1 would have reported 0.0


def test_binary_results_still_supported():
    import bench.suites.report as report
    rates = report.category_rates([
        {"id": "a", "category": "x", "pass": True},
        {"id": "b", "category": "x", "pass": False},
    ])
    assert rates["x"] == 0.5


def test_gate_never_reads_the_diagnostic_snapshot(tmp_path, monkeypatch):
    """`E-repaired-*` must not satisfy a lookup for suite `E`. It did once:
    the glob matched it and it sorts last, so the gate silently graded itself
    on the easier gold-state-injected number."""
    import json

    import bench.suites.report as report
    res = tmp_path / "results"
    res.mkdir()
    monkeypatch.setattr(report, "RESULTS", res)
    (res / "E-20260725-120000.json").write_text(json.dumps(
        {"suite": "E", "score": 0.70, "at": "20260725-120000",
         "judge_model": "x", "results": []}))
    (res / "E-repaired-20260725-130000.json").write_text(json.dumps(
        {"suite": "E-repaired", "score": 0.99, "at": "20260725-130000",
         "judge_model": "x", "results": []}))
    assert report.latest("E")["score"] == 0.70
    assert report.latest("E-repaired")["score"] == 0.99
