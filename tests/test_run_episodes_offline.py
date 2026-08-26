"""Offline shakedown of the episode runner: a tiny synthetic episode, a
mocked LLM that echoes whatever memory block it was given, and a fake
extraction provider. Verifies the chained pass, arm scoring, and the STATE
alignment — the expensive pilot run should only ever discover product facts,
never runner bugs."""
import json

import pytest

import bench.suites.run_episodes as re_mod


def _episode():
    def requirement(cid, anchor, text):
        return {"id": cid, "text": text, "paraphrase": text,
                "anchor": anchor, "bucket": "deliverables",
                "scope_mode": "scoped", "applies_when": None,
                "work_kinds": ["report"], "key": "content.required",
                "confidence": 9}

    return {
        "id": "e-test", "protocol_version": 3,
        "user_turns": [
            {"seq": 1, "user_input": "以后邮件里要用词册"},
            {"seq": 2, "user_input": "以后报告里要放台账"},
            {"seq": 3, "user_input": "帮我写封邮件催发票",
             "probe": {"should_apply": ["c0"], "must_not_apply": []}},
            {"seq": 4, "user_input": "报告里别放台账了，改放簿录"},
            {"seq": 5, "user_input": "把这份报告整理一下",
             "probe": {"should_apply": ["s0"],
                       "must_not_apply": ["c1"]}},
        ],
        "ground_truth": {
            "requirements": [
                requirement("c0", "词册", "邮件里要用词册"),
                requirement("c1", "台账", "报告里要放台账"),
                requirement("s0", "簿录", "报告里改放簿录"),
            ],
            "lifecycle": [
                {"seq": 1, "op": "assert", "id": "c0"},
                {"seq": 2, "op": "assert", "id": "c1"},
                {"seq": 4, "op": "contradict", "id": "s0",
                 "target": "c1"},
            ],
            "state_checkpoints": [2, 5],
        },
    }


class _EchoLLM:
    """translate/arm calls echo the injected block into the rewrite, so the
    mech bands are driven purely by injection; extraction learns every rule
    verbatim and applies the supersession."""

    def complete(self, model, system, user, max_tokens=1024,
                 temperature=None):
        if "hunks" not in system.lower():
            return "[]"          # extraction/consolidation calls
        req = user.split("User request:\n")[-1].split("\n\nJSON:")[0]
        block = user.split(":\n", 1)[-1].split("\n\nUser request:")[0]
        return json.dumps({"decision": "apply", "applied": [],
                           "hunks": [{"old": req,
                                      "new": f"{req} || {block}"}]},
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
        lambda crit, ctx, **_kwargs: (
            any(w in ctx.get("rewritten_request", "")
                or any(w in item.get("text", "")
                       for item in ctx.get("candidate_entries", []))
                for w in ("词册", "台账", "簿录") if w in crit),
            False))
    return _episode()


def test_chained_pass_learns_and_supersedes(wired):
    out = re_mod.run_chained(wired, batch_size=1)
    texts = {r.text: r.status for r in out["store"].list()}
    assert texts.get("邮件里要用词册") == "active"
    assert texts.get("报告里要放台账") == "retired"      # superseded
    assert texts.get("报告里要放簿录") == "active"
    assert len(out["probe_rows"]) == 2


def test_probe_scoring_all_arms(wired):
    out = re_mod.run_chained(wired, batch_size=1)
    by_cid = {n["id"]: n
              for n in wired["ground_truth"]["requirements"]}
    late = out["probe_rows"][1]                       # seq 5, after supersede
    real = re_mod.score_probe(wired, late, "real", by_cid)
    no_ret = re_mod.score_probe(wired, late, "no_retire", by_cid)
    oracle = re_mod.score_probe(wired, late, "oracle", by_cid)
    null = re_mod.score_probe(wired, late, "null-generic", by_cid)
    # real: store is clean (台账 retired) → trap suppressed, the one
    # gold-applicable rule is carried.
    assert real["suppress_hits"] == 1 and real["carry_hits"] == 1
    # no_retire: injects the dead rule too → echo carries it → trap leaks
    assert no_ret["suppress_hits"] == 0
    # oracle: only should_apply memory is injected, never the full gold store.
    assert oracle["suppress_hits"] == 1 and oracle["carry_hits"] == 1
    # null-generic: nothing injected → nothing carried, nothing leaked
    assert null["carry_hits"] == 0 and null["suppress_hits"] == 1


