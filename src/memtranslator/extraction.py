"""Write-path call #1: batched extraction + diff attribution (design §5).

One flash call digests both signal routes — route-A discourse spans and
route-B (raw, polished, final) diff triples — against a NUMBERED index of the
current store. The model refers to entries by index number, never by raw id
(design R6: hex ids are not robust to copy through a flash model; numbers
are). Out-of-range numbers drop the op and raise a flag.
"""
import json

from memtranslator import llm
from memtranslator.config import (GEN_TEMPERATURE, INDEX_ROW_TOKENS,
                                  MODELS, SALIENCE_MIN)
from memtranslator.schema import BUCKETS, POLARITIES
from memtranslator.schema import Requirement

EXTRACTION_SYSTEM = """You maintain a store of a user's delivery requirements — durable rules about
HOW tasks should be executed and delivered (length, format, tone, language,
method, workflow). You receive:
- STORE: the current entries, numbered [1]..[N];
- SIGNALS-A: sentence spans from the user's messages that may set or correct
  a durable rule;
- SIGNALS-B: rewrite records {raw → polished → final} where "final" is what
  the user actually sent after our rewrite, with a mechanical survival label
  for the injected constraints (kept / removed / mixed).

Emit requirement operations, following ALL of these rules:
1. Extract only durable "how the task is done" rules the user expressed.
   NEVER extract: content preferences (what to recommend, personal facts,
   tastes), one-off instructions scoped to a single task ("this time", "这次",
   "例外", "just this once"), or task content itself.
2. If a signal restates an existing entry, emit "reinforce" with its number.
   If it durably overrides or narrows one, emit "contradict" with the number
   and the corrected text (fold exceptions into the text, e.g. "...— except
   formal cover letters"). If new evidence shows a stored rule's category is
   TOO NARROW (the user applies the same rule to a wider or sibling
   category), emit "contradict" with the WIDENED rule — reinforcing the
   narrow wording would freeze the mistake. If the user durably withdraws
   one with no replacement, emit "retire" with the number. Same facet →
   update, never create a duplicate.
3. SIGNALS-B: ops may come ONLY from text the user ADDED into "final"
   relative to "polished". An added delivery constraint (format, language,
   tone, length, method) COUNTS as a durable signal even when seen once —
   that is the point of this channel. Cover the FULL added delta — if the
   user added both a language and a tone constraint, the new rule carries
   both. Bind each learned rule to the breadth the user's intent supports —
   and when the user's own wording NAMES the category ("这类客诉回复", "the
   postmortems I write", "招标文件"), use exactly that wording as the rule's
   breadth: the user's phrasing IS the scope. Only when no category is named,
   infer the task TYPE from the user's own vocabulary, never the specific
   instance (this one file, this one recipient). Interpersonal tone and
   recipient-specific asks stay scoped to their stated context. NEVER emit ops about constraints that were
   already in "polished" (our own injections are not user signals — no
   reinforce for them). A deleted or weakened injected constraint is a
   one-off signal: emit NOTHING for it — no retire, no contradict
   (mechanical strength already handled it; "survival: removed" describes
   exactly this). If the user REWORDED an injected constraint but kept its
   meaning, that is feedback on our rewrite style: emit "style_rule" with a
   short imperative rule (≤25 tokens) about how to phrase rewrites.
4. Requirement text: single sentence, user's language, imperative gist.
   Include "key": a two-part facet key like email.length / code.explanation /
   report.format (reuse an existing entry's key when the facet matches).
   Include "scope" only when clearly not global, e.g. {"task": "email"}.
4a. ATOMISE. One utterance often states several rules — "from now on write
   paper analyses in Chinese, lead with a comparison table, and judge novelty
   explicitly" is THREE rules. Emit one op per rule and give them the SAME
   "evidence_id" (any short string you choose, unique to this utterance). A
   compound entry cannot be partly overridden later, so never emit one.
4b. BUCKET every op. Ask these in order and STOP at the first that fires:
   1 "task_goal"          — the user's request has no clear task verb, or a
                            vague one, and this rule supplies or replaces it
   2 "reasoning_policy"   — the verb is clear, but this rule sets the method,
                            evidence standard, or criteria to weigh
   3 "deliverables"       — this rule makes a piece of information mandatory;
                            delete it and the answer is missing something
   4 "output_contract"    — same information, different rendering, ordering,
                            length or language
   5 "communication_style"— register, tone, audience
   6 "execution_policy"   — how the agent acts while working: tools, search,
                            ask-vs-assume, keeping the input intact, channel
   None fires → omit "bucket". Never guess. A rule that seems to fit two
   buckets is two rules — atomise it (4a).
   Also give "polarity": require | prefer | avoid | prohibit. Reserve
   "prohibit" for the ones that admit no exception.
5. Rate each op "salience" 1-5 (how clearly the user expressed a durable
   rule). Uncertain guesses get low salience. No computation, no invention.

Output STRICTLY a JSON array (possibly empty), nothing else:
[{"op": "new"|"reinforce"|"contradict"|"retire"|"style_rule",
  "target": <index number or null>, "text": "...", "key": "facet.attr",
  "bucket": "<one of the six>", "polarity": "require|prefer|avoid|prohibit",
  "evidence_id": "<same for rules from one utterance>",
  "scope": {}, "salience": 1-5, "evidence": "<short quote>"}]"""


