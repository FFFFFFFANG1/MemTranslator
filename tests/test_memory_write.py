"""Candidate-first route A: extractor, hybrid retrieval and consolidation."""
import json

import memtranslator.llm as llm
from memtranslator.memory_write import (
    CANDIDATE_EXTRACTION_SYSTEM,
    CONSOLIDATION_SYSTEM,
    CandidateCase,
    CandidateItem,
    MemoryCandidate,
    build_consolidation_user_prompt,
    parse_candidate_decisions,
    parse_candidate_output,
    parse_consolidation_output,
    retrieve_cases,
    run_memory_write,
)
from memtranslator.retrieval import (hybrid_order, quota_interleave_order,
                                     rrf_order)
from memtranslator.schema import Requirement
from memtranslator.store import Store


def _item(text="Keep emails concise.", **overrides):
    values = {
        "text": text,
        "bucket": "output_contract",
        "scope_mode": "scoped",
        "applies_when": "",
        "work_kinds": ["email"],
        "key": "length.max",
        "confidence": 8,
    }
    values.update(overrides)
    return CandidateItem(**values)


def _candidate(kind="potential_new", item=None, change=None, sources=None,
               texts=None, **kwargs):
    item = item if item is not None else _item()
    sources = sources or [1]
    texts = texts or ["signal"]
    return MemoryCandidate(
        "C1", kind, item, change, sources, texts, 1, **kwargs)


def test_candidate_parser_separates_new_from_explicit_replacement():
    raw = json.dumps([
        {
            "decision": "candidate",
            "kind": "potential_new",
            "item": _item().__dict__,
            "sources": [1],
        },
        {
            "decision": "candidate",
            "kind": "potential_change",
            "change_mode": "replace",
            "item": _item("Write emails as narrative prose.",
                          key="format.structure").__dict__,
            "target_query": "weekly report bullet format",
            "sources": [2],
        },
    ], ensure_ascii=False)

    candidates, flags = parse_candidate_output(
        raw, ["以后邮件都写短点", "别再用 bullet，改成叙述体"])

    assert flags == []
    assert [c.kind for c in candidates] == [
        "potential_new", "potential_change"]
    assert candidates[0].change_candidate is None
    assert candidates[0].source_texts == ["以后邮件都写短点"]
    assert candidates[1].change_candidate == "weekly report bullet format"
    assert candidates[1].change_mode == "replace"
    assert candidates[1].item.text == "Write emails as narrative prose."


def test_pure_withdrawal_is_a_change_with_no_successor_item():
    raw = json.dumps([{
        "decision": "candidate",
        "kind": "potential_change",
        "change_mode": "withdraw",
        "item": None,
        "target_query": "email greeting requirement",
        "bucket": "communication_style",
        "scope_mode": "scoped",
        "applies_when": None,
        "work_kinds": ["email"],
        "key": "greeting.presence",
        "confidence": 7,
        "sources": [1],
    }], ensure_ascii=False)
    candidates, flags = parse_candidate_output(raw, ["以后邮件不用问候语了"])
    assert flags == [] and candidates[0].item is None
    assert candidates[0].applies_when == ""
    assert candidates[0].work_kinds == ["email"]
    assert candidates[0].source_texts == ["以后邮件不用问候语了"]


def test_discard_decision_is_audited_but_never_becomes_a_candidate():
    raw = json.dumps([{
        "decision": "discard",
        "reason": "temporary",
        "sources": [1],
    }])

    candidates, discards, flags = parse_candidate_decisions(
        raw, ["Use a table for this run, then restore the usual format."])

    assert candidates == [] and flags == []
    assert len(discards) == 1
    assert discards[0].reason == "temporary"
    assert discards[0].source_signal_ids == [1]


def test_discard_only_batch_skips_retrieval_and_consolidation(monkeypatch):
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps([{
            "decision": "discard", "reason": "temporary", "sources": [1]
        }])

    monkeypatch.setattr(llm, "complete", fake)
    out = run_memory_write(
        ["Use a table for this run, then restore the usual format."], [])

    assert len(calls) == 1
    assert out["ops"] == [] and out["candidate_count"] == 0
    assert out["discards"] == [{"reason": "temporary", "sources": [1]}]
    assert out["trace"]["extractor"]["raw_output"]
    assert out["trace"]["extractor"]["discards"][0]["reason"] == "temporary"
    assert out["trace"]["consolidator"] is None


