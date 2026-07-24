"""Case-level retry for transient channel failures — the local Anthropic
proxy flaps, and one blip must not kill a whole run. Backoff 5/15/45s,
then re-raise so a genuinely dead channel still fails loudly."""
import time

import httpx

from memtranslator.llm import LLMUnavailable


def with_retry(fn, label: str):
    for attempt in range(4):
        try:
            return fn()
        except (LLMUnavailable, httpx.HTTPError):
            if attempt == 3:
                raise
            wait = 5 * 3 ** attempt
            print(f"{label}: channel unavailable, retry in {wait}s",
                  flush=True)
            time.sleep(wait)
