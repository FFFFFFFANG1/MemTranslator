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


def test_json_with_trailing_prose_parses():
    # observed in B2 dry-run: haiku appends an explanation after the JSON
    patch, err = parse_patch(
        '{"decision": "noop"}\n\nThe user is asking for suggestions...')
    assert patch == {"decision": "noop"} and err is False


def test_fenced_json_with_trailing_prose_parses():
    patch, err = parse_patch(
        '```json\n{"decision": "apply", "applied_memory_ids": ["m1"], '
        '"new_request": "x"}\n```\n\nExplanation: because...')
    assert patch["decision"] == "apply" and err is False


def test_braces_inside_strings_do_not_confuse_extractor():
    patch, err = parse_patch(
        '{"decision": "apply", "applied_memory_ids": [], '
        '"new_request": "use {curly} braces literally"}')
    assert patch["new_request"] == "use {curly} braces literally" and err is False
