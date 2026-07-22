"""LLM judges (plan Task 7). PrefEval ships error-type evaluation prompts
(generation_task/llm_based_evaluation_errortypes.py — see prefeval-notes V3);
our adherence judge is a simplified verdict-style variant of that idea, and
Task 9 calibrates it against 30 human labels before the main run. FAR and
preservation judges are ours (no official counterpart)."""

from __future__ import annotations

import json

from pilot import llm
from pilot.arms import _memory_block
from pilot.config import MODELS

ADHERENCE_SYSTEM = """You evaluate whether an AI assistant's response respects a user's stated preference.
Judge only the response text. Output strictly one JSON object:
{"verdict": "followed" | "violated" | "not_applicable", "reason": "..."}
- "followed": the response respects the preference (explicitly or implicitly).
- "violated": the response contradicts or ignores the preference where it clearly applied.
- "not_applicable": the preference genuinely does not bear on this request."""

FAR_SYSTEM = """You check whether an AI assistant's response was inappropriately steered by stored user memories that do NOT apply to the request.
Output strictly one JSON object:
{"steered": true | false, "steering_memory_ids": ["m2"], "reason": "..."}
"steered" is true only if the response's content, constraints, or style was clearly shaped by one of the listed memories even though that memory is irrelevant to this request. Generic helpfulness is not steering."""

PRESERVE_SYSTEM = """You compare an original user request with a rewritten version, given the user's stored memories.
Output strictly one JSON object:
{"same_core_task": true | false, "added_beyond_memories": true | false, "reason": "..."}
- same_core_task: both versions ask for the same underlying thing.
- added_beyond_memories: the rewrite adds requirements NOT grounded in any provided memory."""


def _parse(raw: str, default: dict) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").removeprefix("json").strip()
    try:
        d = json.loads(s)
        d["judge_parse_error"] = False
        return d
    except json.JSONDecodeError:
        return {**default, "judge_parse_error": True}


def judge_adherence(preference: str, request: str, response: str) -> dict:
    user = (f"User preference: {preference}\n\nUser request: {request}\n\n"
            f"Assistant response:\n{response}\n\nJSON:")
    out = llm.call(MODELS["judge"], user, system=ADHERENCE_SYSTEM,
                   max_tokens=1024)
    return _parse(out["text"], {"verdict": "not_applicable", "reason": ""})


def judge_far(memories: list[dict], request: str, response: str) -> dict:
    user = (f"Stored memories (all irrelevant to this request):\n"
            f"{_memory_block(memories)}\n\nUser request: {request}\n\n"
            f"Assistant response:\n{response}\n\nJSON:")
    out = llm.call(MODELS["judge"], user, system=FAR_SYSTEM, max_tokens=1024)
    return _parse(out["text"], {"steered": False, "reason": ""})


def judge_preservation(memories: list[dict], original: str, rewritten: str) -> dict:
    user = (f"Stored memories:\n{_memory_block(memories)}\n\n"
            f"Original request: {original}\n\n"
            f"Rewritten request: {rewritten}\n\nJSON:")
    out = llm.call(MODELS["judge"], user, system=PRESERVE_SYSTEM,
                   max_tokens=1024)
    return _parse(out["text"], {"same_core_task": True,
                                "added_beyond_memories": False, "reason": ""})
