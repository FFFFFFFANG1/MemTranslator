"""Thin Anthropic client. Lazy so tests never need a key; tests monkeypatch
`complete` and `stream_text` at module level.

Network failures (this machine reaches Anthropic through a local proxy that
can flap) surface as LLMUnavailable so endpoints can answer with an explicit,
user-facing state instead of a bare 500."""
from collections.abc import Iterator

import anthropic

_client: anthropic.Anthropic | None = None


class LLMUnavailable(Exception):
    """The model endpoint could not be reached (network/proxy down)."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def complete(model: str, system: str, user: str, max_tokens: int = 1024,
             temperature: float | None = None) -> str:
    """One-shot completion. `temperature=None` leaves the SDK default (1.0);
    product paths pass an explicit value — see config.GEN_TEMPERATURE."""
    extra = {} if temperature is None else {"temperature": temperature}
    try:
        resp = _get_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            **extra,
        )
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("connection") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"status:{e.status_code}") from e
    return "".join(b.text for b in resp.content if b.type == "text")


def stream_text(model: str, system: str, messages: list[dict],
                max_tokens: int = 2048) -> Iterator[str]:
    try:
        with _get_client().messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            yield from stream.text_stream
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("connection") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"status:{e.status_code}") from e