def test_write_trace_keeps_candidates_cases_and_consolidator_output(
        monkeypatch):
    replies = [
        json.dumps([{
            "decision": "candidate", "kind": "potential_new",
            "item": _item().__dict__, "target_query": None, "sources": [1],
        }]),
        json.dumps([{"case": 1, "action": "add", "targets": []}]),
    ]
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: replies.pop(0))

    out = run_memory_write(["Keep emails concise from now on."], [])
    trace = out["trace"]

    assert trace["input_signals"] == ["Keep emails concise from now on."]
    assert trace["extractor"]["candidates"][0]["item"]["text"] \
        == "Keep emails concise."
    assert trace["consolidator"]["cases"][0]["memories"] == []
    assert '"action": "add"' in trace["consolidator"]["raw_output"]
    assert trace["ops"][0]["kind"] == "new"


def test_invalid_applicability_gets_one_protocol_repair(monkeypatch):
    invalid = _item(
        "Meetings may be scheduled on weekends.",
        scope_mode="scoped", work_kinds=["all"], applies_when="",
        key="schedule.weekend").__dict__
    repaired = {**invalid, "work_kinds": ["meeting"]}
    replies = [
        json.dumps([{
            "decision": "candidate", "kind": "potential_change",
            "change_mode": "replace", "item": invalid,
            "target_query": "weekday-only meeting restriction",
            "sources": [1],
        }]),
        json.dumps([{
            "decision": "candidate", "kind": "potential_change",
            "change_mode": "replace", "item": repaired,
            "target_query": "weekday-only meeting restriction",
            "sources": [1],
        }]),
        json.dumps([{"case": 1, "action": "replace", "targets": [1]}]),
    ]
    prompts = []

    def fake(_model, _system, user, **_kwargs):
        prompts.append(user)
        return replies.pop(0)

    monkeypatch.setattr(llm, "complete", fake)
    old = Requirement(text="Only schedule meetings on weekdays.")

    out = run_memory_write(
        ["From now on, meetings may be scheduled on weekends."], [old])

    assert out["ops"][0]["kind"] == "contradict"
    assert out["ops"][0]["kinds"] == ["meeting"]
    assert "VALIDATION RETRY" in prompts[1]
    attempts = out["trace"]["extractor"]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["flags"]
    assert attempts[1]["flags"] == []


def test_candidate_prompt_gates_on_user_owned_requirements_first():
    ownership = CANDIDATE_EXTRACTION_SYSTEM.index(
        "Focus only on the user's own requirements")
    temporal = CANDIDATE_EXTRACTION_SYSTEM.index(
        "current task is temporary by default")
    assert ownership < temporal
    assert all(word in CANDIDATE_EXTRACTION_SYSTEM
               for word in ("boss", "client", "team", "another person"))
    assert "dietary restrictions" in CANDIDATE_EXTRACTION_SYSTEM
    assert "current task is temporary by default" in CANDIDATE_EXTRACTION_SYSTEM
    assert "not_requirement" in CANDIDATE_EXTRACTION_SYSTEM


def test_candidate_prompt_forbids_redundant_applies_when():
    assert "distinguish cases within the same work kind" in (
        CANDIDATE_EXTRACTION_SYSTEM)
    assert "when writing code/reports" in CANDIDATE_EXTRACTION_SYSTEM
    assert "use null" in CANDIDATE_EXTRACTION_SYSTEM


def test_candidate_prompt_defines_two_disjoint_injection_lanes():
    prompt = CANDIDATE_EXTRACTION_SYSTEM
    assert "ALWAYS-IN-CONTEXT" in prompt
    assert "RETRIEVAL-ONLY" in prompt
    assert 'scope_mode="global" + work_kinds=["all"] + applies_when=null' \
        in prompt
    assert 'scope_mode="scoped"' in prompt
    assert "Any other combination is invalid" in prompt
    assert "never inherit" in prompt
    assert "FINAL ROUTING CHECK" in prompt
    assert 'scoped + ["all"] + null is NEVER legal' in prompt


