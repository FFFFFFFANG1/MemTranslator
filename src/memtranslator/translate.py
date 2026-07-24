"""Read path: recall active requirements, one flash call, JSON patch out.

Noop is the default on every failure mode — an underspecified request is
often intentional, and the human edits the result anyway (anchor §2.2).
"""
import json
import time

from memtranslator import llm
from memtranslator.config import MODELS
from memtranslator.recall import recall, style_block
from memtranslator.schema import Requirement

TRANSLATOR_SYSTEM = """You are a translator sitting between a user and their AI agent.
You receive the user's raw request plus the user's stored requirements — rules about HOW they want tasks executed and delivered (format, length, style, method, workflow).
Rewrite the request ONLY when a stored requirement clearly applies to it, so the agent satisfies the user without ever seeing the requirements.

Rules:
1. If no stored requirement clearly applies, output a no-op. When uncertain, prefer no-op — an underspecified request is often intentional.
2. Never invent constraints that are not grounded in a stored requirement.
3. Never change the core task the user is asking for; only make implicit, requirement-backed constraints explicit.
4. Keep the rewritten request natural, as if the user had typed it themselves, and in the language the user wrote in. Do not mention requirements, memory, or this translation step.

Output strictly one JSON object, nothing else:
{"decision": "noop"}
or
{"decision": "apply", "applied_ids": ["req-1a2b3c4d"], "polished": "..."}"""


def _requirement_block(requirements: list[Requirement]) -> str:
    return "\n".join(f"- [{r.id}] {r.text}" for r in requirements)


def parse_patch(raw: str) -> tuple[dict, bool]:
    """Returns (patch, parse_error). Any failure degrades to noop.

    Tolerates fenced JSON and trailing prose after the object (an observed
    flash-model output pattern)."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.removeprefix("json").strip()
    start = s.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(s[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    s = s[start:i + 1]
                    break
    try:
        patch = json.loads(s)
    except json.JSONDecodeError:
        return {"decision": "noop"}, True
    if patch.get("decision") == "noop":
        return {"decision": "noop"}, False
    if (patch.get("decision") == "apply"
            and isinstance(patch.get("polished"), str)
            and patch["polished"].strip()):
        return {"decision": "apply",
                "applied_ids": patch.get("applied_ids", []),
                "polished": patch["polished"].strip()}, False
    return {"decision": "noop"}, True


def translate(text: str, requirements: list[Requirement],
              context: dict | None = None) -> dict:
    """Returns {decision, polished, applied_ids, parse_error, latency_ms}."""
    recalled = recall(requirements, query=text, context=context)
    if not recalled:
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0,
                "reason": "no_active_requirements"}
    system = TRANSLATOR_SYSTEM + style_block(requirements)
    user = (f"Stored requirements:\n{_requirement_block(recalled)}\n\n"
            f"User request:\n{text}\n\nJSON:")
    t0 = time.time()
    raw = llm.complete(MODELS["translator"], system, user)
    latency_ms = int((time.time() - t0) * 1000)
    patch, parse_error = parse_patch(raw)
    known = {r.id for r in recalled}
    applied = [i for i in patch.get("applied_ids", []) if i in known]
    if patch["decision"] == "apply":
        return {"decision": "apply", "polished": patch["polished"],
                "applied_ids": applied, "parse_error": parse_error,
                "latency_ms": latency_ms}
    return {"decision": "noop", "polished": None, "applied_ids": [],
            "parse_error": parse_error, "latency_ms": latency_ms}
