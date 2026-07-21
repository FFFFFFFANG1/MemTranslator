"""Transcript compression and user-batch slicing for the write-path extract step.

Storage rules (applied before extract sees the transcript):
- user turns: full text; if >2000 tokens, keep head 1000 + tail 1000
- assistant turns: title + subtitle only; if >1000 tokens, also keep head 500 + tail 500

Extract runs in user-batches of USER_BATCH_SIZE (default 5): each batch is one
LLM call covering up to that many user turns and their interleaved assistant replies.

Token counts use tiktoken (cl100k_base). Claude's native tokenizer differs slightly;
this is close enough for storage budgets and avoids an API round-trip.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterator, Mapping, Sequence

import tiktoken

USER_BATCH_SIZE = 5
USER_FULL_TOKEN_LIMIT = 2000
USER_HEAD_TOKENS = 1000
USER_TAIL_TOKENS = 1000
ASSISTANT_FULL_TOKEN_LIMIT = 1000
ASSISTANT_HEAD_TOKENS = 500
ASSISTANT_TAIL_TOKENS = 500

# Proxy for Claude context budgets; not Anthropic's exact tokenizer.
_ENCODING_NAME = "cl100k_base"


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoding().encode(text))


# Back-compat alias used by tests / callers.
estimate_tokens = count_tokens


def take_prefix_tokens(text: str, n: int) -> str:
    if n <= 0 or not text:
        return ""
    enc = _encoding()
    ids = enc.encode(text)
    if len(ids) <= n:
        return text
    return enc.decode(ids[:n])


def take_suffix_tokens(text: str, n: int) -> str:
    if n <= 0 or not text:
        return ""
    enc = _encoding()
    ids = enc.encode(text)
    if len(ids) <= n:
        return text
    return enc.decode(ids[-n:])


def head_tail(text: str, head: int, tail: int) -> str:
    """Keep head+tail token windows; if text fits in head+tail, keep it whole."""
    enc = _encoding()
    ids = enc.encode(text)
    if len(ids) <= head + tail:
        return text
    return f"{enc.decode(ids[:head])}\n...\n{enc.decode(ids[-tail:])}"


def derive_title_subtitle(text: str) -> tuple[str, str]:
    """Mechanical title/subtitle from the first two non-empty lines (no LLM)."""
    lines: list[str] = []
    for ln in text.splitlines():
        s = ln.strip().lstrip("#").strip()
        if s:
            lines.append(s)
    title = lines[0][:160] if lines else "(empty reply)"
    subtitle = lines[1][:240] if len(lines) > 1 else ""
    return title, subtitle


def compress_user(text: str) -> str:
    if count_tokens(text) <= USER_FULL_TOKEN_LIMIT:
        return text
    return head_tail(text, USER_HEAD_TOKENS, USER_TAIL_TOKENS)


def compress_assistant(text: str) -> str:
    title, subtitle = derive_title_subtitle(text)
    parts = [f"title: {title}"]
    if subtitle:
        parts.append(f"subtitle: {subtitle}")
    if count_tokens(text) > ASSISTANT_FULL_TOKEN_LIMIT:
        parts.append(head_tail(text, ASSISTANT_HEAD_TOKENS, ASSISTANT_TAIL_TOKENS))
    return "\n".join(parts)


def compress_turn(role: str, text: str) -> str:
    if role == "user":
        return compress_user(text)
    if role == "assistant":
        return compress_assistant(text)
    return text


def format_transcript(turns: Sequence[Mapping[str, Any]]) -> str:
    """Render turns for extract. Uses turn['index'] when present (global id)."""
    lines: list[str] = []
    for i, turn in enumerate(turns):
        idx = turn["index"] if "index" in turn else i
        role = str(turn["role"]).upper()
        lines.append(f"{role} (turn {idx}): {turn['text']}")
    return "\n".join(lines)


def with_indices(turns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, turn in enumerate(turns):
        row = dict(turn)
        row.setdefault("index", i)
        out.append(row)
    return out


def iter_user_batches(
    turns: Sequence[Mapping[str, Any]],
    batch_size: int = USER_BATCH_SIZE,
) -> Iterator[list[dict[str, Any]]]:
    """Yield consecutive slices each containing up to `batch_size` user turns
    (plus any interleaved assistant turns that follow them)."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    indexed = with_indices(turns)
    batch: list[dict[str, Any]] = []
    n_users = 0
    for turn in indexed:
        if turn.get("role") == "user":
            if n_users == batch_size and batch:
                yield batch
                batch = []
                n_users = 0
            n_users += 1
        batch.append(turn)
    if batch:
        yield batch