def test_explicit_change_mode_and_target_query_contracts_fail_closed():
    withdraw = {
        "decision": "candidate",
        "kind": "potential_change",
        "change_mode": "withdraw",
        "item": None,
        "target_query": "invoice greeting requirement",
        "bucket": "communication_style",
        "scope_mode": "scoped",
        "applies_when": None,
        "work_kinds": ["invoice"],
        "key": "greeting.presence",
        "confidence": 8,
        "sources": [1],
    }
    replace = {
        "decision": "candidate",
        "kind": "potential_change",
        "change_mode": "replace",
        "item": _item("Use a one-line invoice greeting.",
                      work_kinds=["invoice"],
                      key="greeting.presence").__dict__,
        "target_query": "invoice greeting requirement",
        "sources": [2],
    }
    invalid_withdraw = {**withdraw, "item": replace["item"], "sources": [3]}
    invalid_replace = {**replace, "item": None, "sources": [4]}

    candidates, discards, flags = parse_candidate_decisions(
        json.dumps([withdraw, replace, invalid_withdraw, invalid_replace]),
        ["s1", "s2", "s3", "s4"])

    assert discards == []
    assert [(candidate.change_mode, candidate.item is None)
            for candidate in candidates] == [
                ("withdraw", True), ("replace", False)]
    assert candidates[0].change_candidate == "invoice greeting requirement"
    assert len(flags) == 2


def test_malformed_candidate_invariants_are_dropped():
    raw = json.dumps([
        {"decision": "candidate", "kind": "potential_new",
         "change_mode": "replace", "item": _item().__dict__,
         "target_query": "an old rule",
         "sources": [1]},
        {"decision": "candidate", "kind": "potential_change",
         "change_mode": "replace", "item": _item().__dict__,
         "sources": [1]},
    ])
    candidates, flags = parse_candidate_output(raw, ["signal"])
    assert candidates == [] and len(flags) == 2


def test_open_work_kind_slug_is_admitted():
    raw = json.dumps([{
        "decision": "candidate",
        "kind": "potential_new",
        "item": _item("Write weekly reports as narrative prose.",
                      work_kinds=["weekly_report"],
                      key="format.structure").__dict__,
        "target_query": None,
        "sources": [1],
    }])
    candidates, flags = parse_candidate_output(raw, ["周报改成叙述"])
    assert flags == [] and candidates[0].item.work_kinds == ["weekly_report"]
    assert candidates[0].change_candidate is None


def test_potential_new_with_target_query_fails_closed():
    raw = json.dumps([{
        "decision": "candidate",
        "kind": "potential_new",
        "change_mode": None,
        "item": _item().__dict__,
        "target_query": "an existing email length rule",
        "sources": [1],
    }])

    candidates, flags = parse_candidate_output(raw, ["Keep emails concise."])

    assert candidates == []
    assert flags == ["candidate 1: potential_new target_query must be null"]


def test_known_work_kinds_inventory_lists_seed_and_store():
    from memtranslator.memory_write import (
        build_candidate_user_prompt, known_work_kinds)
    existing = [Requirement(text="x", kinds=["weekly_report"]),
                Requirement(text="y", kinds=["email"], status="retired")]
    inventory = known_work_kinds(existing)
    assert "weekly_report" in inventory and "email" in inventory
    assert "any" not in inventory
    prompt = build_candidate_user_prompt(["signal"], inventory)
    assert "Known work_kinds" in prompt
    assert "weekly_report" in prompt
    assert '"all"' not in prompt.split("Known work_kinds", 1)[1]


def test_item_requires_nonempty_work_kinds():
    base = _item().__dict__
    missing = {key: value for key, value in base.items()
               if key != "work_kinds"}
    empty = {**base, "work_kinds": []}
    raw = json.dumps([
        {"decision": "candidate", "kind": "potential_new", "item": missing,
         "sources": [1]},
        {"decision": "candidate", "kind": "potential_new", "item": empty,
         "sources": [1]},
    ])
    candidates, flags = parse_candidate_output(raw, ["signal"])
    assert candidates == [] and len(flags) == 2
    assert all("work_kinds" in flag for flag in flags)


