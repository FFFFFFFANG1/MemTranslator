"""Deterministic guards for the minimal E1 v3 corpus protocol."""
import json
from pathlib import Path

from bench.graph.derive import fold
from bench.suites.run_episodes import _effects


EPISODES = Path(__file__).resolve().parents[1] / "bench" / "cases" / "episodes"


def _episodes():
    return [json.loads(path.read_text())
            for path in sorted(EPISODES.glob("e-*.json"))]


def test_episode_v3_contains_only_runtime_input_and_ground_truth():
    for ep in _episodes():
        assert set(ep) == {
            "id", "protocol_version", "user_turns", "ground_truth"}
        assert ep["protocol_version"] == 3
        assert set(ep["ground_truth"]) == {
            "requirements", "lifecycle", "state_checkpoints"}
        for node in ep["ground_truth"]["requirements"]:
            assert set(node) == {
                "id", "text", "paraphrase", "anchor", "bucket",
                "scope_mode", "applies_when", "work_kinds", "key",
                "confidence"}
            assert all(isinstance(node[key], str) and node[key]
                       for key in ("id", "text", "paraphrase", "anchor"))
            assert node["bucket"] in {
                "task_goal", "reasoning_policy", "deliverables",
                "output_contract", "communication_style",
                "execution_policy"}
            assert node["scope_mode"] in {"global", "scoped"}
            assert (node["applies_when"] is None
                    or isinstance(node["applies_when"], str)
                    and node["applies_when"])
            assert (isinstance(node["work_kinds"], list)
                    and all(isinstance(kind, str) and kind
                            for kind in node["work_kinds"]))
            assert isinstance(node["key"], str) and "." in node["key"]
            assert isinstance(node["confidence"], int)
            if node["scope_mode"] == "global":
                assert node["work_kinds"] == ["all"]
                assert node["applies_when"] is None
            if node["scope_mode"] == "scoped" \
                    and node["work_kinds"] == ["all"]:
                assert node["applies_when"]
        for turn in ep["user_turns"]:
            assert set(turn) <= {"seq", "user_input", "probe"}
            assert set(turn) >= {"seq", "user_input"}
            assert isinstance(turn["user_input"], str) and turn["user_input"]
            if "probe" in turn:
                assert set(turn["probe"]) == {
                    "should_apply", "must_not_apply"}
        shapes = {
            "assert": {"seq", "op", "id"},
            "contradict": {"seq", "op", "id", "target"},
            "retire": {"seq", "op", "target"},
            "reinforce": {"seq", "op", "target"},
        }
        for effect in ep["ground_truth"]["lifecycle"]:
            assert effect["op"] in shapes
            assert set(effect) == shapes[effect["op"]]


def test_every_probe_reference_exists_and_should_apply_is_live():
    for ep in _episodes():
        by_id = {node["id"]: node
                 for node in ep["ground_truth"]["requirements"]}
        for turn in (turn for turn in ep["user_turns"]
                     if turn.get("probe")):
            state = fold(_effects(ep), turn["seq"])
            expected = turn["probe"]
            for field in ("should_apply", "must_not_apply"):
                ids = expected[field]
                assert len(ids) == len(set(ids))
                assert all(cid in by_id for cid in ids)
            for cid in expected["should_apply"]:
                assert state[cid].status == "active", (
                    ep["id"], turn["seq"], cid, state[cid].status)


def test_lifecycle_and_checkpoints_reference_known_turns_and_requirements():
    for ep in _episodes():
        ids = {node["id"] for node in ep["ground_truth"]["requirements"]}
        seqs = {turn["seq"] for turn in ep["user_turns"]}
        assert [turn["seq"] for turn in ep["user_turns"]] == list(
            range(1, len(ep["user_turns"]) + 1))
        assert set(ep["ground_truth"]["state_checkpoints"]) <= seqs
        for effect in ep["ground_truth"]["lifecycle"]:
            assert effect["seq"] in seqs
            if "id" in effect:
                assert effect["id"] in ids
            if "target" in effect:
                assert effect["target"] in ids


