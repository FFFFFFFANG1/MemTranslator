"""M2: extraction call — numbered-candidate protocol, salience gate,
op parsing. All LLM calls faked via monkeypatching llm.complete."""
import json

import memtranslator.llm as llm
from memtranslator.extraction import parse_ops, run_extraction
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


def test_style_rule_op_maps_to_style_kind():
    ops, _ = parse_ops(json.dumps([
        {"op": "style_rule", "text": "保留用户原句式，约束以从句追加",
         "salience": 4},
    ]), [])
    assert ops == [{"kind": "new", "text": "保留用户原句式，约束以从句追加",
                    "key": "", "scope": {}, "salience": 4,
                    "rkind": "style_rule", "bucket": "", "polarity": "",
                    "evidence_id": ""}]


def test_contradict_carries_new_text_and_target():
    existing = _reqs("邮件不超过120词")
    ops, _ = parse_ops(json.dumps([
        {"op": "contradict", "target": 1,
         "text": "邮件不超过120词——正式求职信除外", "key": "email.length",
         "salience": 4},
    ]), existing)
    assert ops[0]["kind"] == "contradict"
    assert ops[0]["target_id"] == existing[0].id
    assert "求职信" in ops[0]["text"]


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
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["user"] = user
        return json.dumps([
            {"op": "new", "text": "commit message 用英文",
             "key": "commit.language", "salience": 4,
             "evidence": "以后 commit 都写英文"},
            {"op": "reinforce", "target": 1, "salience": 4,
             "evidence": "又提了周报 bullet"},
        ])
    monkeypatch.setattr(llm, "complete", fake)
    out = run_extraction(
        a_candidates=["以后 commit 都写英文", "周报继续 bullet points"],
        b_candidates=[{"raw": "r", "polished": "p", "final": "f",
                       "applied": ["周报要用 bullet points"],
                       "survival": "mixed"}],
        existing=existing)
    assert [o["kind"] for o in out["ops"]] == ["new", "reinforce"]
    assert out["ops"][1]["target_id"] == existing[0].id
    assert out["flags"] == []
    # numbered index and both candidate sections reached the prompt
    assert "[1]" in seen["user"] and "commit 都写英文" in seen["user"]
    assert "survival" in seen["user"] or "mixed" in seen["user"]
