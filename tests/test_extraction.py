"""M2: extraction call — numbered-candidate protocol, salience gate,
op parsing. All LLM calls faked via monkeypatching llm.complete."""
import json

import pytest

import memtranslator.llm as llm
from memtranslator.extraction import (A_EXTRACTION_SYSTEM, B_EXTRACTION_SYSTEM,
                                      build_b_user_prompt, parse_feedback_ops,
                                      parse_ops, run_b_extraction,
                                      run_extraction)
from memtranslator.memory_write import CONSOLIDATION_SYSTEM
from memtranslator.schema import Requirement


def _reqs(*texts):
    return [Requirement(text=t) for t in texts]


def test_numbered_target_resolves_to_id():
    existing = _reqs("邮件不超过120词", "代码只给代码")
    ops, flags = parse_ops(json.dumps([
        {"op": "reinforce", "target": 2, "salience": 4, "evidence": "又说了一遍"},
    ]), existing)
    assert ops == [{"kind": "reinforce", "target_id": existing[1].id}]
    assert flags == []


def test_out_of_range_target_dropped_and_flagged():
    existing = _reqs("唯一条目")
    ops, flags = parse_ops(json.dumps([
        {"op": "retire", "target": 5, "salience": 5},
        {"op": "new", "text": "有效规则", "key": "email.length",
         "salience": 4},
    ]), existing)
    assert len(ops) == 1 and ops[0]["kind"] == "new"
    assert len(flags) == 1


def test_salience_gate_drops_low():
    ops, flags = parse_ops(json.dumps([
        {"op": "new", "text": "低显著度", "salience": 2},
        {"op": "new", "text": "高显著度", "key": "report.format", "salience": 4},
    ]), [])
    assert [o["text"] for o in ops] == ["高显著度"]
    assert flags == []


def test_garbage_output_yields_empty_with_flag():
    ops, flags = parse_ops("sorry, I cannot help with that", [])
    assert ops == [] and flags == ["unparseable"]


def test_unescaped_inner_quotes_repaired_not_dropped():
    """Observed live: flash echoes the user's curly quotes back as ASCII
    double quotes inside a JSON string value, invalidating the array. The
    whole batch — all of it correct — was thrown away as unparseable."""
    raw = ('[{"op": "new", "target": null, '
           '"text": "避免第一人称（如"我建议"、"我觉得"），改用客观陈述。", '
           '"key": "style.perspective", "salience": 5}]')
    ops, flags = parse_ops(raw, [])
    assert len(ops) == 1
    assert "我建议" in ops[0]["text"]
    assert flags == []


def test_escaped_quotes_and_clean_json_unaffected_by_repair():
    raw = ('[{"op": "new", "target": null, '
           '"text": "use \\"snake_case\\" for tests", "salience": 4}]')
    ops, flags = parse_ops(raw, [])
    assert len(ops) == 1 and 'use "snake_case" for tests' == ops[0]["text"]


def test_run_extraction_end_to_end(monkeypatch):
    existing = _reqs("周报要用 bullet points")
    calls = []

    def fake(model, system, user, max_tokens=1024, **kw):
        calls.append({"system": system, "user": user})
        if "SIGNALS-A:" in user:
            return json.dumps([
                {"decision": "candidate", "kind": "potential_new", "item": {
                    "text": "Write commit messages in English.",
                        "bucket": "output_contract", "scope_mode": "scoped",
                        "applies_when": None,
                    "work_kinds": ["code"], "key": "commit.language", "confidence": 8}, "change_candidate": None,
                 "sources": [1]},
                {"decision": "candidate", "kind": "potential_new", "item": {
                    "text": "Use bullet points in weekly reports.",
                        "bucket": "output_contract", "scope_mode": "scoped",
                        "applies_when": None,
                    "work_kinds": ["report"], "key": "format.structure", "confidence": 8}, "change_candidate": None,
                 "sources": [2]},
            ])
        return json.dumps([
            {"case": 1, "action": "add", "targets": []},
            {"case": 2, "action": "reaffirm", "targets": [1]},
        ])
    monkeypatch.setattr(llm, "complete", fake)
    out = run_extraction(
        a_candidates=["以后 commit 都写英文", "周报继续 bullet points"],
        b_candidates=[], existing=existing)
    assert [o["kind"] for o in out["ops"]] == ["new", "reinforce"]
    assert out["ops"][1]["target_id"] == existing[0].id
    assert out["ops"][1]["sources"] == ["周报继续 bullet points"]
    assert out["ops"][0]["sources"] == ["以后 commit 都写英文"]
    assert out["flags"] == []
    assert [c["system"] for c in calls] == [A_EXTRACTION_SYSTEM,
                                             CONSOLIDATION_SYSTEM]
    assert "commit 都写英文" in calls[0]["user"]
    assert "CASE 1" in calls[1]["user"] and "MEMORIES" in calls[1]["user"]


def test_a_route_refuses_to_carry_b_signals():
    """The routes no longer share an executor, so one call cannot serve
    both: route B's judgements never reach Store.apply_ops."""
    with pytest.raises(ValueError):
        run_extraction(a_candidates=["以后周报用 bullet"],
                       b_candidates=[{"entries": [], "diff": []}],
                       existing=[])


