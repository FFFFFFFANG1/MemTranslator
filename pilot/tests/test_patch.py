from pilot.translator import apply_patch, parse_patch

INST = {"request": "original request", "content": "MATERIAL"}


def test_noop_keeps_original():
    assert apply_patch(INST, {"decision": "noop"}) == "original request"


def test_apply_replaces_request_only():
    p = {"decision": "apply", "applied_memory_ids": ["m2"],
         "new_request": "better request"}
    assert apply_patch(INST, p) == "better request"


def test_malformed_json_falls_back_to_noop():
    patch, err = parse_patch("not json at all")
    assert patch == {"decision": "noop"} and err is True


def test_fenced_json_ok():
    patch, err = parse_patch(
        '```json\n{"decision": "apply", "applied_memory_ids": ["m1"], '
        '"new_request": "x"}\n```')
    assert patch["decision"] == "apply" and err is False


def test_apply_without_new_request_is_noop():
    patch, err = parse_patch('{"decision": "apply"}')
    assert patch == {"decision": "noop"} and err is True
