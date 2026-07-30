"""Thin LLM client. Lazy so tests never need a key; tests monkeypatch
`complete` and `stream_text` at module level.

Two channels, routed by model id (2026-07-30 owner directive: test runs use
OpenRouter's ling flash): ids containing "/" (OpenRouter naming, e.g.
"inclusionai/ling-3.0-flash:free") go over the OpenAI-compatible endpoint
with OPENROUTER_API_KEY; bare ids stay on the Anthropic SDK. Streaming
remains Anthropic-only (product server path; nothing routed to OpenRouter
streams today).

Network failures (this machine reaches providers through a local proxy that
can flap) surface as LLMUnavailable so endpoints can answer with an explicit,
user-facing state instead of a bare 500."""
import os
from collections.abc import Iterator

import anthropic
import httpx

_client: anthropic.Anthropic | None = None
_or_client: httpx.Client | None = None

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Reasoning is OFF by default on this channel. Measured on ling-3.0-flash:
# the model spends 1000-1200 reasoning tokens on every call regardless of
# prompt size, OpenRouter bills them against max_tokens, and our output
# floor is 1024 — so the budget is exhausted before a single content token
# is emitted (finish_reason=length, empty content) even on a 900-token
# prompt. Backbone evaluations flip this flag; the product does not.
OPENROUTER_REASONING = False


class LLMUnavailable(Exception):
    """The model endpoint could not be reached (network/proxy down)."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _openrouter_complete(model: str, system: str, user: str,
                         max_tokens: int, temperature: float | None) -> str:
    global _or_client
    if _or_client is None:
        _or_client = httpx.Client(timeout=120)
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise LLMUnavailable("OPENROUTER_API_KEY not set")
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    if not OPENROUTER_REASONING:
        payload["reasoning"] = {"enabled": False}
    if temperature is not None:
        payload["temperature"] = temperature
    try:
        resp = _or_client.post(f"{OPENROUTER_BASE}/chat/completions",
                               headers={"Authorization": f"Bearer {key}"},
                               json=payload)
    except httpx.HTTPError as e:
        raise LLMUnavailable("connection") from e
    if resp.status_code != 200:
        # Keep the server's explanation — a bare status once sent a session
        # chasing a prompt bug when the cause was quota.
        raise LLMUnavailable(
            f"status:{resp.status_code} {resp.text[:200]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LLMUnavailable(f"malformed response {str(data)[:200]}") from e


def complete(model: str, system: str, user: str, max_tokens: int = 1024,
             temperature: float | None = None) -> str:
    """One-shot completion. `temperature=None` leaves the SDK default (1.0);
    product paths pass an explicit value — see config.GEN_TEMPERATURE."""
    if "/" in model:
        return _openrouter_complete(model, system, user, max_tokens,
                                    temperature)
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
        # Keep the server's explanation: "400" alone sent a debugging session
        # chasing a prompt bug when the real cause was an exhausted balance.
        detail = getattr(getattr(e, "body", None), "get", lambda _k: None)("error")
        why = (detail or {}).get("message") if isinstance(detail, dict) else None
        raise LLMUnavailable(
            f"status:{e.status_code} {why or str(e)[:200]}") from e
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
        # Keep the server's explanation: "400" alone sent a debugging session
        # chasing a prompt bug when the real cause was an exhausted balance.
        detail = getattr(getattr(e, "body", None), "get", lambda _k: None)("error")
        why = (detail or {}).get("message") if isinstance(detail, dict) else None
        raise LLMUnavailable(
            f"status:{e.status_code} {why or str(e)[:200]}") from e
