"""Thin LLM layer. One protocol, one Anthropic implementation, one fake.

Write path and translator are all "prompt in, JSON out"; everything above
this file treats the model as a function str -> str and does its own parsing
with conservative failure handling (design §3.4).
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # flash-tier for write path + translator
DOWNSTREAM_MODEL = "claude-sonnet-5"          # demo downstream agent


class LLM(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_MODEL):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Models with extended thinking prepend non-text blocks; join text only.
        return "".join(b.text for b in resp.content if b.type == "text")


class FakeLLM:
    """Deterministic stand-in for tests: returns queued responses in order."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        self.calls.append({"system": system, "user": user})
        return self.responses.pop(0)


def parse_json_block(text: str) -> dict | list | None:
    """Parse a JSON object/array from model output, tolerating code fences
    and surrounding prose. Returns None if nothing parses — callers decide
    how to degrade; they never guess."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        return None
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    return None
