"""The oracle runner has one deterministic, write-free input protocol."""
import json

import bench.suites.run_oracle as oracle


def _episode():
    return {
        "id": "e-test", "protocol_version": 3,
        "user_turns": [
            {"seq": 1, "user_input": "not a probe"},
            {"seq": 2, "user_input": "write a report",
             "probe": {"should_apply": ["c0"],
                       "must_not_apply": []}},
        ],
        "ground_truth": {
            "requirements": [{
                "id": "c0", "text": "Use bullets.",
                "paraphrase": "Use a bulleted list.", "anchor": "bullets",
                "bucket": "output_contract", "scope_mode": "scoped",
                "applies_when": None, "work_kinds": ["report"],
                "key": "format.list", "confidence": 9,
            }],
            "lifecycle": [{"seq": 1, "op": "assert", "id": "c0"}],
            "state_checkpoints": [],
        },
    }


def test_score_round_supplies_no_chain_state(monkeypatch):
    seen = {}

    def fake_score(ep, row, arm, by_cid):
        seen.update({"ep": ep, "row": row, "arm": arm,
                     "by_cid": by_cid})
        return {"arm": arm, "seq": row["round"]["seq"],
                "carry_hits": 1, "carry_n": 1,
                "suppress_hits": 0, "suppress_n": 0,
                "carry_detail": [],
                "translator": {"decision": "apply"}}

    monkeypatch.setattr(oracle, "score_probe", fake_score)
    scored = oracle._score_round(_episode(), _episode()["user_turns"][1])

    assert seen["arm"] == "oracle"
    assert seen["row"]["store_state"] == []
    assert seen["row"]["transcript"] == []
    assert seen["row"]["pending_raw"] == []
    assert scored["episode"] == "e-test"


def test_run_oracle_reports_pooled_owner_metrics_without_trace(monkeypatch):
    def fake_score(ep, round_):
        hit = round_["seq"] == 2
        return {"episode": ep["id"], "arm": "oracle",
                "seq": round_["seq"],
                "carry_hits": int(hit), "carry_n": 1,
                "suppress_hits": 0, "suppress_n": 0,
                "carry_detail": [{"judge_parse_flag": False}],
                "translator": {"decision": "apply"}}

    ep = _episode()
    ep["user_turns"].append({
        "seq": 3, "user_input": "write another report",
        "probe": {"should_apply": ["c0"], "must_not_apply": []},
    })
    monkeypatch.setattr(oracle, "_score_round", fake_score)

    result = oracle.run_oracle([ep], workers=1, save_trace=False)

    assert result["pooled"] == {
        "accuracy": 0.5, "memory_hit": 1, "memory_n": 2,
        "per_task": 0.5, "tasks_perfect": 1, "tasks_n": 2,
    }
    assert result["oracle_protocol"]["memory"] == \
        "exactly turn.probe.should_apply golden items with authored attributes"
    assert result["oracle_protocol"]["round_attributes_visible_to_translator"] \
        is False
    assert result["oracle_protocol"]["catalogue_metadata_on_memory"] is True
    assert "probe_trace" not in result["results"][0]


def test_oracle_snapshot_persists_protocol(tmp_path, monkeypatch):
    monkeypatch.setattr(oracle, "RESULTS", tmp_path)
    payload = {"suite": "E1-oracle", "score": 1.0,
               "model": "ark:test-model",
               "oracle_protocol": dict(oracle.ORACLE_PROTOCOL)}

    path = oracle.write_oracle_snapshot(payload)
    saved = json.loads(path.read_text())

    assert path.name.startswith("E1-oracle-ark-test-model-")
    assert saved["oracle_protocol"]["version"] == \
        oracle.ORACLE_PROTOCOL["version"]