def test_a_prompt_forces_head_tail_compaction_at_its_own_boundary():
    from memtranslator.extraction import build_candidate_user_prompt

    signal = ("SIGNAL-BEGIN-" + "甲" * 500 + "MIDDLE-SENTINEL"
              + "乙" * 500 + "-SIGNAL-END")
    prompt = build_candidate_user_prompt([signal], ["any"])
    payload = prompt.split("SIGNALS-A:\n", 1)[1].split(
        "\n\nKnown work_kinds", 1)[0]
    shown = json.loads(payload)[0]["text"]

    assert shown.startswith("SIGNAL-BEGIN-")
    assert shown.endswith("-SIGNAL-END")
    assert "MIDDLE-SENTINEL" not in shown
    assert "[truncated]" in shown
    assert "[truncated]" in A_EXTRACTION_SYSTEM


def test_the_two_prompts_have_disjoint_operation_contracts():
    assert "SIGNALS-B" not in A_EXTRACTION_SYSTEM
    assert "SIGNALS-A" not in B_EXTRACTION_SYSTEM
    # Route B may only judge the entries the patch used: no store index, no
    # creation, none of route A's op vocabulary.
    assert "STORE: the current entries" not in B_EXTRACTION_SYSTEM
    b_contract = B_EXTRACTION_SYSTEM.rsplit("Output STRICTLY", 1)[1]
    assert '"update"|"retire"|"none"' in b_contract
    for kind in ("new", "reinforce", "contradict", "style_rule", "salience"):
        assert kind not in b_contract
    assert "Never create a new memory" in B_EXTRACTION_SYSTEM
    assert "same facet" in B_EXTRACTION_SYSTEM
    assert "independently satisfiable" in B_EXTRACTION_SYSTEM
    assert '"translator_output"' in B_EXTRACTION_SYSTEM
    assert '"user_edition"' in B_EXTRACTION_SYSTEM
    assert '"old"' not in B_EXTRACTION_SYSTEM
    assert '"new"' not in B_EXTRACTION_SYSTEM
    assert "reinforce" not in build_b_user_prompt([])


def test_feedback_parser_binds_only_recorded_entries():
    entry = Requirement(text="Emails must stay under 120 words.")
    candidates = [{"entries": [entry.to_dict()], "diff": [
        {"old": "Keep it under 120 words.",
         "new": "Keep it under 80 words."}]}]
    ops, flags = parse_feedback_ops(json.dumps(
        [{"signal": 1, "entry": 1, "op": "update",
          "text": "Emails must stay under 80 words."}]), candidates)
    assert flags == []
    assert ops == [{"kind": "update", "target_id": entry.id,
                    "text": "Emails must stay under 80 words."}]

    # An entry outside the signal is unreachable — there is no id to name.
    ops, flags = parse_feedback_ops(json.dumps(
        [{"signal": 1, "entry": 2, "op": "retire"}]), candidates)
    assert ops == [] and any("entry out of range" in f for f in flags)


def test_feedback_ops_are_returned_in_signal_chronology():
    """Buffer order decides, not model array order: a later refinement must
    reset the feedback score an earlier removal vote lowered."""
    entry = Requirement(text="Emails must stay under 120 words.")
    candidate = {"entries": [entry.to_dict()], "diff": [
        {"old": "Keep it under 120 words.", "new": "Keep it under 80 words."}]}
    ops, flags = parse_feedback_ops(json.dumps([
        {"signal": 2, "entry": 1, "op": "update",
         "text": "Emails must stay under 80 words."},
        {"signal": 1, "entry": 1, "op": "retire"},
    ]), [candidate, candidate])
    assert flags == []
    assert [op["kind"] for op in ops] == ["retire", "update"]


def test_feedback_none_and_no_op_update_produce_nothing():
    entry = Requirement(text="Emails must stay under 120 words.")
    candidates = [{"entries": [entry.to_dict()], "diff": [
        {"old": "Keep it under 120 words.", "new": "Keep it under 80 words."}]}]
    ops, flags = parse_feedback_ops(
        json.dumps([{"signal": 1, "entry": 1, "op": "none"}]), candidates)
    assert ops == [] and flags == []
    ops, flags = parse_feedback_ops(json.dumps(
        [{"signal": 1, "entry": 1, "op": "update",
          "text": "Emails must stay under 120 words."}]), candidates)
    assert ops == [] and any("unchanged" in f for f in flags)


def test_run_b_extraction_sees_entries_and_diff_only(monkeypatch):
    entry = Requirement(text="Emails must stay under 120 words.")
    candidates = [{"entries": [entry.to_dict()], "diff": [
        {"old": "Write the email under 120 words.",
         "new": "Write the email."}]}]
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["system"], seen["user"] = system, user
        return json.dumps([{"signal": 1, "entry": 1, "op": "retire"}])
    monkeypatch.setattr(llm, "complete", fake)
    out = run_b_extraction(candidates)
    assert out["ops"] == [{"kind": "retire", "target_id": entry.id}]
    # the raw/polished triple belongs to route A's world; B sees the edit
    assert "polished" not in seen["user"] and "survival" not in seen["user"]
    assert seen["system"] is B_EXTRACTION_SYSTEM