def test_item_requires_explicit_consistent_scope_mode():
    base = _item().__dict__
    missing = {key: value for key, value in base.items()
               if key != "scope_mode"}
    global_specific_kind = {**base, "scope_mode": "global"}
    global_with_condition = {
        **base, "scope_mode": "global", "work_kinds": ["all"],
        "applies_when": "when writing to Smith"}
    raw = json.dumps([
        {"decision": "candidate", "kind": "potential_new", "item": item,
         "sources": [1]}
        for item in (missing, global_specific_kind, global_with_condition)
    ])

    candidates, flags = parse_candidate_output(raw, ["signal"])

    assert candidates == [] and len(flags) == 3
    assert all("scope_mode" in flag or "global" in flag for flag in flags)


def test_new_applicability_protocol_reserves_global_for_every_output():
    base = {
        "text": "Keep the output concise.",
        "bucket": "output_contract",
        "key": "length.max",
        "confidence": 8,
    }
    items = [
        {**base, "scope_mode": "global", "applies_when": None,
         "work_kinds": ["all"]},
        {**base, "scope_mode": "scoped",
         "applies_when": "when abbreviations appear",
         "work_kinds": ["all"]},
        {**base, "scope_mode": "scoped", "applies_when": None,
         "work_kinds": ["email"]},
        {**base, "scope_mode": "global", "applies_when": None,
         "work_kinds": ["email"]},
        {**base, "scope_mode": "global",
         "applies_when": "when abbreviations appear",
         "work_kinds": ["all"]},
        {**base, "scope_mode": "scoped", "applies_when": None,
         "work_kinds": ["all"]},
        {**base, "scope_mode": "scoped",
         "applies_when": "when writing to Smith",
         "scope": {"audience": "smith"}, "work_kinds": ["email"]},
    ]
    raw = json.dumps([
        {"decision": "candidate", "kind": "potential_new", "item": item,
         "target_query": None, "sources": [1]}
        for item in items
    ])

    candidates, flags = parse_candidate_output(raw, ["signal"])

    assert len(candidates) == 3
    assert candidates[0].item.scope_mode == "global"
    assert candidates[0].item.applies_when == ""
    assert candidates[1].item.work_kinds == ["any"]
    assert candidates[1].item.applies_when == "when abbreviations appear"
    assert candidates[2].item.work_kinds == ["email"]
    # scoped+all without a condition is ambiguous: it is neither the unique
    # always-on declaration nor a targetable retrieval declaration.
    assert len(flags) == 4
    assert any("scoped with work_kinds all requires" in flag
               for flag in flags)


def test_all_is_the_only_explicit_global_work_kind_and_prefixed_key_is_safe():
    valid = _item(work_kinds=["all"], scope_mode="global",
                  key="tone.register").__dict__
    mixed = _item(work_kinds=["all", "email"],
                  scope_mode="global",
                  key="tone.register").__dict__
    legacy = _item(work_kinds=["agent_response"],
                   key="tone.register").__dict__
    prefixed = _item(work_kinds=["email"], key="email.length.max").__dict__
    raw = json.dumps([
        {"decision": "candidate", "kind": "potential_new", "item": item,
         "sources": [1]}
        for item in (valid, mixed, legacy, prefixed)
    ])

    candidates, flags = parse_candidate_output(raw, ["signal"])

    assert len(candidates) == 2
    assert candidates[0].item.work_kinds == ["any"]
    assert candidates[0].item.key == "tone.register"
    assert candidates[1].item.work_kinds == ["email"]
    assert candidates[1].item.key == "email.length.max"
    assert len(flags) == 2


def test_rrf_fuses_rank_positions_and_is_deterministic():
    # Reciprocal rank rewards the two outer documents' first-place finish;
    # the caller-provided order then breaks exact ties deterministically.
    assert rrf_order([[0, 1, 2], [2, 1, 0]]) == [0, 2, 1]
    assert rrf_order([[0, 1], [1, 0]], tie_order=[1, 0]) == [1, 0]


class _Dense:
    def __init__(self):
        self.queries = []
        self.text_batches = []

    def rank(self, query, texts):
        self.queries.append(query)
        self.text_batches.append(texts)
        if "old format rule" in query:
            return [3, 2, 1, 0]
        return [1, 0, 2, 3]


class _BrokenDense:
    def rank(self, query, texts):
        raise RuntimeError("backend unavailable")


def test_embedding_failure_degrades_to_bm25():
    order = hybrid_order("email", ["email length rule", "code format rule"],
                         embedding_ranker=_BrokenDense())
    assert order[0] == 0


