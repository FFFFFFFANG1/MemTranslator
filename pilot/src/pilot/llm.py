"""Thin LLM client. Every call in the pilot goes through call():
disk cache keyed by full input -> reproducible + resumable + free re-runs.

4xx errors (e.g. BadRequestError) are raised immediately — those are code
bugs, not transient faults. temperature/thinking are never sent (plan §1.2-5).
"""

from __future__ import annotations

import hashlib
import json
import time

import anthropic

from pilot.config import CACHE_DIR

_client = anthropic.Anthropic()


def call(model: str, user: str, system: str | None = None,
         max_tokens: int = 2048) -> dict:
    """Returns {"text", "input_tokens", "output_tokens", "cached"}."""
    key = hashlib.sha256(json.dumps(
        [model, system, user, max_tokens],
        ensure_ascii=False).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        out = json.loads(cache_file.read_text())
        out["cached"] = True
        return out
    last_err = None
    for attempt in range(4):
        try:
            kwargs = dict(model=model, max_tokens=max_tokens,
                          messages=[{"role": "user", "content": user}])
            if system is not None:
                kwargs["system"] = system
            resp = _client.messages.create(**kwargs)
            text = "".join(b.text for b in resp.content if b.type == "text")
            out = {"text": text,
                   "input_tokens": resp.usage.input_tokens,
                   "output_tokens": resp.usage.output_tokens}
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(out, ensure_ascii=False))
            out["cached"] = False
            return out
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as e:
            last_err = e
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"LLM call failed after retries: {last_err!r}")