def test_carry_fast_path_accepts_audited_equivalent_phrases():
    assert re_mod._explicit_clause_present(
        "draft a straightforward, direct email",
        {"text": "stop being polite and friendly",
         "paraphrase": "straightforward, direct"})
    assert re_mod._explicit_clause_present(
        "Write the report. Use present tense.",
        {"text": "never use future tense",
         "paraphrase": "use present tense"})


def test_carry_judge_receives_authored_equivalent(monkeypatch):
    seen = {}

    def fake_judge(criterion, context, **_kwargs):
        seen.update({"criterion": criterion, "context": context})
        return True, False

    monkeypatch.setattr(re_mod, "judge", fake_judge)
    row = {
        "round": {
            "seq": 1,
            "user_input": "Draft the launch email.",
            "probe": {"should_apply": ["c0"], "must_not_apply": []},
        },
        "store_state": [],
        "chained_out": {
            "decision": "apply",
            "polished": "Draft a brief launch email.",
            "applied_ids": [],
            "parse_error": False,
            "latency_ms": 1,
        },
    }
    node = {
        "id": "c0", "text": "Keep emails short.",
        "paraphrase": "Use a concise email style.", "anchor": "short",
    }

    scored = re_mod.score_probe({}, row, "real", {"c0": node})

    assert scored["carry_hits"] == 1
    assert "Use a concise email style" in seen["criterion"]
    assert seen["context"]["authored_equivalent"] == node["paraphrase"]


def test_oracle_protocol_injects_only_should_apply_without_history(
        wired, monkeypatch):
    seen = {}

    def fake_translate(text, requirements, context=None, raw_messages=None):
        seen.update({"text": text,
                     "requirements": [requirement.text
                                      for requirement in requirements],
                     "requirement_metadata": [
                         {"key": requirement.key,
                          "bucket": requirement.bucket,
                          "scope": requirement.scope,
                          "scope_mode": requirement.scope_mode,
                          "applies_when": requirement.applies_when,
                          "work_kinds": requirement.kinds}
                         for requirement in requirements],
                     "context": context,
                     "raw_messages": raw_messages})
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0,
                "reason": "model_noop"}

    monkeypatch.setattr(re_mod.tr_mod, "translate", fake_translate)

    round_ = wired["user_turns"][-1]
    re_mod.arm_oracle(
        [], wired, round_, transcript=["stale history"],
        raw_messages=["stale pending raw"])

    assert seen == {
        "text": "把这份报告整理一下",
        "requirements": ["报告里改放簿录"],
        "requirement_metadata": [
            {"key": "content.required", "bucket": "deliverables",
             "scope": {}, "scope_mode": "scoped", "applies_when": "",
             "work_kinds": ["report"]}],
        "context": None,
        "raw_messages": None,
    }
    assert "oracle" in re_mod.ARMS
    assert "oracle-arm" not in re_mod.ARMS
    assert "oracle-should" not in re_mod.ARMS


def test_full_context_leaks_by_construction(wired):
    out = re_mod.run_chained(wired, batch_size=1)
    by_cid = {n["id"]: n
              for n in wired["ground_truth"]["requirements"]}
    late = out["probe_rows"][1]
    fc = re_mod.score_probe(wired, late, "full_context", by_cid)
    # the transcript contains 台账 in the (withdrawn) turn AND in the
    # superseding turn; an echo model reproduces it → trap leaks. A real
    # model may do better — that is exactly what the arm measures.
    # (carry is judge-band and only graded on real/oracle now)
    assert fc["suppress_hits"] == 0
    assert fc["carry_n"] == 0