def test_positive_sparse_only_drops_zero_score_tail_before_rrf():
    class Dense:
        def rank(self, query, texts):
            return [1, 0, 2]

    order = hybrid_order(
        "email", ["email rule", "code rule", "report rule"],
        embedding_ranker=Dense(), positive_sparse_only=True)

    # Document 0 receives sparse evidence; zero-score documents participate
    # only through the dense route instead of acquiring a fake sparse rank.
    assert order[:2] == [0, 1]


def test_quota_interleave_refills_overlap_sparse_then_dense():
    order = quota_interleave_order(
        [0, 1, 2, 3, 4, 5], [2, 3, 6, 7, 8, 9], cap=8)

    assert order == [0, 1, 2, 3, 6, 7, 4, 8]


def test_quota_interleave_gives_unused_sparse_seats_to_dense():
    order = quota_interleave_order(
        [0], [1, 2, 3, 4, 5, 6, 7, 8], cap=8)

    assert order == [0, 1, 2, 3, 4, 5, 6, 7]


def test_each_candidate_retrieves_its_own_fixed_top3_with_the_right_query():
    existing = [Requirement(text=f"memory {i}") for i in range(4)]
    candidates = [
        MemoryCandidate("C1", "potential_new", _item("new text"),
                        None, [1], ["new"], 1),
        MemoryCandidate("C2", "potential_change", _item("replacement"),
                        "old format rule", [2], ["change"], 2),
    ]
    dense = _Dense()
    cases = retrieve_cases(candidates, existing, embedding_ranker=dense)

    assert len(dense.queries) == 2
    assert "text: new text" in dense.queries[0]
    assert "work_kinds: email" in dense.queries[0]
    assert "work_kind_keys: email.length.max" in dense.queries[0]
    assert "key: length.max" in dense.queries[0]
    assert "text: old format rule" in dense.queries[1]
    assert all(batch[0].startswith("text: memory 0\nwork_kinds:")
               for batch in dense.text_batches)
    assert all(len(case.memories) == 3 for case in cases)
    assert cases[0].memories != cases[1].memories


def test_onnx_ranker_prepares_unchanged_documents_only_once():
    from memtranslator.retrieval import OnnxE5Ranker

    ranker = OnnxE5Ranker.__new__(OnnxE5Ranker)
    ranker._document_vectors = {}
    calls = []

    def fake_encode(texts):
        calls.append(list(texts))
        return [f"vector:{text}" for text in texts]

    ranker._encode = fake_encode
    ranker.prepare(["doc-a", "doc-b"])
    ranker.prepare(["doc-a", "doc-b"])
    ranker.prepare(["doc-a", "doc-c"])

    assert calls == [
        ["passage: doc-a", "passage: doc-b"],
        ["passage: doc-c"],
    ]


def test_consolidator_prompt_omits_sources_and_confidence():
    old = Requirement(text="Keep emails under 120 words.",
                      bucket="output_contract", key="email.length",
                      scope={"audience": "smith"}, kinds=["email"],
                      confidence=6, sources=["old quote"])
    candidate = MemoryCandidate(
        "C1", "potential_change", _item(),
        "Keep emails under a word cap.", [1], ["quote"], 1)
    prompt = build_consolidation_user_prompt(
        [CandidateCase(candidate, [old])])

    assert "CASE 1" in prompt and "GROUPS" not in prompt
    assert '"legacy_scope": {"audience": "smith"}' in prompt
    assert '"work_kinds": ["email"]' in prompt
    assert "Keep emails under a word cap." in prompt
    assert "quote" not in prompt
    assert "confidence" not in prompt
    assert "sources" not in prompt
    assert "polarity" not in prompt
    assert "binding" not in CANDIDATE_EXTRACTION_SYSTEM
    assert "salience" not in CANDIDATE_EXTRACTION_SYSTEM
    assert "polarity" not in CONSOLIDATION_SYSTEM


def test_consolidator_case_never_truncates_candidate_or_similar_memories():
    candidate_text = "CANDIDATE-BEGIN-" + "候选" * 800 + "-CANDIDATE-END"
    memory_text = "MEMORY-BEGIN-" + "相似" * 800 + "-MEMORY-END"
    candidate = MemoryCandidate(
        "C1", "potential_new", _item(candidate_text),
        None, [1], ["raw source must stay outside the case"], 1)
    prompt = build_consolidation_user_prompt([
        CandidateCase(candidate, [Requirement(text=memory_text)])])

    assert candidate_text in prompt
    assert memory_text in prompt
    assert "[truncated]" not in prompt
    assert "raw source must stay outside the case" not in prompt


