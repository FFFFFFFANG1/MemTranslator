"""Transient-failure handling for bench runs.

Two different failures look the same from here and must not be treated the
same. The local Anthropic proxy drops connections for a minute or two at a
time — retry and it comes back. The judge channel returns 429 when we push it
too hard — retrying at the same pace makes it worse, so that path backs off
much further and honours Retry-After when the server sends one.

Backoff is exponential with jitter. The jitter matters now that cases run
concurrently: without it every worker wakes at the same instant and
re-stampedes the endpoint that just rate-limited us.
"""
import random
import time

import httpx

from memtranslator.llm import LLMUnavailable

BASE_DELAY = 4.0
MAX_DELAY = 240.0
MAX_ATTEMPTS = 7          # ~4+8+16+32+64+128s of cover before giving up


def _retry_after(exc) -> float | None:
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    raw = resp.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _is_rate_limit(exc) -> bool:
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code == 429


def backoff_delay(attempt: int, rate_limited: bool = False) -> float:
    """Exponential with full jitter; rate limits start a rung higher."""
    ceiling = min(MAX_DELAY, BASE_DELAY * (2 ** attempt))
    if rate_limited:
        ceiling = min(MAX_DELAY, ceiling * 2)
    return random.uniform(ceiling / 2, ceiling)


def with_retry(fn, label: str):
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except (LLMUnavailable, httpx.HTTPError) as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            limited = _is_rate_limit(exc)
            wait = _retry_after(exc) or backoff_delay(attempt, limited)
            why = "rate limited" if limited else "channel unavailable"
            print(f"{label}: {why}, retry in {wait:.0f}s "
                  f"(attempt {attempt + 1}/{MAX_ATTEMPTS})", flush=True)
            time.sleep(wait)