def test_state_band_alignment(wired):
    out = re_mod.run_chained(wired, batch_size=1)
    state = re_mod.score_state(wired, out["snapshots"][5], 5)
    # c1 is dead gold-side; its successor s0 has a DIFFERENT distinctive, so
    # c1 is checkable: no active entry may contain 台账. c0/s0 must each have
    # an active aligned entry.
    assert state["n"] == 3
    assert state["rate"] == 1.0, state["misses"]


def test_state_judge_compares_target_to_a_small_provenance_shortlist(
        monkeypatch):
    target = {
        "id": "c0", "text": "函数命名不要使用动词加名词的组合",
        "paraphrase": "函数名不能是动词与名词的组合",
        "anchor": "动词加名词",
    }
    ep = {
        "id": "state-shortlist", "protocol_version": 3,
        "user_turns": [{"seq": 1, "user_input": "函数命名规则"}],
        "ground_truth": {
            "requirements": [target],
            "lifecycle": [{"seq": 1, "op": "assert", "id": "c0"}],
            "state_checkpoints": [1],
        },
    }
    snapshot = [
        re_mod.Requirement(text=f"Unrelated stored rule {i}").to_dict()
        for i in range(30)
    ]
    aligned = re_mod.Requirement(
        text="Function names must not use verb-plus-noun combinations.",
        key="code.naming", sources=["函数命名不要使用动词加名词的组合"])
    snapshot.append(aligned.to_dict())
    seen = {}

    def fake_judge(criterion, context, **kwargs):
        seen["criterion"] = criterion
        seen["context"] = context
        seen["kwargs"] = kwargs
        return (any("verb-plus-noun" in item["text"]
                    for item in context["candidate_entries"]), False)

    monkeypatch.setattr(re_mod, "judge", fake_judge)
    state = re_mod.score_state(ep, snapshot, 1)

    assert state["rate"] == 1.0
    assert len(seen["context"]["candidate_entries"]) <= 5
    assert "paraphrase" in seen["criterion"]
    assert "stored_entries" not in seen["context"]
    assert seen["kwargs"]["model"] == re_mod.STATE_JUDGE_MODEL


def test_noop_keeps_every_expected_carry_in_the_denominator(
        wired, monkeypatch):
    out = re_mod.run_chained(wired, batch_size=1)
    by_cid = {n["id"]: n
              for n in wired["ground_truth"]["requirements"]}
    late = dict(out["probe_rows"][1])
    late["chained_polished"] = None
    late["chained_out"] = None
    monkeypatch.setitem(
        re_mod.ARMS, "real",
        lambda *_args, **_kwargs: {
            "decision": "noop", "polished": None, "latency_ms": 0,
            "block_chars": 0, "reason": "model_noop"})
    criteria = []

    def strict_judge(criterion, _context):
        criteria.append(criterion)
        return False, False

    monkeypatch.setattr(re_mod, "judge", strict_judge)

    row = re_mod.score_probe(wired, late, "real", by_cid)

    assert row["carry_hits"] == 0
    assert row["carry_n"] == 1
    assert re_mod._owner_metrics([row], "real") == {
        "tasks_perfect": 0, "tasks_n": 1,
        "memory_hit": 0, "memory_n": 1}
    assert criteria and all("mere compliance" in criterion
                            for criterion in criteria)


def test_carry_judge_sees_original_and_effective_request(wired, monkeypatch):
    out = re_mod.run_chained(wired, batch_size=1)
    by_cid = {n["id"]: n
              for n in wired["ground_truth"]["requirements"]}
    late = out["probe_rows"][1]
    seen = {}

    def spy(criterion, context):
        seen["criterion"] = criterion
        seen["context"] = context
        return True, False

    monkeypatch.setattr(re_mod, "judge", spy)
    re_mod.score_probe(wired, late, "real", by_cid)

    assert seen["context"]["original_request"] == \
        late["round"]["user_input"]
    assert seen["context"]["effective_request"] != \
        seen["context"]["original_request"]
    assert "directly transforming an applicable occurrence" in \
        seen["criterion"]
    assert "equivalent behavioral instruction" in seen["criterion"]