def test_consolidation_actions_map_to_store_ops_and_targets_stay_local():
    a, b = Requirement(text="old a"), Requirement(text="old b")
    change = MemoryCandidate("C1", "potential_change", _item("new a"),
                             "old a", [1], ["quote a"], 1)
    fresh = MemoryCandidate("C2", "potential_new", _item("fresh"),
                            None, [2], ["quote b"], 2)
    cases = [CandidateCase(change, [a]), CandidateCase(fresh, [b])]
    raw = json.dumps([
        {"case": 1, "action": "replace", "targets": [1]},
        {"case": 2, "action": "add", "targets": []},
    ])

    ops, flags = parse_consolidation_output(raw, cases)

    assert flags == []
    assert ops[0]["kind"] == "contradict"
    assert ops[0]["target_id"] == a.id and ops[0]["text"] == "new a"
    assert ops[0]["sources"] == ["quote a"]
    assert ops[0]["confidence"] == 8
    assert ops[1]["kind"] == "new" and ops[1]["text"] == "fresh"
    assert ops[1]["kinds"] == ["email"]
    assert ops[1]["sources"] == ["quote b"]


def test_target_collision_discards_every_conflicting_action():
    shared = Requirement(text="same memory")
    c1 = MemoryCandidate("C1", "potential_change", _item("one"),
                         "old", [1], ["q1"], 1)
    c2 = MemoryCandidate("C2", "potential_change", _item("two"),
                         "old", [2], ["q2"], 2)
    cases = [CandidateCase(c1, [shared]), CandidateCase(c2, [shared])]
    raw = json.dumps([
        {"case": 1, "action": "replace", "targets": [1]},
        {"case": 2, "action": "replace", "targets": [1]},
    ])
    ops, flags = parse_consolidation_output(raw, cases)
    assert ops == []
    assert any("target conflict" in flag for flag in flags)


def test_reaffirm_persists_sources_and_bumps_strength(tmp_path):
    store = Store(tmp_path / "store.jsonl")
    old = store.add("same", kinds=["email"], confidence=3,
                    sources=["first mention"])
    candidate = MemoryCandidate("C1", "potential_new", _item("same"),
                                None, [1], ["second mention"], 1)
    cases = [CandidateCase(candidate, [old])]
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "reaffirm", "targets": [1]}]),
        cases)
    assert flags == []
    assert ops == [{"kind": "reinforce", "target_id": old.id,
                    "sources": ["second mention"], "confidence": 8}]
    store.apply_ops(ops)
    got = store.get(old.id)
    assert got.strength == 2
    assert got.sources == ["first mention", "second mention"]
    assert got.confidence == 8


def test_ignore_on_unrelated_candidate_is_noop():
    old = Requirement(text="Keep emails concise.", kinds=["email"])
    candidate = MemoryCandidate(
        "C1", "potential_new",
        _item("Always use APA citations.", key="citation.format"),
        None, [1], ["apa"], 1)
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "ignore", "targets": []}]),
        [CandidateCase(candidate, [old])])
    assert ops == [] and flags == []


def test_cross_facet_single_target_merge_is_blocked():
    old = Requirement("For research summaries, cite sources.",
                      kinds=["agent_response"], bucket="deliverables",
                      key="citations.sources")
    candidate = MemoryCandidate(
        "C1", "potential_new",
        _item("For research surveys, state the conclusion first "
              "and cite sources.",
              work_kinds=["agent_response"], key="output.conclusion_first"),
        None, [1], ["survey signal"], 1)
    ops, flags = parse_consolidation_output(
        json.dumps([{
            "case": 1, "action": "merge", "targets": [1],
            "text": ("For research surveys and summaries, state the "
                     "conclusion first and cite sources."),
        }]),
        [CandidateCase(candidate, [old])])
    assert ops == []
    assert any("different facets" in flag for flag in flags)


