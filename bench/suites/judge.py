"""One criterion, one call, one binary verdict. Fail-closed: anything that
does not parse to a clean yes counts as no and raises a parse flag, which the
report surfaces — a noisy judge must be visible, never silently generous.

Rides the OpenAI-compatible channel from the repo-root .env (2026-07-24
sign-off: deepseek-v4-pro via Volcano Ark). thinking disabled — the criteria
are deliberately narrow; reasoning tokens only add cost and latency. httpx is
already a dev-group dependency, so no SDK is added."""
import json

import httpx

from bench.suites.config import (JUDGE_MAX_TOKENS, JUDGE_MODEL, LLM_API_KEY,
                                 LLM_BASE_URL)
from bench.suites.ratelimit import JUDGE_BUCKET, JUDGE_SPACER
from bench.suites.retry import with_retry

JUDGE_SYSTEM = """You are a strict binary judge for a rewrite-quality benchmark.
You get a CRITERION and a CONTEXT (JSON). Decide whether the criterion holds.
Judge only what the criterion asks; do not reward extra qualities.
Answer with exactly one JSON object, nothing else:
{"verdict": "yes"|"no", "reason": "<one short sentence>"}"""

_client: httpx.Client | None = None


def _complete(system: str, user: str) -> str:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=120)
    JUDGE_BUCKET.acquire()
    JUDGE_SPACER.acquire()
    resp = _client.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json={"model": JUDGE_MODEL, "max_tokens": JUDGE_MAX_TOKENS,
              "temperature": 0, "thinking": {"type": "disabled"},
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]})
    if resp.status_code == 429:
        JUDGE_BUCKET.on_rate_limit()
    resp.raise_for_status()
    JUDGE_BUCKET.on_success()
    return resp.json()["choices"][0]["message"]["content"]


def judge(criterion: str, context: dict) -> tuple[bool, bool]:
    """Returns (ok, parse_flag). Retry lives HERE, at the call, not on the
    item that contains this call: an item-level retry re-runs every sibling
    LLM call in the shard, and at 35 calls/shard with 2% per-call failure the
    whole shard re-runs with probability ~51%."""
    user = (f"CRITERION:\n{criterion}\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=1)}")
    raw = with_retry(lambda: _complete(JUDGE_SYSTEM, user), "judge")
    s = raw.strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return False, True
    try:
        obj = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return False, True
    v = obj.get("verdict")
    if v not in ("yes", "no"):
        return False, True
    return v == "yes", False
