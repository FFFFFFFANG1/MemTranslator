"""Generation-channel LLM helper (deepseek-v4-flash over Ark).

The payload shape mirrors judge.py deliberately: Ark models default to
THINKING ON, and reasoning tokens silently eat small max_tokens budgets — the
response comes back with empty content and finish_reason=stop, which looks
exactly like a prompt bug. `thinking: disabled` is mandatory on every call on
this channel (measured 2026-07-28: 23-44 reasoning tokens on a one-word
reply)."""
import json

import httpx

from bench.runner.config import GEN_MODEL, LLM_API_KEY, LLM_BASE_URL
from bench.runner.ratelimit import AIMDBucket
from bench.runner.retry import with_retry

GEN_BUCKET = AIMDBucket(rate=4.0, burst=8.0)

_client: httpx.Client | None = None


def _post(system: str, user: str, max_tokens: int, temperature: float,
          model: str) -> str:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=120)
    GEN_BUCKET.acquire()
    resp = _client.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json={"model": model, "max_tokens": max_tokens,
              "temperature": temperature, "thinking": {"type": "disabled"},
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]})
    if resp.status_code == 429:
        GEN_BUCKET.on_rate_limit()
    resp.raise_for_status()
    GEN_BUCKET.on_success()
    return resp.json()["choices"][0]["message"]["content"]


def flash(system: str, user: str, *, max_tokens: int = 800,
          temperature: float = 0.0, model: str = GEN_MODEL) -> str:
    return with_retry(lambda: _post(system, user, max_tokens, temperature,
                                    model), "gen")


def flash_json(system: str, user: str, *, max_tokens: int = 800,
               temperature: float = 0.0, model: str = GEN_MODEL):
    """One call, parsed to JSON. Returns None when the payload does not
    parse — callers treat that as a gate failure, never as data."""
    raw = flash(system, user, max_tokens=max_tokens,
                temperature=temperature, model=model)
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").removeprefix("json").strip()
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        start, end = s.find("["), s.rfind("]")
        if start < 0 or end <= start:
            return None
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return None