def test_merge_two_independent_memories_is_blocked():
    a = Requirement(text="For research summaries, cite sources.",
                    kinds=["agent_response"], bucket="deliverables",
                    key="citations.sources")
    b = Requirement(text="For research surveys, conclusion first.",
                    kinds=["agent_response"], bucket="output_contract",
                    key="output.conclusion_first")
    candidate = MemoryCandidate(
        "C1", "potential_new",
        _item("For research surveys, conclusion first and cite sources.",
              work_kinds=["agent_response"]),
        None, [1], ["q"], 1)
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "merge", "targets": [1, 2]}]),
        [CandidateCase(candidate, [a, b])])
    assert ops == []
    assert any("different facets" in flag for flag in flags)


def test_same_facet_merge_two_memories_uses_store_merge():
    a = Requirement(text="For research summaries, cite sources.",
                    kinds=["agent_response"], bucket="deliverables",
                    key="citations.sources")
    b = Requirement(text="Research summaries need source citations.",
                    kinds=["agent_response"], bucket="deliverables",
                    key="citations.sources")
    candidate = MemoryCandidate(
        "C1", "potential_new",
        _item("For research summaries, cite sources.",
              bucket="deliverables", work_kinds=["agent_response"],
              key="citations.sources"),
        None, [1], ["q"], 1)
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "merge", "targets": [1, 2]}]),
        [CandidateCase(candidate, [a, b])])
    assert flags == []
    assert ops[0]["kind"] == "merge"
    assert set(ops[0]["target_ids"]) == {a.id, b.id}


def test_merge_exact_duplicate_normalises_to_reaffirm():
    old = Requirement(text="Keep emails concise.", kinds=["email"])
    candidate = MemoryCandidate("C1", "potential_new", _item(),
                                None, [1], ["again"], 1)
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "merge", "targets": [1]}]),
        [CandidateCase(candidate, [old])])
    assert flags == []
    assert ops == [{"kind": "reinforce", "target_id": old.id,
                    "sources": ["again"], "confidence": 8}]


def test_replace_persists_candidate_applicability_work_kinds_and_sources(
        tmp_path):
    store = Store(tmp_path / "store.jsonl")
    old = store.add("Use bullets in weekly reports.",
                    kinds=["weekly_report"])
    candidate = MemoryCandidate(
        "C1", "potential_change",
        _item("Use bullets in all prose deliverables.",
              scope_mode="global", work_kinds=["any"],
              key="document.format"),
        "Use bullets in weekly reports.", [1],
        ["apply it to all documents"], 1, change_mode="replace")
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "replace", "targets": [1]}]),
        [CandidateCase(candidate, [old])])
    assert flags == []
    store.apply_ops(ops)
    heir = store.active()[0]
    assert heir.applies_when == "" and heir.kinds == ["any"]
    assert heir.scope_mode == "global"
    assert heir.sources == ["apply it to all documents"]
    assert heir.confidence == 8


def test_potential_new_cannot_replace_a_memory():
    old = Requirement(text="Keep emails under 120 words.",
                      bucket="output_contract", key="email.length",
                      kinds=["email"])
    candidate = _candidate(item=_item("Keep emails under 80 words."))

    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "replace", "targets": [1]}]),
        [CandidateCase(candidate, [old])])

    assert ops == []
    assert any("invalid 'replace' contract" in flag for flag in flags)


def test_potential_new_merge_cannot_narrow_broad_applicability():
    old = Requirement(text="For research surveys, cite sources.",
                      bucket="deliverables", key="citations.sources",
                      scope={}, kinds=["any"])
    candidate = _candidate(item=_item(
        "For research surveys, cite sources.", bucket="deliverables",
        key="citations.sources",
        applies_when="when the field is speculative decoding",
        work_kinds=["report"]))

    # Avoid the exact-text reaffirm normalizer: the model's enriched merge is
    # semantically close but would replace broad metadata with one instance.
    candidate.item.text = "Research surveys should cite their sources."
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "merge", "targets": [1]}]),
        [CandidateCase(candidate, [old])])

    assert ops == []
    assert any("narrows applicability" in flag for flag in flags)


