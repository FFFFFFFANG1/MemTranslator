import json

from bench.runner.schema import Check, TranslateCase, load_translate_cases


def test_load_translate_cases(tmp_path):
    p = tmp_path / "cases.jsonl"
    p.write_text(json.dumps({
        "id": "t-x-001", "category": "apply-single", "source": "handwritten",
        "requirements": ["Emails must stay under 120 words."],
        "input": "帮我给房东写封邮件",
        "expect_decision": "apply", "must_apply": [0],
        "checks": [{"kind": "mech", "name": "contains_all",
                    "args": {"keywords": ["房东"]}}],
    }, ensure_ascii=False) + "\n")
    cases = load_translate_cases(p)
    assert len(cases) == 1
    c = cases[0]
    assert isinstance(c, TranslateCase) and c.must_apply == [0]
    assert c.checks[0] == Check(kind="mech", name="contains_all",
                                args={"keywords": ["房东"]})


def test_expect_decision_validated(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"id": "b", "category": "c", "source": "s", '
                 '"requirements": [], "input": "x", '
                 '"expect_decision": "maybe", "must_apply": [], "checks": []}')
    try:
        load_translate_cases(p)
        raise AssertionError("should reject unknown expect_decision")
    except ValueError:
        pass


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "dup.jsonl"
    row = ('{"id": "same", "category": "c", "source": "s", "requirements": [],'
           ' "input": "x", "expect_decision": "noop", "must_apply": [],'
           ' "checks": []}\n')
    p.write_text(row + row)
    try:
        load_translate_cases(p)
        raise AssertionError("should reject duplicate ids")
    except ValueError:
        pass
