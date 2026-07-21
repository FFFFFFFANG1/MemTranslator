"""Live-API smoke test of the full loop on the idea.md paper-analysis example.

Skipped unless ANTHROPIC_API_KEY is set. One run costs a few flash-tier calls.
"""

import os

import pytest

from memtranslator import AnthropicLLM, MemoryStore, run_translate, run_write_path

pytestmark = pytest.mark.skipif("ANTHROPIC_API_KEY" not in os.environ,
                                reason="needs ANTHROPIC_API_KEY")

FEEDBACK_SESSION = """USER (turn 0): 帮我总结一下这篇 memory 系统的论文。
ASSISTANT (turn 1): 这篇论文提出了一个分层记忆架构，主要贡献是……（顺着论文总结了一遍）
USER (turn 2): 我不是要你总结，我要你分析它的问题：novelty 到底在哪，和 Mem0、Zep 这些比差异是什么，实验能不能支撑结论。以后看论文都按这个来。
ASSISTANT (turn 3): 明白了。批判性来看：该文的检索层与 Mem0 的差异主要是……"""


def test_full_loop_feedback_to_translation(tmp_path):
    store = MemoryStore(tmp_path / "mem.jsonl")
    llm = AnthropicLLM()

    applied = run_write_path(llm, FEEDBACK_SESSION, store, session_id="smoke-1")
    ops = [op.op for _, op in applied]
    assert store.active(), f"write path produced no active memory (ops={ops})"

    t = run_translate(llm, "帮我看看这篇论文", store,
                      content="# Paper: Yet Another Memory System\n...")
    # The polished request must surface the critical-analysis requirement
    # while keeping the attached content byte-identical.
    assert not t.noop, f"translator noop'd; rationale={t.rationale}"
    assert t.polished_input.endswith("# Paper: Yet Another Memory System\n..."), "content must be preserved"
    assert t.polished_request != t.original_request

    unrelated = run_translate(llm, "把这段话翻译成英文：你好世界", store)
    assert unrelated.noop, f"expected noop on unrelated request, got: {unrelated.polished_request}"