def test_explicit_replace_may_narrow_applicability():
    old = Requirement(text="For research surveys, cite sources.",
                      bucket="deliverables", key="citations.sources",
                      scope={}, kinds=["any"])
    candidate = MemoryCandidate(
        "C1", "potential_change",
        _item("Only speculative-decoding surveys need citations.",
              bucket="deliverables", key="citations.sources",
              applies_when="when the field is speculative decoding",
              work_kinds=["report"]),
        "research-survey citation scope", [1],
        ["From now on only speculative-decoding surveys need citations."],
        1, change_mode="replace")

    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "replace", "targets": [1]}]),
        [CandidateCase(candidate, [old])])

    assert flags == []
    assert ops[0]["kind"] == "contradict"
    assert ops[0]["applies_when"] == \
        "when the field is speculative decoding"
    assert ops[0]["kinds"] == ["report"]


def test_exact_duplicate_is_mechanically_reaffirmed():
    old = Requirement(text="Keep emails concise.", kinds=["email"])
    candidate = MemoryCandidate("C1", "potential_new", _item(),
                                None, [1], ["again"], 1)
    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "add", "targets": []}]),
        [CandidateCase(candidate, [old])])
    assert flags == []
    assert ops == [{"kind": "reinforce", "target_id": old.id,
                    "sources": ["again"], "confidence": 8}]


def test_withdraw_mode_allows_retire_but_never_reaffirm():
    old = Requirement(text="Invoices must include a greeting.",
                      bucket="communication_style", kinds=["invoice"])
    candidate = MemoryCandidate(
        "C1", "potential_change", None, "invoice greeting requirement",
        [1], ["drop the invoice greeting convention"], 1,
        bucket="communication_style", scope_mode="scoped",
        applies_when="", work_kinds=["invoice"],
        key="invoice.greeting", confidence=8, change_mode="withdraw")
    case = CandidateCase(candidate, [old])

    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "reaffirm", "targets": [1]}]),
        [case])
    assert ops == []
    assert any("invalid 'reaffirm' contract" in flag for flag in flags)

    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "retire", "targets": [1]}]),
        [case])
    assert flags == []
    assert ops == [{"kind": "retire", "target_id": old.id,
                    "withdrawal": True,
                    "sources": ["drop the invoice greeting convention"],
                    "confidence": 8}]


def test_replace_mode_cannot_retire():
    old = Requirement(text="Invoices must include a greeting.",
                      bucket="communication_style", kinds=["invoice"])
    candidate = MemoryCandidate(
        "C1", "potential_change",
        _item("Use a one-line invoice greeting.",
              bucket="communication_style", work_kinds=["invoice"],
              key="invoice.greeting"),
        "invoice greeting requirement", [1], ["use a shorter greeting"], 1,
        change_mode="replace")

    ops, flags = parse_consolidation_output(
        json.dumps([{"case": 1, "action": "retire", "targets": [1]}]),
        [CandidateCase(candidate, [old])])

    assert ops == []
    assert any("invalid 'retire' contract" in flag for flag in flags)


def test_prompts_forbid_store_crud_and_keep_atom_batch_rules_short():
    assert "GROUPS" not in CONSOLIDATION_SYSTEM
    assert "defer" not in CONSOLIDATION_SYSTEM
    assert "assert" not in CANDIDATE_EXTRACTION_SYSTEM
    assert "evidence_quotes" not in CANDIDATE_EXTRACTION_SYSTEM
    assert "Split independently enforceable" in (
        CANDIDATE_EXTRACTION_SYSTEM)
    assert "current task is temporary by default" in (
        CANDIDATE_EXTRACTION_SYSTEM)
    assert '"decision":"discard"' in CANDIDATE_EXTRACTION_SYSTEM
    assert "target_query" in CANDIDATE_EXTRACTION_SYSTEM
    assert "potential_change + withdraw" in CANDIDATE_EXTRACTION_SYSTEM
    assert "item must be null" in CANDIDATE_EXTRACTION_SYSTEM
    assert "change_mode withdraw" in CONSOLIDATION_SYSTEM
    assert "independently enforceable facets" in CONSOLIDATION_SYSTEM
    assert "must not narrow" in CONSOLIDATION_SYSTEM
    assert "confidence" in CANDIDATE_EXTRACTION_SYSTEM
    assert "polarity" not in CANDIDATE_EXTRACTION_SYSTEM
    assert "salience" not in CANDIDATE_EXTRACTION_SYSTEM
    assert "binding" not in CANDIDATE_EXTRACTION_SYSTEM
