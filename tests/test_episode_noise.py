"""Guards for the deterministic OASST1-expanded E1 corpus."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from bench.suites.build_noise_pool import select_rows
from bench.suites.expand_episode_noise import expand_episode


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "bench" / "cases" / "episodes"
NOISY = ROOT / "bench" / "cases" / "episodes-noisy"
POOL = ROOT / "bench" / "cases" / "noise" / "oasst1-root-prompts.jsonl"


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _seq_mapping(base: dict, noisy: dict) -> dict[int, int]:
    """Locate each authored turn in the expanded ordered subsequence."""
    mapping = {}
    cursor = 0
    for source in base["user_turns"]:
        while (cursor < len(noisy["user_turns"])
               and noisy["user_turns"][cursor]["user_input"]
               != source["user_input"]):
            cursor += 1
        assert cursor < len(noisy["user_turns"]), (base["id"], source["seq"])
        mapping[source["seq"]] = noisy["user_turns"][cursor]["seq"]
        assert noisy["user_turns"][cursor] == {
            **source, "seq": noisy["user_turns"][cursor]["seq"]}
        cursor += 1
    return mapping


def test_noise_pool_is_fixed_bilingual_and_unique():
    rows = [json.loads(line) for line in POOL.read_text().splitlines()]
    assert Counter(row["lang"] for row in rows) == {"en": 4096, "zh": 800}
    assert all(set(row) == {"id", "lang", "text"} for row in rows)
    assert all(row["id"].startswith("oasst1:") for row in rows)
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["text"].casefold() for row in rows}) == len(rows)
    assert all(12 <= len(row["text"]) <= 500 for row in rows)


def test_noise_selector_uses_structure_labels_and_stable_order():
    def row(message_id: str, text: str, **overrides) -> dict:
        value = {
            "message_id": message_id, "text": text, "lang": "en",
            "role": "prompter", "parent_id": None, "review_result": True,
            "deleted": False, "synthetic": False, "labels": {},
        }
        value.update(overrides)
        return value

    rows = [
        row("keep-a", "Explain why leaves change colour."),
        row("keep-b", "Give me a simple pasta recipe."),
        row("assistant", "This must not pass the role filter.", role="assistant"),
        row("child", "This must not pass the root filter.", parent_id="p"),
        row("spam", "This must not pass the label filter.",
            labels={"spam": {"value": 1}}),
    ]
    first = select_rows(rows, caps={"en": 2}, max_chars=500)
    second = select_rows(reversed(rows), caps={"en": 2}, max_chars=500)
    assert first == second
    assert {item["id"] for item in first} == {
        "oasst1:keep-a", "oasst1:keep-b"}


def test_expander_is_deterministic_and_remaps_evaluator_sequences():
    episode = {
        "id": "e-test", "protocol_version": 3,
        "user_turns": [
            {"seq": 1, "user_input": "first authored turn"},
            {"seq": 2, "user_input": "second authored turn",
             "probe": {"should_apply": ["c1"], "must_not_apply": []}},
            {"seq": 3, "user_input": "third authored turn"},
        ],
        "ground_truth": {
            "requirements": [{"id": "c1"}],
            "lifecycle": [{"seq": 1, "op": "assert", "id": "c1"}],
            "state_checkpoints": [2, 3],
        },
    }
    pool = {"en": [
        {"id": f"n{i}", "lang": "en", "text": f"ordinary prompt {i}"}
        for i in range(30)]}
    first, manifest = expand_episode(
        episode, pool, seed=7, min_noise=5, max_noise=10)
    second, _ = expand_episode(
        episode, pool, seed=7, min_noise=5, max_noise=10)
    assert first == second
    mapping = _seq_mapping(episode, first)
    assert 5 <= mapping[2] - mapping[1] - 1 <= 10
    assert 5 <= mapping[3] - mapping[2] - 1 <= 10
    assert first["ground_truth"]["lifecycle"][0]["seq"] == mapping[1]
    assert first["ground_truth"]["state_checkpoints"] == [
        mapping[2], mapping[3]]
    assert manifest["noise_turns"] == len(first["user_turns"]) - 3


def test_checked_in_noisy_corpus_preserves_authored_semantics_and_gap_size():
    manifest = _json(NOISY / "noise_manifest.json")
    assert manifest["source"] == "OpenAssistant/oasst1"
    assert manifest["source_revision"] == (
        "fdf72ae0827c1cda404aff25b6603abec9e3399b")
    assert manifest["license"] == "Apache-2.0"
    assert manifest["seed"] == 20260820
    assert manifest["min_noise"] == 5
    assert manifest["max_noise"] == 10

    for base_path in sorted(BASE.glob("e-*.json")):
        base = _json(base_path)
        noisy = _json(NOISY / base_path.name)
        mapping = _seq_mapping(base, noisy)
        assert noisy["ground_truth"]["requirements"] == (
            base["ground_truth"]["requirements"])
        assert [turn["seq"] for turn in noisy["user_turns"]] == list(
            range(1, len(noisy["user_turns"]) + 1))
        for previous, following in zip(
                base["user_turns"], base["user_turns"][1:]):
            gap = mapping[following["seq"]] - mapping[previous["seq"]] - 1
            assert 5 <= gap <= 10
        assert all(set(turn) == {"seq", "user_input"}
                   for turn in noisy["user_turns"]
                   if turn["seq"] not in mapping.values())

        expected_lifecycle = [
            {**effect, "seq": mapping[effect["seq"]]}
            for effect in base["ground_truth"]["lifecycle"]]
        assert noisy["ground_truth"]["lifecycle"] == expected_lifecycle
        assert noisy["ground_truth"]["state_checkpoints"] == [
            mapping[seq]
            for seq in base["ground_truth"]["state_checkpoints"]]
