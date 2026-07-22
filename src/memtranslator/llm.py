"""Thin Anthropic client. Lazy so tests never need a key; tests monkeypatch
`complete` and `stream_text` at module level."""
from collections.abc import Iterator

import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def complete(model: str, system: str, user: str, max_tokens: int = 1024) -> str:
    resp = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def stream_text(model: str, system: str, messages: list[dict],
                max_tokens: int = 2048) -> Iterator[str]:
    with _get_client().messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        yield from stream.text_stream
