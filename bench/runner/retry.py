"""Case-level retry for transient channel failures — the local Anthropic
proxy flaps, and one blip must not kill a whole run. Observed flaps last up
to a couple of minutes, so back off 5/15/45/120s (~3min of cover) before
re-raising so a genuinely dead channel still fails loudly."""
import time

import httpx

from memtranslator.llm import LLMUnavailable

_WAITS = (5, 15, 45, 120)


def with_retry(fn, label: str):
    for attempt in range(len(_WAITS) + 1):
        try:
            return fn()
        except (LLMUnavailable, httpx.HTTPError):
            if attempt == len(_WAITS):
                raise
            wait = _WAITS[attempt]
            print(f"{label}: channel unavailable, retry in {wait}s",
                  flush=True)
            time.sleep(wait)
