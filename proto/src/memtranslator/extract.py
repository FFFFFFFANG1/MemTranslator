"""Write path Call 1: transcript -> candidate requirements (design §3.2).

Zero candidates is a normal, common outcome and must stay cheap: the session
then costs exactly one LLM call.
"""

from __future__ import annotations

from .llm import LLM, parse_json_block
from .schema import SIGNALS, Candidate, norm_ws
from .store import MemoryStore

MAX_CANDIDATES = 8

SYSTEM = """You maintain long-term memory of a user's REQUIREMENTS for how their AI agents should behave. You read one conversation transcript and extract requirement candidates.

Extract ONLY these three signal types:
- next_turn_feedback: the user corrects, amends, or redirects the assistant's previous response ("I didn't want a summary, analyze its problems").
- repeated_requirement: the user asks for the same behavior they have asked for before in this transcript.
- explicit_instruction: the user states a standing rule ("from now on, always...").

Do NOT extract:
- one-off situational requests ("translate this one into French");
- facts about the user or their environment (those are not behavioral requirements);
- guesses inferred from the assistant's behavior rather than the user's words.

For each candidate output:
- requirement: one self-contained English sentence stating the behavioral requirement;
- polarity: "do" or "dont";
- scope_condition: a natural-language condition describing WHEN this applies, phrased as "the user asks ..." — scope it as narrowly as the evidence supports;
- task_type: a short dotted category like "research.paper-review", "" if unclear;
- keywords: 3-6 lowercase recall keywords;
- signal: one of next_turn_feedback | repeated_requirement | explicit_instruction;
- quote: the user's own words, copied VERBATIM from the transcript (this is machine-checked; any paraphrase gets the candidate discarded);
- turn: the 0-based index of the user message the quote comes from;
- expires_hint: null, or an ISO date if the user bounded it in time.

Output a JSON object: {"candidates": [...]}. At most 8 candidates, only the clearest. If the transcript contains no durable requirement signal, output {"candidates": []}."""


def extract(llm: LLM, transcript: str, store: MemoryStore) -> list[Candidate]:
    raw = llm.complete(SYSTEM, f"<TRANSCRIPT>\n{transcript}\n</TRANSCRIPT>")
    parsed = parse_json_block(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
        store.quarantine(raw, stage="extract", reason="unparseable extraction output")
        return []

    haystack = norm_ws(transcript)
    out: list[Candidate] = []
    for item in parsed["candidates"][:MAX_CANDIDATES]:
        try:
            cand = Candidate(
                requirement=item["requirement"].strip(),
                polarity=item.get("polarity", "do"),
                scope_condition=item["scope_condition"].strip(),
                task_type=item.get("task_type") or "",
                keywords=[str(k).lower() for k in item.get("keywords", [])][:6],
                signal=item["signal"],
                quote=item["quote"],
                turn=int(item.get("turn", -1)),
                expires_hint=item.get("expires_hint"),
            )
        except (KeyError, AttributeError, TypeError, ValueError):
            store.quarantine(str(item), stage="extract", reason="malformed candidate")
            continue
        if cand.signal not in SIGNALS or not cand.requirement or not cand.scope_condition:
            store.quarantine(str(item), stage="extract", reason="invalid fields")
            continue
        if norm_ws(cand.quote) not in haystack:
            # Verbatim check failed: hallucinated or paraphrased evidence.
            store.quarantine(str(item), stage="extract", reason="quote not verbatim in transcript")
            continue
        out.append(cand)
    return out
