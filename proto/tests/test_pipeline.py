"""Pipeline write-path: user-batch extract then one consolidate."""

import json

from memtranslator import FakeLLM, MemoryStore
from memtranslator.pipeline import run_write_path


def _extract_resp(quote: str, turn: int):
    return json.dumps({"candidates": [{
        "requirement": f"Req from turn {turn}.",
        "polarity": "do",
        "scope_condition": "the user asks for help",
        "task_type": "general",
        "keywords": ["help"],
        "signal": "explicit_instruction",
        "quote": quote,
        "turn": turn,
        "expires_hint": None,
    }]})


def _consolidate_add(n: int):
    return json.dumps({"ops": [{"candidate_idx": i, "op": "ADD"} for i in range(n)]})


def test_write_path_batches_by_five_users(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    turns = []
    for i in range(6):
        turns.append({"role": "user", "text": f"please always do thing-{i}"})
        turns.append({"role": "assistant", "text": _assistant(f"Ack {i}")})

    # 6 users → 2 extract batches (5 + 1), then 1 consolidate
    llm = FakeLLM([
        _extract_resp("please always do thing-0", 0),
        _extract_resp("please always do thing-5", 10),
        _consolidate_add(2),
    ])
    applied = run_write_path(llm, turns, store, session_id="s-batch")
    assert len(llm.calls) == 3
    assert len(applied) == 2
    assert len(store.active()) == 2
    # Second batch must still carry global turn indices into the extract prompt
    second_extract_user = llm.calls[1]["user"]
    assert "USER (turn 10): please always do thing-5" in second_extract_user


def _assistant(text: str) -> str:
    return f"title: {text}\nsubtitle: ok"


def test_write_path_string_transcript_single_extract(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    transcript = "USER (turn 0): always lint before commit\nASSISTANT (turn 1): title: ok"
    llm = FakeLLM([
        _extract_resp("always lint before commit", 0),
        _consolidate_add(1),
    ])
    applied = run_write_path(llm, transcript, store, session_id="s-str")
    assert len(llm.calls) == 2
    assert len(applied) == 1
