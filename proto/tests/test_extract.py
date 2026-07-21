import json

from memtranslator import FakeLLM, MemoryStore
from memtranslator.extract import extract

TRANSCRIPT = """USER (turn 0): 帮我总结这篇论文。
ASSISTANT (turn 1): （总结了论文）
USER (turn 2): 我不是要总结，我要你分析它的问题，和相关工作比一比。
ASSISTANT (turn 3): （批判性分析）"""


def _resp(candidates):
    return json.dumps({"candidates": candidates}, ensure_ascii=False)


def good_candidate(**over):
    c = {
        "requirement": "When analyzing papers, critique problems and compare against related work.",
        "polarity": "do",
        "scope_condition": "the user asks to analyze a research paper",
        "task_type": "research.paper-review",
        "keywords": ["paper", "analysis"],
        "signal": "next_turn_feedback",
        "quote": "我不是要总结，我要你分析它的问题",
        "turn": 2,
        "expires_hint": None,
    }
    c.update(over)
    return c


def test_extracts_valid_candidate(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    got = extract(FakeLLM([_resp([good_candidate()])]), TRANSCRIPT, store)
    assert len(got) == 1
    assert got[0].signal == "next_turn_feedback"
    assert not store.quarantine_path.exists()


def test_paraphrased_quote_is_discarded(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    got = extract(FakeLLM([_resp([good_candidate(quote="用户说不要总结要分析")])]), TRANSCRIPT, store)
    assert got == []
    assert "quote not verbatim" in store.quarantine_path.read_text()


def test_quote_check_tolerates_whitespace_reflow(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    got = extract(FakeLLM([_resp([good_candidate(quote="我不是要总结，\n我要你分析它的问题")])]),
                  TRANSCRIPT, store)
    assert len(got) == 1


def test_unparseable_output_quarantines_and_returns_empty(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    got = extract(FakeLLM(["I found some interesting requirements!"]), TRANSCRIPT, store)
    assert got == []
    assert "unparseable" in store.quarantine_path.read_text()


def test_empty_candidates_is_normal_no_quarantine(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    assert extract(FakeLLM([_resp([])]), TRANSCRIPT, store) == []
    assert not store.quarantine_path.exists()


def test_invalid_signal_discarded_others_kept(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    got = extract(FakeLLM([_resp([good_candidate(signal="vibes"), good_candidate()])]), TRANSCRIPT, store)
    assert len(got) == 1


def test_candidate_cap_at_eight(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    got = extract(FakeLLM([_resp([good_candidate() for _ in range(12)])]), TRANSCRIPT, store)
    assert len(got) == 8