def _index_block(existing: list[Requirement]) -> str:
    rows = []
    for n, r in enumerate(existing, 1):
        text = r.text if len(r.text) <= INDEX_ROW_TOKENS * 4 \
            else r.text[:INDEX_ROW_TOKENS * 4] + "…"
        tag = "/".join(x for x in (r.bucket, r.key) if x) or "unclassified"
        rows.append(f"[{n}] ({tag}) {text}")
    return "\n".join(rows) or "(store is empty)"


def build_user_prompt(a_candidates: list[str], b_candidates: list[dict],
                      existing: list[Requirement]) -> str:
    parts = [f"STORE:\n{_index_block(existing)}"]
    if a_candidates:
        lines = "\n".join(f"- {s}" for s in a_candidates)
        parts.append(f"SIGNALS-A (message spans):\n{lines}")
    if b_candidates:
        blocks = []
        for b in b_candidates:
            block = json.dumps(
                {"raw": b["raw"], "polished": b["polished"],
                 "final": b["final"], "applied": b.get("applied", []),
                 "survival": b.get("survival", "unknown")},
                ensure_ascii=False)
            if b.get("survival") == "removed":
                block += ("\n  NOTE: the injected constraint was deleted — "
                          "one-off signal, already handled mechanically; "
                          "emit NO op about the deleted constraint itself.")
            blocks.append(block)
        parts.append("SIGNALS-B (rewrite records):\n" + "\n".join(blocks))
    parts.append("JSON:")
    return "\n\n".join(parts)


def parse_ops(raw: str, existing: list[Requirement]) -> tuple[list[dict], list[str]]:
    """LLM output → store ops. Numbers become ids here; anything malformed
    is dropped with a flag, never guessed."""
    s = raw.strip()
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return [], ["unparseable"]
    try:
        items = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return [], ["unparseable"]

    ops, flags = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        op = it.get("op")
        salience = it.get("salience", 0)
        if not isinstance(salience, int) or salience < SALIENCE_MIN:
            continue
        target_id = None
        if it.get("target") is not None:
            t = it["target"]
            if not isinstance(t, int) or not (1 <= t <= len(existing)):
                flags.append(f"target out of range: {t!r}")
                continue
            target_id = existing[t - 1].id

        bucket = it.get("bucket") or ""
        if bucket and bucket not in BUCKETS:
            flags.append(f"unknown bucket: {bucket!r}")
            continue
        polarity = it.get("polarity") or ""
        if polarity and polarity not in POLARITIES:
            polarity = ""            # a bad polarity is droppable metadata,
                                     # unlike a bad bucket which mis-files
        meta = {"bucket": bucket, "polarity": polarity,
                "evidence_id": it.get("evidence_id") or ""}

        if op == "new" and isinstance(it.get("text"), str):
            ops.append({"kind": "new", "text": it["text"],
                        "key": it.get("key", ""),
                        "scope": it.get("scope") or {}, "salience": salience,
                        **meta})
        elif op == "style_rule" and isinstance(it.get("text"), str):
            ops.append({"kind": "new", "text": it["text"], "key": "",
                        "scope": {}, "salience": salience,
                        "rkind": "style_rule", **meta})
        elif op == "reinforce" and target_id:
            ops.append({"kind": "reinforce", "target_id": target_id})
        elif op == "contradict" and target_id and isinstance(it.get("text"), str):
            ops.append({"kind": "contradict", "target_id": target_id,
                        "text": it["text"], "key": it.get("key", ""),
                        "scope": it.get("scope") or {}, "salience": salience,
                        **meta})
        elif op == "retire" and target_id:
            ops.append({"kind": "retire", "target_id": target_id})
        elif op == "merge":
            ts = it.get("targets")
            if (isinstance(ts, list) and len(ts) >= 2
                    and all(isinstance(t, int) and 1 <= t <= len(existing)
                            for t in ts)
                    and isinstance(it.get("text"), str)):
                ops.append({"kind": "merge",
                            "target_ids": [existing[t - 1].id for t in ts],
                            "text": it["text"], "key": it.get("key", ""),
                            "scope": it.get("scope") or {},
                            "salience": salience, **meta})
            else:
                flags.append(f"malformed merge: {ts!r}")
        else:
            flags.append(f"malformed op: {op!r}")
    return ops, flags


def run_extraction(a_candidates: list[str], b_candidates: list[dict],
                   existing: list[Requirement]) -> dict:
    user = build_user_prompt(a_candidates, b_candidates, existing)
    raw = llm.complete(MODELS["translator"], EXTRACTION_SYSTEM, user,
                       max_tokens=1500, temperature=GEN_TEMPERATURE)
    ops, flags = parse_ops(raw, existing)
    return {"ops": ops, "flags": flags}
