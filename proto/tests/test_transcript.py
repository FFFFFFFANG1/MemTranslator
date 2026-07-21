"""Tests for transcript compression and user-batch slicing."""

from memtranslator.transcript import (
    USER_BATCH_SIZE,
    _encoding,
    compress_assistant,
    compress_user,
    count_tokens,
    estimate_tokens,
    format_transcript,
    head_tail,
    iter_user_batches,
)


def _repeat_tokens(n: int, piece: str = "word ") -> str:
    """Build a string whose tiktoken length is at least n."""
    enc = _encoding()
    out = []
    while len(enc.encode("".join(out))) < n:
        out.append(piece)
    return "".join(out)


def test_count_tokens_chinese_ascii():
    assert count_tokens("") == 0
    assert count_tokens("hello") >= 1
    assert count_tokens("你好世界") >= 1
    assert estimate_tokens is count_tokens


def test_compress_user_keeps_short_text():
    text = "以后这种论文都要和相关工作做比较。"
    assert compress_user(text) == text


def test_compress_user_head_tail_when_over_2000():
    text = _repeat_tokens(2500)
    out = compress_user(text)
    assert out != text
    assert "\n...\n" in out
    assert count_tokens(out) < count_tokens(text)
    head, _, tail = out.partition("\n...\n")
    assert text.startswith(head[:20])
    assert text.endswith(tail[-20:])


def test_compress_assistant_short_is_title_subtitle_only():
    text = "Critical analysis\nNovelty vs Mem0 is thin.\nMore body that stays short."
    out = compress_assistant(text)
    assert out.startswith("title: Critical analysis")
    assert "subtitle: Novelty vs Mem0 is thin." in out
    assert "More body that stays short." not in out


def test_compress_assistant_long_adds_head_tail():
    body = _repeat_tokens(1500)
    text = f"Long reply title\nA short subtitle follows.\n{body}"
    out = compress_assistant(text)
    assert "title: Long reply title" in out
    assert "subtitle: A short subtitle follows." in out
    assert "\n...\n" in out


def test_head_tail_short_enough_returns_full():
    text = _repeat_tokens(600)
    assert head_tail(text, 400, 400) == text


def test_head_tail_long_inserts_ellipsis():
    text = _repeat_tokens(2000)
    out = head_tail(text, 400, 400)
    assert "\n...\n" in out
    head, _, tail = out.partition("\n...\n")
    assert count_tokens(head) == 400
    assert count_tokens(tail) == 400


def test_iter_user_batches_size_five():
    turns = []
    for i in range(12):
        turns.append({"role": "user", "text": f"u{i}"})
        turns.append({"role": "assistant", "text": f"a{i}"})
    batches = list(iter_user_batches(turns, batch_size=USER_BATCH_SIZE))
    assert len(batches) == 3  # 5 + 5 + 2
    assert sum(1 for t in batches[0] if t["role"] == "user") == 5
    assert sum(1 for t in batches[1] if t["role"] == "user") == 5
    assert sum(1 for t in batches[2] if t["role"] == "user") == 2
    assert batches[0][0]["index"] == 0
    assert batches[1][0]["index"] == 10


def test_format_transcript_uses_global_index():
    turns = [
        {"role": "user", "text": "hi", "index": 4},
        {"role": "assistant", "text": "title: x", "index": 5},
    ]
    s = format_transcript(turns)
    assert "USER (turn 4): hi" in s
    assert "ASSISTANT (turn 5): title: x" in s


def test_chinese_user_truncation():
    text = _repeat_tokens(2500, piece="测试内容")
    out = compress_user(text)
    assert "\n...\n" in out
    assert count_tokens(out) < count_tokens(text)
