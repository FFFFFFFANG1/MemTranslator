"""Offline shakedown of the episode runner: a tiny synthetic episode, a
mocked LLM that echoes whatever memory block it was given, and a fake
extraction provider. Verifies the chained pass, arm scoring, and the STATE
alignment — the expensive pilot run should only ever discover product facts,
never runner bugs."""
import json

import pytest

import bench_archive.runner.run_episodes as re_mod
from bench_archive.graph.schema import ANY


def _episode():
    def node(cid, distinctive, clause, successor_of=None):
        return {"cid": cid, "text": clause, "clause": clause,
                "alt_clause": clause, "distinctive": distinctive,
                "coords": {"bucket": "output_contract", "key": "email.length",
                           "polarity": "require", "binding": "hard",
                           "value": {"type": "numeric", "num": 1, "unit": "w",
                                     "cmp": "max"},
                           "scope": {"app": ANY, "task": ANY,
                                     "code_lang": ANY, "nat_lang": ANY}},
                "atom": {}, "successor_of": successor_of}

    return {
        "id": "e-test", "schema_version": "E1", "protocol_version": 2,
        "persona": {"id": "t"},
        "catalogue": [
            node("c0", "词册", "邮件里要用词册"),
            node("c1", "台账", "报告里要放台账"),
            node("s0", "簿录", "报告里改放簿录", successor_of="c1"),
        ],
        "effects": [
            {"seq": 1, "kind": "assert", "cid": "c0", "target": "",
             "targets": [], "delta": 0},
            {"seq": 2, "kind": "assert", "cid": "c1", "target": "",
             "targets": [], "delta": 0},
            {"seq": 4, "kind": "contradict", "cid": "s0", "target": "c1",
             "targets": [], "delta": 0},
        ],
        "rounds": [
            {"seq": 1, "type": "S", "text": "以后邮件里要用词册",
             "context": {}, "effects": []},
            {"seq": 2, "type": "S", "text": "以后报告里要放台账",
             "context": {}, "effects": []},
            {"seq": 3, "type": "R", "text": "帮我写封邮件催发票",
             "context": {}, "probe": True,
             "may_fire": ["c0", "c1"], "must_not_fire": []},
            {"seq": 4, "type": "S", "text": "报告里别放台账了，改放簿录",
             "context": {}, "effects": []},
            {"seq": 5, "type": "R", "text": "把这份报告整理一下",
             "context": {}, "probe": True,
             "may_fire": ["c0", "s0"], "must_not_fire": ["c1"]},
        ],
        "checkpoints": [2, 5],
        "dup_pairs": [],
    }


class _EchoLLM:
    """translate/arm calls echo the injected block into the rewrite, so the
    mech bands are driven purely by injection; extraction learns every rule
    verbatim and applies the supersession."""

    def complete(self, model, system, user, max_tokens=1024,
                 temperature=None):
        if "extract requirement operations" in system.lower() \
                or "durable" in system.lower():
            return "[]"
        req = user.split("User request:\n")[-1].split("\n\nJSON:")[0]
        block = user.split(":\n", 1)[-1].split("\n\nUser request:")[0]
        return json.dumps({"decision": "apply", "applied_ids": [],
                           "polished": f"{req} || {block}"},
                          ensure_ascii=False)


class _ScriptedProvider:
    """Learns each rule the round it is uttered; applies the contradict."""

    def __init__(self):
        self.n = 0

    def extract(self, events, existing):
        ops = []
        for e in events:
            t = e["text"]
            if "词册" in t and not any("词册" in r.text for r in existing):
                ops.append({"kind": "new", "text": "邮件里要用词册"})
            if "台账" in t and "簿录" not in t \
                    and not any("台账" in r.text for r in existing):
                ops.append({"kind": "new", "text": "报告里要放台账"})
            if "簿录" in t:
                tgt = next((r.id for r in existing if "台账" in r.text), None)
                ops.append({"kind": "contradict", "target_id": tgt,
                            "text": "报告里要放簿录"})
        return ops

    def consolidate(self, existing):
        return []


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.setattr(re_mod, "RUN_DIR", tmp_path)
    echo = _EchoLLM()
    monkeypatch.setattr(re_mod.llm, "complete", echo.complete)
    import memtranslator.translate as tr
    monkeypatch.setattr(tr.llm, "complete", echo.complete)
    monkeypatch.setattr(re_mod, "V1Provider", _ScriptedProvider)
    # offline judge: a clause is "carried" when its distinctive word made it
    # into the rewrite — keeps the judge band deterministic and networkless
    monkeypatch.setattr(
        re_mod, "judge",
        lambda crit, ctx: (any(w in ctx["rewritten_request"]
                               for w in ("词册", "台账", "簿录")
                               if w in crit), False))
    return _episode()


def test_chained_pass_learns_and_supersedes(wired):
    out = re_mod.run_chained(wired, flush_every=1)
    texts = {r.text: r.status for r in out["store"].list()}
    assert texts.get("邮件里要用词册") == "active"
    assert texts.get("报告里要放台账") == "retired"      # superseded
    assert texts.get("报告里要放簿录") == "active"
    assert len(out["probe_rows"]) == 2


def test_probe_scoring_all_arms(wired):
    out = re_mod.run_chained(wired, flush_every=1)
    by_cid = {n["cid"]: n for n in wired["catalogue"]}
    late = out["probe_rows"][1]                       # seq 5, after supersede
    real = re_mod.score_probe(wired, late, "real", by_cid)
    no_ret = re_mod.score_probe(wired, late, "no_retire", by_cid)
    oracle = re_mod.score_probe(wired, late, "oracle-arm", by_cid)
    null = re_mod.score_probe(wired, late, "null-generic", by_cid)
    # real: store is clean (台账 retired) → trap suppressed, both live carried
    assert real["suppress_hits"] == 1 and real["carry_hits"] == 2
    # no_retire: injects the dead rule too → echo carries it → trap leaks
    assert no_ret["suppress_hits"] == 0
    # oracle: gold store, perfect
    assert oracle["suppress_hits"] == 1 and oracle["carry_hits"] == 2
    # null-generic: nothing injected → nothing carried, nothing leaked
    assert null["carry_hits"] == 0 and null["suppress_hits"] == 1


def test_full_context_leaks_by_construction(wired):
    out = re_mod.run_chained(wired, flush_every=1)
    by_cid = {n["cid"]: n for n in wired["catalogue"]}
    late = out["probe_rows"][1]
    fc = re_mod.score_probe(wired, late, "full_context", by_cid)
    # the transcript contains 台账 in the (withdrawn) turn AND in the
    # superseding turn; an echo model reproduces it → trap leaks. A real
    # model may do better — that is exactly what the arm measures.
    # (carry is judge-band and only graded on real/oracle-arm now)
    assert fc["suppress_hits"] == 0
    assert fc["carry_n"] == 0


def test_state_band_alignment(wired):
    out = re_mod.run_chained(wired, flush_every=1)
    state = re_mod.score_state(wired, out["snapshots"][5], 5)
    # c1 is dead gold-side; its successor s0 has a DIFFERENT distinctive, so
    # c1 is checkable: no active entry may contain 台账. c0/s0 must each have
    # an active aligned entry.
    assert state["n"] == 3
    assert state["rate"] == 1.0, state["misses"]
