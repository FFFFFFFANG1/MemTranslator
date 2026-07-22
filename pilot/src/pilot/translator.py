"""The user translator: rewrites the request iff a stored memory applies
(plan Task 6). Content preservation is by construction: only the request
string is ever replaced; attached content is assembled by arms.py."""

from __future__ import annotations

import json

from pilot import llm
from pilot.arms import _memory_block
from pilot.config import MODELS

TRANSLATOR_SYSTEM = """You are a user-input translator sitting between a user and an AI assistant.
You receive the user's raw request plus the user's stored preference memories.
Your job: rewrite the request ONLY when some stored memory clearly applies to it, so that the assistant can satisfy the user without ever seeing the memories.

Rules:
1. If no stored memory clearly applies to this request, output a no-op. When uncertain, prefer no-op -- an underspecified request is often intentional.
2. Never invent requirements that are not grounded in a stored memory.
3. Never change the core task the user is asking for; only make implicit, memory-backed requirements explicit.
4. Never touch, summarize, or rewrite any material the user attached (documents, code, data). You may only rewrite the request itself.
5. Keep the rewritten request natural, as if the user had typed it themselves. Do not mention memories, profiles, or this translation step.

Output strictly one JSON object, nothing else:
{"decision": "noop"}
or
{"decision": "apply", "applied_memory_ids": ["m3"], "new_request": "..."}"""


def _translator_user(instance: dict) -> str:
    mem = _memory_block(instance["memory_store"])
    content_note = ""
    if instance["content"]:
        head = instance["content"][:1500]
        content_note = ("\n\nAttached material (first 1500 chars, shown for "
                        f"context only -- DO NOT rewrite it):\n{head}")
    return (f"Stored user memories:\n{mem}\n\n"
            f"User request:\n{instance['request']}{content_note}\n\nJSON:")


def _first_json_object(s: str) -> dict | None:
    """Extract the first balanced top-level JSON object; the model often
    appends prose after the JSON (observed in B2 dry-run), which is fine —
    we just must not let the trailing text fail the whole parse."""
    start = s.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = not in_str
            elif not in_str:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except json.JSONDecodeError:
                            break
        start = s.find("{", start + 1)
    return None


def parse_patch(raw: str) -> tuple[dict, bool]:
    """Returns (patch, parse_error). Any failure degrades to noop."""
    patch = _first_json_object(raw)
    if patch is not None:
        if patch.get("decision") == "noop":
            return {"decision": "noop"}, False
        if (patch.get("decision") == "apply"
                and isinstance(patch.get("new_request"), str)
                and patch["new_request"].strip()):
            return {"decision": "apply",
                    "applied_memory_ids": patch.get("applied_memory_ids", []),
                    "new_request": patch["new_request"].strip()}, False
    return {"decision": "noop"}, True


def apply_patch(instance: dict, patch: dict) -> str:
    if patch.get("decision") == "apply" and patch.get("new_request"):
        return patch["new_request"]
    return instance["request"]


def translate(instance: dict) -> dict:
    """Returns {"patch", "polished_request", "parse_error", tokens...}."""
    out = llm.call(MODELS["translator"], _translator_user(instance),
                   system=TRANSLATOR_SYSTEM, max_tokens=1024)
    patch, parse_error = parse_patch(out["text"])
    return {"patch": patch,
            "polished_request": apply_patch(instance, patch),
            "parse_error": parse_error,
            "translator_input_tokens": out["input_tokens"],
            "translator_output_tokens": out["output_tokens"]}
