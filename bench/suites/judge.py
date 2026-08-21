"""One criterion, one call, one binary verdict. Fail-closed: anything that
does not parse to a clean yes counts as no and raises a parse flag, which the
report surfaces — a noisy judge must be visible, never silently generous.

Rides the OpenAI-compatible channel from the repo-root .env. The default judge
is GLM-5.3 after a targeted false-negative audit; JUDGE_MODEL may override it.
GLM-5.x requires thinking and enough headroom for reasoning before its short
JSON answer. httpx is already a dev-group dependency, so no SDK is added."""
import json

import httpx

from bench.suites.config import (JUDGE_MAX_TOKENS, JUDGE_MODEL, LLM_API_KEY,
                                 LLM_BASE_URL)
from bench.suites.ratelimit import JUDGE_BUCKET, JUDGE_SPACER
from bench.suites.retry import with_retry

JUDGE_SYSTEM = """You are a strict binary judge for a rewrite-quality benchmark.
You get a CRITERION and a CONTEXT (JSON). Decide whether the criterion holds.
Judge only what the criterion asks; do not reward extra qualities.
When original_request and effective_request are present, compare them. A rule
can be communicated by an equivalent instruction or by directly transforming
an applicable occurrence; exact wording is unnecessary. Mere compatibility or
the absence of prohibited content is not evidence when neither happened.
Answer with exactly one JSON object, nothing else:
{"verdict": "yes"|"no", "reason": "<one short sentence>"}"""

_client: httpx.Client | None = None


def _payload(system: str, user: str, *, model: str | None = None,
             max_tokens: int | None = None) -> dict:
    selected_model = model or JUDGE_MODEL
    selected_tokens = max_tokens or JUDGE_MAX_TOKENS
    is_glm = selected_model.lower().startswith("glm-5")
    return {
        "model": selected_model,
        "max_tokens": selected_tokens,
        "temperature": 0,
        "thinking": {"type": "enabled" if is_glm else "disabled"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }


def _complete(system: str, user: str, *, model: str | None = None,
              max_tokens: int | None = None) -> str:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=120)
    JUDGE_BUCKET.acquire()
    JUDGE_SPACER.acquire()
    resp = _client.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json=_payload(system, user, model=model, max_tokens=max_tokens))
    if resp.status_code == 429:
        JUDGE_BUCKET.on_rate_limit()
    resp.raise_for_status()
    JUDGE_BUCKET.on_success()
    return resp.json()["choices"][0]["message"]["content"]


def judge(criterion: str, context: dict, *, model: str | None = None,
          max_tokens: int | None = None) -> tuple[bool, bool]:
    """Returns (ok, parse_flag). Retry lives HERE, at the call, not on the
    item that contains this call: an item-level retry re-runs every sibling
    LLM call in the shard, and at 35 calls/shard with 2% per-call failure the
    whole shard re-runs with probability ~51%."""
    user = (f"CRITERION:\n{criterion}\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=1)}")
    # Transport retry and semantic-output retry solve different failures.
    # GLM can return HTTP 200 after mandatory thinking consumed the completion
    # budget, leaving an empty/non-JSON final. Retry that once; only two bad
    # finals become the visible fail-closed parse flag.
    for _semantic_attempt in range(2):
        raw = with_retry(
            lambda: _complete(JUDGE_SYSTEM, user, model=model,
                              max_tokens=max_tokens),
            "judge")
        s = raw.strip()
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            obj = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            continue
        v = obj.get("verdict")
        if v in ("yes", "no"):
            return v == "yes", False
    return False, True