def test_first_four_turns_are_an_unscored_cold_start_batch():
    for ep in _episodes():
        cold_start = ep["user_turns"][:4]
        assert len(cold_start) == 4
        assert all("probe" not in turn for turn in cold_start), ep["id"]


def test_known_conditional_false_positives_are_not_gold():
    by_episode = {ep["id"]: ep for ep in _episodes()}
    rejected = {
        ("e-01", 5, "e01-c01"),
        ("e-01", 10, "e01-c05"),
        ("e-01", 30, "e01-c24"), ("e-01", 40, "e01-c24"),
        ("e-01", 48, "e01-c31"), ("e-01", 52, "e01-s01"),
        ("e-02", 25, "e02-c24"), ("e-02", 30, "e02-c14"),
        ("e-03", 5, "e03-c02"), ("e-03", 28, "e03-c00"),
        ("e-03", 44, "e03-c14"), ("e-03", 44, "e03-s00"),
        ("e-03", 25, "e03-c24"),
        ("e-02", 44, "e02-s01"), ("e-06", 15, "e06-c05"),
        ("e-06", 20, "e06-c05"), ("e-06", 56, "e06-s04"),
        ("e-06", 40, "e06-c05"), ("e-07", 40, "e07-c26"),
        ("e-09", 24, "e09-c23"), ("e-10", 25, "e10-c21"),
        ("e-10", 35, "e10-c15"), ("e-11", 35, "e11-c21"),
        ("e-11", 35, "e11-c22"), ("e-11", 56, "e11-c28"),
        ("e-11", 61, "e11-s00"), ("e-08", 24, "e08-c23"),
        ("e-04", 20, "e04-c15"), ("e-04", 28, "e04-c03"),
        ("e-10", 20, "e10-c11"), ("e-10", 56, "e10-s01"),
        ("e-10", 59, "e10-c11"), ("e-10", 61, "e10-s02"),
        ("e-12", 10, "e12-c09"),
        # Attribute audit: the source explicitly narrows these to prose,
        # article/blog, while the probes ask for code/report/postmortem.
        ("e-01", 24, "e01-c21"),
        ("e-02", 60, "e02-s01"),
        ("e-06", 24, "e06-c16"),
        ("e-09", 60, "e09-s04"),
        ("e-11", 25, "e11-c22"),
        # "Reply to an email" is narrower than drafting a new email; an
        # incident email is not itself a postmortem/technical document.
        ("e-06", 25, "e06-c14"), ("e-06", 28, "e06-c14"),
        ("e-06", 35, "e06-c14"), ("e-06", 52, "e06-c14"),
        ("e-10", 20, "e10-c21"),
        ("e-12", 15, "e12-c12"), ("e-12", 35, "e12-c28"),
        ("e-12", 52, "e12-c19"), ("e-12", 61, "e12-c06"),
    }
    for episode_id, seq, cid in rejected:
        turn = next(turn for turn in by_episode[episode_id]["user_turns"]
                    if turn["seq"] == seq)
        assert cid not in turn["probe"]["should_apply"]


def test_deadline_weekday_restatement_is_reinforcement_not_successor():
    ep = next(ep for ep in _episodes() if ep["id"] == "e-12")
    lifecycle = [effect for effect in ep["ground_truth"]["lifecycle"]
                 if effect["seq"] == 45]
    weekday = next(effect for effect in lifecycle
                   if effect.get("target") == "e12-c18")
    assert weekday == {"seq": 45, "op": "reinforce", "target": "e12-c18"}

    seq48 = next(turn for turn in ep["user_turns"] if turn["seq"] == 48)
    assert "e12-c18" in seq48["probe"]["should_apply"]
    assert "e12-c18" not in seq48["probe"]["must_not_apply"]
