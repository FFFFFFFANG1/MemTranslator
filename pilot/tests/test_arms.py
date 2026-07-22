import pytest

from pilot.arms import build_downstream_call

INST = {"request": "Recommend a restaurant in Seattle.", "content": "",
        "memory_store": [{"mid": f"m{i}", "text": f"pref text {i}",
                          "topic": "t"} for i in range(1, 9)]}


def test_a0_clean():
    system, user = build_downstream_call("A0_none", INST)
    assert "pref text" not in system + user
    assert INST["request"] in user


def test_a1_memories_in_system_only():
    system, user = build_downstream_call("A1_system", INST)
    assert all(f"pref text {i}" in system for i in range(1, 9))
    assert "pref text" not in user


def test_a2_memories_in_user_only():
    system, user = build_downstream_call("A2_inject", INST)
    assert all(f"pref text {i}" in user for i in range(1, 9))
    assert "pref text" not in system


def test_a3_uses_polished_and_no_memories():
    system, user = build_downstream_call(
        "A3_translator", INST, polished_request="Recommend a vegan restaurant in Seattle.")
    assert "vegan" in user and "pref text" not in system + user


def test_content_appended_verbatim():
    inst = dict(INST, content="RAW-MATERIAL-XYZ do not touch")
    for arm, pol in [("A0_none", None), ("A3_translator", "rewritten req")]:
        _, user = build_downstream_call(arm, inst, polished_request=pol)
        assert "RAW-MATERIAL-XYZ do not touch" in user


def test_baseline_arm_uses_injected_block_not_oracle_store():
    system, user = build_downstream_call(
        "B1_mem0", INST, injected_block="Relevant memories about this user:\n- retrieved fact")
    assert "retrieved fact" in user
    assert "pref text" not in system + user  # oracle store must not leak


def test_baseline_arm_empty_block_is_clean_prompt():
    system, user = build_downstream_call("B2_graphiti", INST, injected_block="")
    assert user == INST["request"]
    assert "pref text" not in system + user


def test_baseline_arm_requires_block():
    with pytest.raises(ValueError):
        build_downstream_call("B1_mem0", INST)
