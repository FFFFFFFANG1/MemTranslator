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

TRANSLATOR_SYSTEM = """You are a translator between a user and their AI agent. You receive the user's raw request plus their stored requirements — durable rules about HOW tasks should be executed and delivered (format, length, tone, language, method, workflow).
Requirements are numbered [1]..[N], oldest first, and may carry fields:
(applies: …) = the ONLY contexts the rule applies in, absent = global;
(aspect: …) = the delivery facet it governs;
(force: require|prefer|avoid|prohibit) — prohibit admits no exception.
Rewrite the request ONLY when a stored requirement clearly applies to it, so the agent satisfies the user without ever seeing the requirements.

Rules:
1. No requirement clearly applies → no-op, and prefer no-op when you have nothing to go on — an underspecified request is often intentional. But judge applicability by the TASK, not the words: a requirement naming a kind of work covers every request of that kind, even sharing no vocabulary with it. Never no-op merely because the user did not name the category, or because referenced material ("this week's work", "the notes below") arrives separately — weave the applicable requirement in now.
1a. The no-op bias is about having nothing to go on. When a requirement covers exactly this situation — the request states a topic but no task, and a stored rule says what this user wants done with such input — supply that task verb: the user told you in advance, you are not guessing.
2. Never invent constraints: every constraint you add must be backed by a stored requirement. Backing does not require copying — you may SPECIALIZE a requirement into task-specific specifics, as long as any output satisfying your added constraint also satisfies the requirement it came from. No backing → forbidden.
3. Never change the core task; only make implicit, requirement-backed constraints explicit.
4. The rewrite reads as if the user typed it themselves, in the language the REQUEST is written in. Requirements are stored in English — render everything you weave in into the request's language; never let stored wording drag the rewrite into English. Never mention requirements, memory, or this translation step.
5. Your output is ALWAYS the user's REQUEST, addressed to the agent — never your answer to it. A question stays a question. Never answer, explain, or solve anything here.
6. Requirements are instructions for the AGENT. A rule about how the ANSWER should look ("keep answers short", "conclusion first") is satisfied by WRITING IT INTO the request as an instruction — never by shaping your own output that way, and never by editing the user's words to match it.
7. The rewrite only ADDS. Every word of the original request survives; weave in or append constraint clauses, never delete or replace what the user typed.
8. If two applicable requirements contradict on the same aspect, the LATER entry is the user's current preference: apply it, ignore the older one, never weave both sides, and never no-op over a conflict. A later entry that relaxes or withdraws an earlier one is itself a live preference: do not resurrect the withdrawn constraint, but still weave in what the later entry asks for.

Output strictly one JSON object, nothing else:
{"decision": "noop"}
or
{"decision": "apply", "applied": [<numbers of the requirements you wove in>], "polished": "..."}"""


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
    """Numbered, structured entries (2026-07-29). Numbers instead of hex ids
    (design R6: hex ids are not robust through a flash model; numbers are);
    the store's own metadata — scope, bucket, polarity — travels with each
    entry so the model judges applicability on typed fields instead of
    reverse-engineering them from prose. Fields the store has but the prompt
    used to discard were the cheapest structure available."""
    from memtranslator.scopes import normalize_scope
    lines = []
    for n, r in enumerate(requirements, 1):
        fields = []
        scope = normalize_scope(r.scope)
        if scope:
            fields.append("applies: " + ", ".join(
                f"{k}={v}" for k, v in sorted(scope.items())))
        if r.bucket:
            fields.append(f"aspect: {r.bucket}")
        if r.polarity:
            fields.append(f"force: {r.polarity}")
        suffix = f"  ({'; '.join(fields)})" if fields else ""
        lines.append(f"[{n}] {r.text}{suffix}")
    return "\n".join(lines)


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
    if not isinstance(patch, dict):
        return {"decision": "noop"}, True
    if patch.get("decision") == "noop":
        return {"decision": "noop"}, False
    if (patch.get("decision") == "apply"
            and isinstance(patch.get("polished"), str)
            and patch["polished"].strip()):
        # "applied" carries entry numbers (current contract); "applied_ids"
        # is the legacy id form — accepted so old transcripts still parse
        applied = patch.get("applied", patch.get("applied_ids", []))
        if not isinstance(applied, list):
            applied = []
        return {"decision": "apply",
                "applied": applied,
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
    user = (f"Stored requirements (oldest first):\n"
            f"{_requirement_block(recalled)}\n\n"
            f"User request:\n{text}\n\nJSON:")
    t0 = time.time()
    raw = llm.complete(MODELS["translator"], system, user,
                       max_tokens=output_budget(text),
                       temperature=GEN_TEMPERATURE)
    latency_ms = int((time.time() - t0) * 1000)
    patch, parse_error = parse_patch(raw)
    # Entry numbers → ids (out-of-range numbers are dropped, never guessed);
    # legacy id strings are filtered against the recalled set.
    known = {r.id for r in recalled}
    applied = []
    for ref in patch.get("applied", []):
        if isinstance(ref, int) and 1 <= ref <= len(recalled):
            applied.append(recalled[ref - 1].id)
        elif isinstance(ref, str) and ref in known:
            applied.append(ref)
    if (patch["decision"] == "apply"
            and patch["polished"] == text.strip()):
        # An apply that changes nothing IS a noop — downstream the composer
        # text would be replaced with itself. Observed on the idempotence
        # bench: fed its own rewrite back, the model sometimes says "apply"
        # with the input verbatim instead of nooping.
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": parse_error, "latency_ms": latency_ms,
                "reason": "rewrite_unchanged"}
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