def test_only_probe_turns_translate_after_prior_buffer_is_flushed(
        wired, monkeypatch):
    calls = []

    def fake_translate(text, requirements, context=None, raw_messages=None):
        calls.append({"text": text, "context": context,
                      "requirements": [item.text for item in requirements],
                      "raw_messages": raw_messages})
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0,
                "reason": "model_noop"}

    monkeypatch.setattr(re_mod.tr_mod, "translate", fake_translate)
    re_mod.run_chained(wired, batch_size=10)

    assert [c["text"] for c in calls] == [
        "帮我写封邮件催发票", "把这份报告整理一下"]
    assert all(call["context"] is None for call in calls)
    assert all(call["requirements"] for call in calls)
    assert all(call["raw_messages"] is None for call in calls)


def test_previous_turn_is_extracted_before_translation_without_current_leak(
        wired, monkeypatch):
    calls = []

    def fake_translate(text, requirements, context=None, raw_messages=None):
        calls.append({
            "text": text,
            "requirements": [item.text for item in requirements],
            "raw_messages": raw_messages,
        })
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0,
                "reason": "model_noop"}

    class EchoPreviousTurn:
        def extract(self, events, existing):
            return [{"kind": "new", "text": f"MEM:{event['text']}"}
                    for event in events]

    monkeypatch.setattr(re_mod.tr_mod, "translate", fake_translate)
    monkeypatch.setattr(re_mod, "V1Provider", EchoPreviousTurn)
    re_mod.run_chained(wired, batch_size=10)

    assert [call["text"] for call in calls] == [
        "帮我写封邮件催发票", "把这份报告整理一下"]
    assert calls[0]["requirements"] == [
        "MEM:以后邮件里要用词册", "MEM:以后报告里要放台账"]
    assert "MEM:帮我写封邮件催发票" not in calls[0]["requirements"]
    assert "MEM:帮我写封邮件催发票" in calls[1]["requirements"]
    assert "MEM:报告里别放台账了，改放簿录" in calls[1]["requirements"]
    assert "MEM:把这份报告整理一下" not in calls[1]["requirements"]
    assert all(call["raw_messages"] is None for call in calls)


def test_chained_sut_receives_user_input_but_no_evaluator_attributes(
        wired, monkeypatch):
    translate_calls = []
    extracted_events = []
    for index, round_ in enumerate(wired["user_turns"]):
        round_["context"] = {
            "task": f"gold-task-{index}", "app": "gold-app",
            "lang": "gold-lang"}
        round_["type"] = f"gold-type-{index}"
        round_["effects"] = [{"gold": index}]

    def fake_translate(text, requirements, context=None, raw_messages=None):
        translate_calls.append({
            "text": text, "context": context,
            "raw_messages": raw_messages})
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0,
                "reason": "model_noop"}

    class Spy:
        def extract(self, events, existing):
            extracted_events.extend(dict(event) for event in events)
            return []

    monkeypatch.setattr(re_mod.tr_mod, "translate", fake_translate)
    monkeypatch.setattr(re_mod, "V1Provider", Spy)
    re_mod.run_chained(wired, batch_size=2)

    assert [call["text"] for call in translate_calls] == [
        round_["user_input"] for round_ in wired["user_turns"]
        if round_.get("probe")]
    assert all(call["context"] is None for call in translate_calls)
    assert all(call["raw_messages"] is None for call in translate_calls)
    assert extracted_events == [
        {"type": "natural", "text": round_["user_input"]}
        for round_ in wired["user_turns"]]


