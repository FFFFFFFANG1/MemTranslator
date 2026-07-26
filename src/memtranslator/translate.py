"""Read path: recall active requirements, one flash call, JSON patch out.

Noop is the default on every failure mode — an underspecified request is
often intentional, and the human edits the result anyway (anchor §2.2).
"""
import json
import time
from difflib import SequenceMatcher

from memtranslator import llm
from memtranslator.config import (GEN_TEMPERATURE, MAX_OUTPUT_TOKENS,
                                  MIN_OUTPUT_TOKENS, MODELS,
                                  PRESERVE_MIN_RATIO)
from memtranslator.recall import recall, style_block
from memtranslator.schema import Requirement

TRANSLATOR_SYSTEM = """You are a translator sitting between a user and their AI agent.
You receive the user's raw request plus the user's stored requirements — rules about HOW they want tasks executed and delivered (format, length, style, method, workflow).
Rewrite the request ONLY when a stored requirement clearly applies to it, so the agent satisfies the user without ever seeing the requirements.

Rules:
1. If no stored requirement clearly applies, output a no-op. When uncertain, prefer no-op — an underspecified request is often intentional. But judge applicability by the TASK, not by the words: a requirement that names a kind of work ("research questions", "code answers", "the summaries I write") applies to every request of that kind, including ones that share no vocabulary with it — a question weighing two tools against each other is a research question; a request for a small utility is a code request. No-op is for requests genuinely outside every stored requirement, never for ones whose category the user simply did not name.
2. Never invent constraints that are not grounded in a stored requirement.
3. Never change the core task the user is asking for; only make implicit, requirement-backed constraints explicit.
4. Keep the rewritten request natural, as if the user had typed it themselves, and in the language the user wrote in. Do not mention requirements, memory, or this translation step.
5. Your output is ALWAYS the user's REQUEST, addressed to the agent — never your answer to it. If the user asked a question, the rewritten text is still that question. Never answer, explain, or solve anything here.
6. Requirements are instructions for the AGENT, not for you. A requirement that describes how the ANSWER should look ("keep answers short", "no bullet points", "don't restate my question", "conclusion first") is satisfied by WRITING IT INTO the request as an instruction — never by producing an answer in that shape yourself, and never by editing the user's own words to match it.
7. The rewrite only ADDS. Every word of the user's original request survives in it; you may append or weave in constraint clauses, but you may not delete or replace what the user typed.

Output strictly one JSON object, nothing else:
{"decision": "noop"}
or
{"decision": "apply", "applied_ids": ["req-1a2b3c4d"], "polished": "..."}"""


def _estimate_tokens(text: str) -> int:
    """Cheap upper-ish estimate without a tokenizer: CJK runs about one token
    per character, Latin script about one per four."""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk + (len(text) - cjk) // 4 + 1


def output_budget(text: str) -> int:
    """max_tokens for one rewrite of `text`.

    The rewrite only ADDS, so the reply is never shorter than the request —
    a fixed cap therefore truncates long inputs mid-payload, the JSON fails
    to parse, and the user sees the hotkey do nothing at all. Measured on the
    product path before this existed: a 2,074-character Chinese paste came
    back parse_error=True and silently no-op. The budget scales with the
    request and keeps a headroom allowance for the injected constraints and
    the JSON envelope.
    """
    est = _estimate_tokens(text)
    return max(MIN_OUTPUT_TOKENS,
               min(MAX_OUTPUT_TOKENS, int(est * 1.6) + 400))


def preserves_request(original: str, polished: str) -> bool:
    """A rewrite only ADDS — it never deletes what the user typed.

    This is the mechanical half of rule 7, and it is a product invariant, not
    a quality heuristic: the composer text is the user's own words on their
    way to an agent, so a "rewrite" that drops part of them has replaced the
    user rather than served them. Observed for real on a flash backbone: with
    several answer-shaped requirements stored at once, the model would answer
    the question instead of rewriting it, or satisfy "don't restate my
    question" by deleting words out of the question. Both destroy the request,
    so both degrade to noop — the same fail-safe every other error path here
    already takes.
    """
    if not original.strip():
        return True
    matcher = SequenceMatcher(None, original, polished, autojunk=False)
    kept = sum(b.size for b in matcher.get_matching_blocks())
    return kept >= PRESERVE_MIN_RATIO * len(original)


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
    raw = llm.complete(MODELS["translator"], system, user,
                       max_tokens=output_budget(text),
                       temperature=GEN_TEMPERATURE)
    latency_ms = int((time.time() - t0) * 1000)
    patch, parse_error = parse_patch(raw)
    known = {r.id for r in recalled}
    applied = [i for i in patch.get("applied_ids", []) if i in known]
    if (patch["decision"] == "apply"
            and not preserves_request(text, patch["polished"])):
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": parse_error, "latency_ms": latency_ms,
                "reason": "rewrite_dropped_user_text"}
    if patch["decision"] == "apply":
        return {"decision": "apply", "polished": patch["polished"],
                "applied_ids": applied, "parse_error": parse_error,
                "latency_ms": latency_ms}
    return {"decision": "noop", "polished": None, "applied_ids": [],
            "parse_error": parse_error, "latency_ms": latency_ms,
            "reason": "unparseable_output" if parse_error else "model_noop"}
