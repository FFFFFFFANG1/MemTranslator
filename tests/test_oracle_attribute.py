"""Offline guards for the one-item GLM golden-attribute annotator."""
import json

import pytest

import bench.suites.oracle_attribute as attr


def _episode():
    return {
        "id": "e-test",
        "protocol_version": 3,
        "user_turns": [
            {"seq": 1, "user_input": "From now on, keep every reply short."},
            {"seq": 2, "user_input": "For reports, cite the source."},
            {"seq": 3, "user_input": "Reports no longer need citations; use an appendix instead."},
        ],
        "ground_truth": {
            "requirements": [
                {"id": "c0", "text": "Keep every reply short.",
                 "paraphrase": "All replies must be concise.",
                 "anchor": "short"},
                {"id": "c1", "text": "Cite sources in reports.",
                 "paraphrase": "Reports need citations.",
                 "anchor": "sources"},
                {"id": "s0", "text": "Use an appendix in reports.",
                 "paraphrase": "Reports need an appendix.",
                 "anchor": "appendix"},
            ],
            "lifecycle": [
                {"seq": 1, "op": "assert", "id": "c0"},
                {"seq": 2, "op": "assert", "id": "c1"},
                {"seq": 3, "op": "contradict", "id": "s0",
                 "target": "c1"},
            ],
            "state_checkpoints": [],
        },
    }


def test_jobs_use_the_exact_lifecycle_introduction_turn():
    jobs = attr.annotation_jobs([_episode()])

    assert [(job.item_id, job.source_seq, job.source_message)
            for job in jobs] == [
        ("c0", 1, "From now on, keep every reply short."),
        ("c1", 2, "For reports, cite the source."),
        ("s0", 3,
         "Reports no longer need citations; use an appendix instead."),
    ]


def test_jobs_reject_missing_or_ambiguous_introduction():
    missing = _episode()
    missing["ground_truth"]["lifecycle"] = []
    with pytest.raises(ValueError, match="exactly one introduction"):
        attr.annotation_jobs([missing])

    duplicate = _episode()
    duplicate["ground_truth"]["lifecycle"].append(
        {"seq": 2, "op": "assert", "id": "c0"})
    with pytest.raises(ValueError, match="exactly one introduction"):
        attr.annotation_jobs([duplicate])


def test_parse_annotation_uses_extractor_contract_and_preserves_gold_text():
    job = attr.annotation_jobs([_episode()])[0]
    raw = json.dumps([{
        "decision": "candidate",
        "kind": "potential_new",
        "change_mode": None,
        "item": {
            "text": "The model rewrote this, but it must not reach gold.",
            "bucket": "output_contract",
            "scope_mode": "global",
            "applies_when": None,
            "work_kinds": ["all"],
            "key": "length.max",
            "confidence": 9,
        },
        "target_query": None,
        "sources": [1],
    }])

    parsed = attr.parse_annotation(raw, job)

    assert parsed == {
        "bucket": "output_contract",
        "scope_mode": "global",
        "applies_when": None,
        "work_kinds": ["all"],
        "key": "length.max",
        "confidence": 9,
    }


def test_parse_annotation_rejects_invalid_or_multiple_candidates():
    job = attr.annotation_jobs([_episode()])[0]
    invalid = json.dumps([{
        "decision": "candidate", "kind": "potential_new",
        "change_mode": None,
        "item": {"text": job.text, "bucket": "output_contract",
                 "scope_mode": "scoped", "applies_when": None,
                 "work_kinds": ["all"], "key": "length.max",
                 "confidence": 8},
        "target_query": None, "sources": [1],
    }])
    with pytest.raises(ValueError, match="scoped with work_kinds all"):
        attr.parse_annotation(invalid, job)

    valid = json.dumps([{
        "decision": "candidate", "kind": "potential_new",
        "change_mode": None,
        "item": {"text": job.text, "bucket": "output_contract",
                 "scope_mode": "global", "applies_when": None,
                 "work_kinds": ["all"], "key": "length.max",
                 "confidence": 8},
        "target_query": None, "sources": [1],
    }] * 2)
    with pytest.raises(ValueError, match="exactly one candidate"):
        attr.parse_annotation(valid, job)


def test_apply_annotations_adds_only_extractor_item_attributes():
    episode = _episode()
    records = {
        "e-test:c0": {
            "fingerprint": attr.annotation_jobs([episode])[0].fingerprint,
            "attributes": {
                "bucket": "output_contract", "scope_mode": "global",
                "applies_when": None, "work_kinds": ["all"],
                "key": "length.max", "confidence": 9,
            },
        },
    }

    changed = attr.apply_annotations([episode], records, require_complete=False)

    assert changed == 1
    assert episode["ground_truth"]["requirements"][0] == {
        "id": "c0", "text": "Keep every reply short.",
        "paraphrase": "All replies must be concise.", "anchor": "short",
        "bucket": "output_contract", "scope_mode": "global",
        "applies_when": None, "work_kinds": ["all"],
        "key": "length.max", "confidence": 9,
    }
    assert set(episode["ground_truth"]["requirements"][1]) == {
        "id", "text", "paraphrase", "anchor"}