def test_chained_pass_flushes_before_probes_and_at_episode_end(
        wired, monkeypatch):
    wired["ground_truth"]["state_checkpoints"] = []
    batches = []

    class Spy:
        def extract(self, events, existing):
            batches.append([event["text"] for event in events])
            return []

    monkeypatch.setattr(re_mod, "V1Provider", Spy)
    re_mod.run_chained(wired, batch_size=10)

    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_chained_pass_flushes_when_ten_item_buffer_is_full_and_before_probe(
        wired, monkeypatch):
    wired["user_turns"] = [
        {"seq": seq, "user_input": f"turn-{seq}", **(
            {"probe": {"should_apply": [], "must_not_apply": []}}
            if seq == 20 else {})}
        for seq in range(1, 21)]
    wired["ground_truth"] = {
        "requirements": [], "lifecycle": [], "state_checkpoints": []}
    batches = []

    class Spy:
        def extract(self, events, existing):
            batches.append([event["text"] for event in events])
            return []

    monkeypatch.setattr(re_mod, "V1Provider", Spy)
    re_mod.run_chained(wired, batch_size=10)

    assert batches == [
        [f"turn-{seq}" for seq in range(1, 11)],
        [f"turn-{seq}" for seq in range(11, 20)],
        ["turn-20"],
    ]


def test_state_checkpoint_never_flushes_pending(wired, monkeypatch):
    wired["user_turns"].append({"seq": 6, "user_input": "尾轮"})
    wired["ground_truth"]["state_checkpoints"] = [5]
    batches = []

    class Spy:
        def extract(self, events, existing):
            batches.append([event["text"] for event in events])
            return []

    monkeypatch.setattr(re_mod, "V1Provider", Spy)
    out = re_mod.run_chained(wired, batch_size=10)

    # The authored checkpoint remains evaluator-only. Protocol flushes happen
    # before probes, at a full buffer, and at episode end only.
    assert [len(batch) for batch in batches] == [2, 2, 2]
    assert out["snapshots"][5] == []


def test_probe_trace_is_opt_in(wired, monkeypatch):
    monkeypatch.setattr(re_mod, "write_snapshot", lambda *_a, **_k: None)

    scores_only = re_mod.run_one(
        wired, ["real"], sizes=None, use_canary=False, save_trace=False)
    full = re_mod.run_one(
        wired, ["real"], sizes=None, use_canary=False, save_trace=True)

    assert "probe_trace" not in scores_only
    assert "write_trace" not in scores_only
    assert len(full["probe_trace"]["chained"]) == 2
    assert len(full["probe_trace"]["scores"]) == 2
    assert "translator" in full["probe_trace"]["scores"][0]
    assert full["write_trace"]
    assert {"events", "ops", "store_apply"} <= full["write_trace"][0].keys()


def test_main_loads_requested_episode_corpus(tmp_path, monkeypatch):
    episode_dir = tmp_path / "episodes-noisy"
    episode_dir.mkdir()
    episode = {
        "id": "e-custom", "protocol_version": 3,
        "user_turns": [{"seq": 1, "user_input": "ordinary request"}],
        "ground_truth": {
            "requirements": [], "lifecycle": [], "state_checkpoints": []},
    }
    (episode_dir / "e-custom.json").write_text(json.dumps(episode))
    captured = {}

    def fake_run_one(ep, arms, sizes, use_canary, save_trace=False,
                     cases_dir=None):
        captured.update(ep=ep, arms=arms, sizes=sizes,
                        use_canary=use_canary, save_trace=save_trace,
                        cases_dir=cases_dir)
        return {"id": ep["id"]}

    monkeypatch.setattr(re_mod, "run_one", fake_run_one)
    re_mod.main([
        "e-custom", "--episodes-dir", str(episode_dir),
        "--arms", "real", "--workers", "1"])

    assert captured["ep"] == episode
    assert captured["cases_dir"] == episode_dir.resolve()
