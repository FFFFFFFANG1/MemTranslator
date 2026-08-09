"""Write-path call #1: batched extraction + diff attribution (design §5).

One flash call digests both signal routes — route-A discourse spans and
route-B (raw, polished, final) diff triples — against a NUMBERED index of the
current store. The model refers to entries by index number, never by raw id
(design R6: hex ids are not robust to copy through a flash model; numbers
are). Out-of-range numbers drop the op and raise a flag.
"""
import json
import re

from memtranslator import llm
from memtranslator.config import (GEN_TEMPERATURE, INDEX_ROW_TOKENS,
                                  MODELS, SALIENCE_MIN)
from memtranslator.schema import BUCKETS, POLARITIES
from memtranslator.scopes import normalize_scope
from memtranslator.schema import Requirement

# The two signal routes are separate calls with disjoint operation contracts
# (2026-08-09). Route A reads what the user SAID and emits store ops against
# the numbered STORE. Route B reads what the user EDITED in a patch we wrote
# and judges only the entries that patch used, so it needs no store index and
# may not create memory — see B_EXTRACTION_SYSTEM. Route A's own rules keep
# their historical numbers so a doc citing "rule 4c" still points at the same
# text. Cross-batch store hygiene stays with the low-frequency consolidation
# pass, the only stage that sees the results of both routes.
A_EXTRACTION_SYSTEM = """You maintain a store of a user's delivery requirements — durable rules about
HOW tasks should be executed and delivered (length, format, tone, language,
method, workflow). You receive:
- STORE: the current entries, numbered [1]..[N];
- SIGNALS-A: sentence spans from the user's messages that may set or correct
  a durable rule. A span may carry a mechanical annotation "[shares
  vocabulary with entries [3]]" — candidate referents computed by word
  overlap. When resolving which entry a span restates, overrides or
  withdraws, check those numbers FIRST; the annotation is a candidate
  list, not a verdict, and a span without one usually sets a NEW rule.

Emit requirement operations, following ALL of these rules:
1. Extract only durable "how the task is done" rules the user expressed.
   NEVER extract: content preferences (what to recommend, personal facts,
   tastes), one-off instructions scoped to a single task ("this time", "这次",
   "例外", "just this once"), or task content itself. Constraints attached
   to a task the user is assigning in the same breath ("写个X，要Y，别用Z" /
   "write me an X that does Y, no Z") are that task's SPEC, not durable
   rules — extract nothing from them unless durability phrasing (以后 /
   每次 / from now on / always) explicitly covers them.
2. If a signal restates an existing entry, emit "reinforce" with its number.
   If it durably overrides or narrows one, emit "contradict" with the number
   and the corrected text (fold exceptions into the text, e.g. "...— except
   formal cover letters"). If new evidence shows a stored rule's category is
   TOO NARROW (the user applies the same rule to a wider or sibling
   category), emit "contradict" with the WIDENED rule — reinforcing the
   narrow wording would freeze the mistake. If the user durably withdraws
   one with no replacement, emit "retire" with the number.
   WITHDRAWALS ("stop doing X" / 「别再X了」/「X不用了」): first find the
   stored entry that says X, then re-read the WHOLE utterance for what the
   user wants INSTEAD — the instead-half trails the negative half and is
   the easy part to drop. Three cases:
   - the instead-half names a concrete behavior Y (「别再X了，Y就行」/
     "stop X, just do Y"): emit "contradict" with text stating Y
     positively. Never store the negation itself — "don't do X anymore"
     as a stored rule leaves the old X rule undead.
   - the instead-half only returns to normal/default ("write it
     normally", 「按默认」): emit "retire".
   - no instead-half: emit "retire".
   A withdrawal never yields "new" while a stored entry still says X —
   that would create the contradiction instead of resolving it. Same facet →
   update, never create a duplicate.
   REFERENT NOT IN STORE: users sometimes override or withdraw a rule by
   bare reference ("that earlier instruction", "the old rule", a deictic
   phrase with no subject matter). If NO stored entry is about the subject
   being referenced, the referent predates the store — it is NOT here. Emit "new" with the corrected rule (or
   nothing, for a bare withdrawal). NEVER aim contradict or retire at an
   unrelated entry just because a number must be chosen; a wrong target
   destroys a healthy rule.
4. Requirement text: single sentence, imperative gist, written in ENGLISH
   regardless of the user's language — English is the store's canonical
   language (owner ruling 2026-07-29: one storage language keeps matching
   and dedup single-lingual; the rewrite step renders rules back into the
   user's language). Quoted names, file formats and code terms stay
   verbatim. A rule ABOUT output language is still stored in English
   ("reply in Chinese"), never in the language it mandates.
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
4c. STATE THE CLASS, NOT THE INSTANCE. "text" has to read correctly months
   from now against requests you have not seen: name the class of work the
   rule governs, not the one in front of you. Narrowing the user actually
   meant goes in "scope", never in "text" — a rule whose text names one
   recipient, file or title can never fire again.
5. Rate each op "salience" 1-5 (how clearly the user expressed a durable
   rule). Uncertain guesses get low salience. No computation, no invention.

Output STRICTLY a JSON array (possibly empty), nothing else:
[{"op": "new"|"reinforce"|"contradict"|"retire"|"style_rule",
  "target": <index number or null>, "text": "...", "key": "facet.attr",
  "bucket": "<one of the six>", "polarity": "require|prefer|avoid|prohibit",
  "evidence_id": "<same for rules from one utterance>",
  "scope": {}, "salience": 1-5, "evidence": "<short quote>"}]"""

# Historical name kept for the probes and repros that pin the A channel.
EXTRACTION_SYSTEM = A_EXTRACTION_SYSTEM


B_EXTRACTION_SYSTEM = """You review human edits to requirement-backed request patches.
For each SIGNAL you receive:
- ENTRIES are the exact stored requirements the translator used for that
  patch, numbered locally within the signal;
- DIFF is the only human feedback. Each item shows the complete sentence
  before and after the edit; ``<changed>...</changed>`` marks the edited
  span. Sentences through 128 lexical tokens are complete; longer sentences
  retain 56 tokens on each side of the change and use ``[truncated]``.

Judge each entry independently. First identify the facet governed by the
entry (length, format, language, tone, method, and so on), then the facet
changed inside the markers.

Strict attribution rules:
- If the entry's original behavior remains unchanged and the user merely adds
  a second, independently satisfiable constraint, emit none. Never append an
  orthogonal addition to the stored entry.
- update is allowed only when the diff changes the same facet, value, or scope
  as the entry. A changed cap, alternative rendering, opposite language or
  tone, or a new exception to the same rule is a replacement/refinement and
  MUST be update, never retire.
- retire is allowed only when the marked edit removes or rejects the entry's
  behavior and supplies no replacement on that facet.
- When attribution or facet identity is uncertain, emit none.

Use this counterfactual before update: ignore the marked addition in the
AFTER sentence. If the entry's required behavior is still present and fully
satisfied, while the addition can coexist with it, the answer is none. For
example, an entry requiring labelled charts is not updated when the user
keeps the labels and merely adds another output language. Conversely,
replacing a list with a matrix changes the same rendering facet and is update.

The only operations are:
- update: the diff directly refines, narrows, widens, or changes that entry.
  Return the complete revised durable requirement in ENGLISH, not the
  one-off request; do not merely explain what changed.
- retire: the diff directly removes or rejects the behavior required by that
  entry and supplies no replacement. This is one negative vote; storage
  retires an entry only after two votes.
- none: the edit is unrelated to the entry, only changes task content or
  phrasing, preserves the entry, adds a one-off constraint, or is ambiguous.

Never create a new memory, reinforce an entry, infer a style rule, or target
an entry outside the signal. Untouched agent-written text is not user
evidence. A replacement is update, not retire. Emit exactly one judgement
per signal-entry pair.

Output STRICTLY a JSON array, nothing else:
[{"signal": <signal number>, "entry": <entry number>,
  "op": "update"|"retire"|"none", "text": "<required for update>"}]"""


def _index_block(existing: list[Requirement]) -> str:
    rows = []
    for n, r in enumerate(existing, 1):
        text = r.text if len(r.text) <= INDEX_ROW_TOKENS * 4 \
            else r.text[:INDEX_ROW_TOKENS * 4] + "…"
        tag = "/".join(x for x in (r.bucket, r.key) if x) or "unclassified"
        rows.append(f"[{n}] ({tag}) {text}")
    return "\n".join(rows) or "(store is empty)"


def _referent_hints(span: str, existing: list[Requirement]) -> list[int]:
    """Mechanical referent pre-resolution (0 tokens): store entry numbers
    whose content vocabulary overlaps the span, same overlap logic the
    screening boost and the grounding guard use. A withdrawal or override
    that quotes a rule carries the rule's vocabulary, not rule-setting
    phrasing — handing the model the candidate numbers turns "search the
    store for the referent" into "verify a candidate", which is the step
    flash was measured to fumble (revoke ops flip between contradict /
    retire+new / nothing on identical input at temperature 0)."""
    from memtranslator.signals import content_tokens, overlap_is_reference

    toks = content_tokens(span)
    return [n for n, r in enumerate(existing, 1)
            if overlap_is_reference(toks, content_tokens(r.text))]


def build_user_prompt(a_candidates: list[str], b_candidates: list[dict],
                      existing: list[Requirement]) -> str:
    parts = [f"STORE:\n{_index_block(existing)}"]
    if a_candidates:
        lines = []
        for s in a_candidates:
            hints = _referent_hints(s, existing)
            tag = (f"  [shares vocabulary with entries "
                   f"{', '.join(f'[{n}]' for n in hints)}]") if hints else ""
            lines.append(f"- {s}{tag}")
        parts.append("SIGNALS-A (message spans):\n" + "\n".join(lines))
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


def build_a_user_prompt(a_candidates: list[str],
                        existing: list[Requirement]) -> str:
    return build_user_prompt(a_candidates, [], existing)


def build_b_user_prompt(candidates: list[dict]) -> str:
    """Route-B input is entry snapshots plus marked diffs — no store index.
    The entries are the ones the patch actually used, recorded at translate
    time, so there is nothing for the model to search for or resolve."""
    signals = []
    for signal_n, candidate in enumerate(candidates, 1):
        entries = []
        for entry_n, entry in enumerate(candidate.get("entries", []), 1):
            entries.append({
                "entry": entry_n,
                "text": entry.get("text", ""),
                "key": entry.get("key", ""),
                "scope": entry.get("scope") or None,
                "bucket": entry.get("bucket", ""),
                "polarity": entry.get("polarity", ""),
            })
        signals.append({"signal": signal_n, "entries": entries,
                        "diff": candidate.get("diff", [])})
    return ("SIGNALS:\n" + json.dumps(signals, ensure_ascii=False, indent=2)
            + "\n\nJSON:")


def _escape_inner_quotes(s: str) -> str:
    """Repair the one JSON defect flash actually produces: the user's
    curly quotes (“我建议”) echoed back as ASCII double quotes INSIDE a
    string value, which invalidates the whole array and silently threw
    away entire op batches (found live: a batch whose ops were all
    correct — two durable rules extracted, a task spec rightly refused —
    died as "unparseable"). Inside a string, a quote whose next
    non-whitespace character is not a JSON delimiter is content, not a
    terminator — escape it."""
    out, in_str, i = [], False, 0
    while i < len(s):
        ch = s[i]
        if not in_str:
            if ch == '"':
                in_str = True
            out.append(ch)
        elif ch == "\\":
            out.append(s[i:i + 2])
            i += 1
        elif ch == '"':
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in ",:]}":
                in_str = False
                out.append(ch)
            else:
                out.append('\\"')
        else:
            out.append(ch)
        i += 1
    return "".join(out)


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
        try:
            items = json.loads(_escape_inner_quotes(s[start:end + 1]))
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
                        "scope": normalize_scope(it.get("scope")), "salience": salience,
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
                        "scope": normalize_scope(it.get("scope")), "salience": salience,
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
                            "scope": normalize_scope(it.get("scope")),
                            "salience": salience, **meta})
            else:
                flags.append(f"malformed merge: {ts!r}")
        else:
            flags.append(f"malformed op: {op!r}")
    return ops, flags


def parse_feedback_ops(raw: str, candidates: list[dict]
                       ) -> tuple[list[dict], list[str]]:
    """Parse route-B judgements and bind them mechanically to the recorded
    entry ids. The model names a (signal, entry) pair, never an id: it can
    only ever act on an entry the patch really used."""
    s = raw.strip()
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return [], ["unparseable"]
    try:
        items = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        try:
            items = json.loads(_escape_inner_quotes(s[start:end + 1]))
        except json.JSONDecodeError:
            return [], ["unparseable"]
    if not isinstance(items, list):
        return [], ["unparseable"]

    by_pair, flags, seen = {}, [], set()
    for item in items:
        if not isinstance(item, dict):
            flags.append("malformed feedback judgement")
            continue
        signal_n, entry_n = item.get("signal"), item.get("entry")
        if not isinstance(signal_n, int) \
                or not (1 <= signal_n <= len(candidates)):
            flags.append(f"feedback signal out of range: {signal_n!r}")
            continue
        entries = candidates[signal_n - 1].get("entries", [])
        if not isinstance(entry_n, int) or not (1 <= entry_n <= len(entries)):
            flags.append(f"feedback entry out of range: {entry_n!r}")
            continue
        pair = (signal_n, entry_n)
        if pair in seen:
            flags.append(f"duplicate feedback judgement: {pair!r}")
            continue
        seen.add(pair)
        entry = entries[entry_n - 1]
        target_id = entry.get("id")
        if not target_id:
            flags.append(f"feedback entry missing id: {pair!r}")
            continue

        kind = item.get("op")
        if kind == "none":
            by_pair[pair] = None
            continue
        if kind == "retire":
            by_pair[pair] = {"kind": "retire", "target_id": target_id}
            continue
        if kind == "update":
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                flags.append(f"feedback update missing text: {pair!r}")
                continue
            text = text.strip()
            if text == (entry.get("text") or "").strip():
                flags.append(f"feedback update unchanged: {pair!r}")
                continue
            by_pair[pair] = {"kind": "update", "target_id": target_id,
                             "text": text}
            continue
        flags.append(f"unsupported feedback op: {kind!r}")

    expected = sum(len(c.get("entries", [])) for c in candidates)
    if len(seen) < expected:
        flags.append(f"missing feedback judgements: {expected - len(seen)}")
    # Model array order is not trusted. Apply feedback in buffer chronology so
    # a later refinement can reset earlier negative evidence, not vice versa.
    ops = [by_pair[p] for p in sorted(by_pair) if by_pair[p] is not None]
    return ops, flags


def _ground_destructive_ops(ops: list[dict], a_candidates: list[str],
                            b_candidates: list[dict],
                            existing: list[Requirement]
                            ) -> tuple[list[dict], list[str]]:
    """Zero-LLM guard: a contradict/retire must be GROUNDED — its target's
    text must share vocabulary with what the user actually said this batch.

    Found by the bench's collision-free canary (2026-07-29, deterministic
    3/3 repro in bench/repro_deixis_kill.py): a withdrawal referencing, by a
    bare deictic phrase, a rule that predates the store made the model
    resolve the dangling reference to the only numbered entry it could see
    and kill an unrelated rule. The user had never mentioned that rule's
    subject; this check makes that mechanical. Shared function-word bigrams
    can still ground a wrong target (the guard is conservative, not
    complete) — but zero overlap is zero justification, and that is exactly
    the repro's shape.

    Token computation is signals.content_tokens — the SAME set the
    screening boost and the referent hints use. The three must agree: the
    perf canary died over one scaffold token (一律) bridging unrelated
    rules, and l-rvk-004 died the opposite death when this guard, still on
    raw tokens, saw zero overlap between "notifications" (stored) and
    "notification" (withdrawal) and dropped a retire the model got right."""
    from memtranslator.signals import _KEY_LEXICON, content_tokens

    def roots(text: str) -> set:
        """Cross-language facet bridge: 'emails' and 「邮件」 share no token
        but share the `email` lexicon root. Without this the guard blocked
        legitimate supersedes whenever store and signal spoke different
        languages — the same cross-language failure this codebase has now
        hit three times."""
        low = text.lower()
        return {root for root, surfaces in _KEY_LEXICON.items()
                if any(s.lower() in low for s in surfaces)}

    # route-B grounding includes POLISHED: the user was editing OUR
    # injection, so every rule woven into that exchange was visibly in play
    signal_text = " ".join(a_candidates) + " " + " ".join(
        f"{b.get('raw', '')} {b.get('polished', '')} {b.get('final', '')}"
        for b in b_candidates)
    sig = content_tokens(signal_text)
    sig_roots = roots(signal_text)
    by_id = {r.id: r for r in existing}
    kept, flags = [], []
    for o in ops:
        if o["kind"] in ("contradict", "retire"):
            tgt = by_id.get(o.get("target_id") or "")
            if tgt is not None \
                    and not (content_tokens(tgt.text) & sig) \
                    and not (roots(tgt.text) & sig_roots):
                flags.append(
                    f"ungrounded {o['kind']} dropped: target "
                    f"{tgt.text[:30]!r} shares no vocabulary with the "
                    f"signals")
                if o["kind"] == "contradict" and o.get("text"):
                    # the corrected rule itself is still user-grounded —
                    # keep the content, lose the kill
                    kept.append({**o, "kind": "new", "target_id": None})
                continue
        kept.append(o)
    return kept, flags


_QUOTED = re.compile(r"「([^」]{4,})」|\u201c([^\u201d]{4,})\u201d|\"([^\"]{4,})\"")


def _withdrawal_referent(spans: list[str]) -> str:
    """What the withdrawal NAMES. Users typically quote the rule they are
    dropping inside brackets or quotation marks, and that quoted fragment
    is a far sharper referent than the whole chatty span around it;
    without any quotation the span itself is used."""
    quoted = []
    for sp in spans:
        for m in _QUOTED.finditer(sp):
            quoted.append(next(g for g in m.groups() if g))
    return " ".join(quoted) if quoted else " ".join(spans)


def _gate_destructive_intent(ops: list[dict], a_candidates: list[str],
                             b_candidates: list[dict],
                             existing: list[Requirement]
                             ) -> tuple[list[dict], list[str]]:
    """A bare retire needs a withdrawal-SHAPED span, not mere vocabulary
    overlap (LightMem's rule: delete only on direct conflict/revocation).

    Measured on a chained e-05 replay: extraction emitted 10 bare retires
    in 62 rounds, killing live gold rules — every one passed the overlap
    grounding because ordinary task chatter naturally mentions rule
    vocabulary ("写个 bullet list…" grounds a bullet-point rule's death).
    Overlap says the rule was IN PLAY; only revocation language says the
    user wants it GONE. The span-level check reuses the screening layer's
    withdrawal pattern, so both layers recognise the same shapes."""
    from memtranslator.signals import (_WITHDRAW_PAT, content_tokens,
                                       overlap_is_reference)
    spans = list(a_candidates) + [
        f"{b.get('raw', '')} {b.get('final', '')}" for b in b_candidates]
    withdraw_spans = [s for s in spans if _WITHDRAW_PAT.search(s)]
    by_id = {r.id: r for r in existing}
    active = [r for r in existing if r.status == "active"]
    kept, flags = [], []
    for o in ops:
        if o["kind"] == "retire":
            tgt = by_id.get(o.get("target_id") or "")
            if tgt is not None:
                tt = content_tokens(tgt.text)
                # reference-strength overlap (≥2 tokens or an anchor), not
                # any-shared-token: a chatty span matching the withdrawal
                # pattern for an unrelated rule must not license this kill
                lic = [w for w in withdraw_spans
                       if overlap_is_reference(tt, content_tokens(w))]
                if not lic:
                    flags.append(f"retire without withdrawal-shaped "
                                 f"evidence dropped: {tgt.text[:40]!r}")
                    continue
                # AIM CHECK (loop-9): overlap proves the span mentions
                # vocabulary the target shares — not that the span NAMES
                # the target. Measured: 「don't use sentence structure…」
                # licensed the death of "write complete sentences", and a
                # headings withdrawal killed a table-columns rule, because
                # generic rule words (include / at least / sentence) reach
                # reference strength on their own. The referent is usually
                # quoted verbatim in the utterance, so score every ACTIVE
                # entry against that referent and require the victim to be
                # the best match; a strictly better match means the op is
                # mis-aimed and is re-pointed at the rule the user named.
                ref = _withdrawal_referent(lic)
                rt = content_tokens(ref)
                def score(text):
                    et = content_tokens(text)
                    return (len(set(rt) & set(et))
                            / max(1, len(set(rt) | set(et))))
                best, bs = tgt, score(tgt.text)
                for r in active:
                    sc = score(r.text)
                    if sc > bs + 0.05:
                        best, bs = r, sc
                if best is not tgt:
                    flags.append(f"retire re-aimed: {tgt.text[:32]!r} -> "
                                 f"{best.text[:32]!r}")
                    o = {**o, "target_id": best.id}
                o = {**o, "withdrawal": True}
        kept.append(o)
    return kept, flags


def _gate_contradict_facet(ops: list[dict], a_candidates: list[str],
                           b_candidates: list[dict],
                           existing: list[Requirement]
                           ) -> tuple[list[dict], list[str]]:
    """A contradict must stay within its target's kind of work. Measured
    killer (e-02 chained): a postmortem-scoped "at least 17 sentences"
    utterance was filed as an UPDATE to the email sentence cap — the model
    even rewrote the new text to say "in emails", inheriting the target's
    scope — and the correct cap died with a live wrong heir, invisible to
    both the withdrawal gate and the heir invariant. Mechanical check: the
    op's best-grounding span names one kind of work, the target another,
    and they are incompatible → the utterance is a NEW rule for its own
    kind, not an update; keep the content, cancel the kill. Either side
    unknown → never block (the standing never-exclude-on-missing rule)."""
    from memtranslator.kinds import infer_task_kind, kind_matches
    from memtranslator.signals import content_tokens
    spans = list(a_candidates) + [
        f"{b.get('raw', '')} {b.get('final', '')}" for b in b_candidates]
    by_id = {r.id: r for r in existing}
    kept, flags = [], []
    for o in ops:
        if o.get("kind") == "contradict" and o.get("text"):
            tgt = by_id.get(o.get("target_id") or "")
            if tgt is not None and spans:
                ot = set(content_tokens(o["text"]))
                best = max(spans, key=lambda s:
                           len(ot & set(content_tokens(s))))
                skind = infer_task_kind(best, {})
                tkinds = tgt.kinds or None
                if not tkinds:
                    tk = infer_task_kind(tgt.text, {})
                    tkinds = [tk] if tk else None
                if (skind and tkinds
                        and not kind_matches(tkinds, skind)):
                    flags.append(f"cross-kind contradict -> new: span kind "
                                 f"{skind} vs target {tkinds} "
                                 f"({tgt.text[:30]!r})")
                    kept.append({**o, "kind": "new", "target_id": None})
                    continue
        kept.append(o)
    return kept, flags


_MIN_FAMILY = re.compile(
    r"at\s+least|minimum|no\s+(?:fewer|less)\s+than|或以上|以上|至少|最少|不少于",
    re.IGNORECASE)
_MAX_FAMILY = re.compile(
    r"at\s+most|maximum|max\b|no\s+(?:more|longer)\s+than|under\b|"
    r"以内|以下|至多|最多|不超过|不得超过|别超过",
    re.IGNORECASE)


def _gate_op_fidelity(ops: list[dict], a_candidates: list[str],
                      b_candidates: list[dict]
                      ) -> tuple[list[dict], list[str]]:
    """A numeric rule must keep its source's DIRECTION. Measured killer
    (e-02 chained): "keep it to 11 sentences max" was written into the
    store as "at least 11 sentences" — wrong at birth, unfixable by any
    later kill-guard, and actively harmful when injected. Mechanical
    check: for a new/contradict op whose text carries digits, find the
    span sharing those digits; if the span sits in one bound family
    (min/max) and the op text in the other, drop the op — an absent rule
    self-heals on the next restatement, an inverted one never does.
    Spans or ops without a clear single family are left alone."""
    from memtranslator.signals import content_tokens
    spans = list(a_candidates) + [
        f"{b.get('raw', '')} {b.get('final', '')}" for b in b_candidates]

    def family(text: str) -> str | None:
        lo, hi = bool(_MIN_FAMILY.search(text)), bool(_MAX_FAMILY.search(text))
        if lo == hi:
            return None                    # neither, or both → ambiguous
        return "min" if lo else "max"

    kept, flags = [], []
    for o in ops:
        if o.get("kind") in ("new", "contradict") and o.get("text"):
            op_digits = set(re.findall(r"\d+", o["text"]))
            if op_digits:
                src = [s for s in spans
                       if op_digits & set(re.findall(r"\d+", s))]
                if src:
                    ofam = family(o["text"])
                    sfams = {family(s) for s in src} - {None}
                    if (ofam is not None and sfams
                            and ofam not in sfams):
                        flags.append(
                            f"polarity-inverted op dropped "
                            f"({'/'.join(sorted(sfams))} source -> {ofam} "
                            f"op): {o['text'][:40]!r}")
                        continue
        kept.append(o)
    return kept, flags


_ONE_OFF_PAT = re.compile(
    r"this\s+(?:one\s+)?time|just\s+this\s+once|this\s+once|for\s+now\b|"
    r"这次|这一次|这一回|本次|就这一次|临时",
    re.IGNORECASE)


_SEMI = re.compile(r"[;；]")
_EXCEPT = re.compile(r"—\s*except|\bexcept\b|除了|例外", re.IGNORECASE)


def _atomise_ops(ops: list[dict]) -> tuple[list[dict], list[str]]:
    """Split semicolon-joined compound entries at birth (loop-8).

    The extraction prompt already demands one rule per op (a compound entry
    cannot be partly overridden later), but the backbone violates it —
    measured: 5 semicolon-joined entries alive in one chained store. The
    consolidation side of this risk is now gated; entries born compound
    have no victims to pop and were the remaining half.

    Conservative by construction: exception folding ("— except formal
    cover letters") is deliberate and exempt; a semicolon inside quotes or
    backticks is content, not a joiner; both halves must carry real
    content. A compound contradict keeps its target on the FIRST half and
    files the rest as its own rule — two contradicts on one target would
    build a bogus supersede chain."""
    from memtranslator.signals import content_tokens
    out, flags = [], []
    for o in ops:
        text = o.get("text") or ""
        if (o.get("kind") not in ("new", "contradict") or not text
                or _EXCEPT.search(text)):
            out.append(o)
            continue
        # a semicolon inside a quoted or backticked span is content
        spans = re.findall(r"`[^`]*`|\"[^\"]*\"|'[^']*'|「[^」]*」", text)
        if any(_SEMI.search(sp) for sp in spans):
            out.append(o)
            continue
        parts = [p.strip(" ;；") for p in _SEMI.split(text)]
        parts = [p for p in parts if p]
        if len(parts) < 2 or any(len(content_tokens(p)) < 3 for p in parts):
            out.append(o)
            continue
        eid = o.get("evidence_id") or f"atom-{abs(hash(text)) % 10000}"
        for n, part in enumerate(parts):
            piece = {**o, "text": part, "evidence_id": eid}
            if n and o.get("kind") == "contradict":
                piece["kind"] = "new"
                piece["target_id"] = None
            out.append(piece)
        flags.append(f"atomised into {len(parts)}: {text[:50]!r}")
    return out, flags


def _gate_withdrawal_new(ops: list[dict], a_candidates: list[str],
                         b_candidates: list[dict],
                         existing: list[Requirement]
                         ) -> tuple[list[dict], list[str]]:
    """The withdrawal protocol says: never NEW while a stored entry still
    says X — that mints the contradiction instead of resolving it.
    Measured on the recheck pass: a withdrawal-shaped span took the
    "referent not in store" branch and re-created the very rule being
    revoked. Mechanical: a new op whose best-grounding span is
    withdrawal-shaped AND overlaps an ACTIVE entry at reference strength
    is dropped — the correct op for that span is contradict or retire."""
    from memtranslator.signals import (_WITHDRAW_PAT, content_tokens,
                                       overlap_is_reference)
    spans = list(a_candidates) + [
        f"{b.get('raw', '')} {b.get('final', '')}" for b in b_candidates]
    active = [r for r in existing if r.status == "active"]
    kept, flags = [], []
    for o in ops:
        if o.get("kind") == "new" and o.get("text") and spans:
            ot = set(content_tokens(o["text"]))
            best = max(spans, key=lambda sp:
                       len(ot & set(content_tokens(sp))))
            if _WITHDRAW_PAT.search(best):
                st = content_tokens(best)
                if any(overlap_is_reference(st, content_tokens(r.text))
                       for r in active):
                    flags.append(f"withdrawal-span new dropped: "
                                 f"{o['text'][:40]!r}")
                    continue
        kept.append(o)
    return kept, flags


def _gate_one_off(ops: list[dict], a_candidates: list[str],
                  b_candidates: list[dict]
                  ) -> tuple[list[dict], list[str]]:
    """A rule minted from a ONE-OFF utterance is a category error the
    backbone can commit fluently: "just this once, use APA" comes back as
    a durable contradict with the exception folded in. Mechanical check on
    the op's best-grounding span: one-off markers present AND no
    durability phrasing → the utterance scoped itself to a single task;
    no durable op may come out of it. Category exceptions ("except formal
    cover letters") carry no one-off marker and pass untouched."""
    from memtranslator.signals import _RULE_PAT, content_tokens
    spans = list(a_candidates) + [
        f"{b.get('raw', '')} {b.get('final', '')}" for b in b_candidates]
    kept, flags = [], []
    for o in ops:
        if o.get("kind") in ("new", "contradict") and o.get("text") and spans:
            ot = set(content_tokens(o["text"]))
            best = max(spans, key=lambda sp:
                       len(ot & set(content_tokens(sp))))
            if _ONE_OFF_PAT.search(best) and not _RULE_PAT.search(best):
                flags.append(f"one-off-grounded op dropped: "
                             f"{o['text'][:40]!r}")
                continue
        kept.append(o)
    return kept, flags


def _dedup_against_store(ops: list[dict], existing: list[Requirement]
                         ) -> tuple[list[dict], list[str]]:
    """Same fact → update, never a second copy (LightMem/SimpleMem write
    gate). Measured churn on chained stores: one rule learned as four
    entries, then chained into A→B→C supersedes of IDENTICAL text, then
    the whole family retired. A `new` op restating an active entry becomes
    a reinforce of it; a `contradict` whose replacement text changes
    nothing (same tokens, same numbers) likewise — a cap that changes its
    NUMBER is a real update and passes untouched."""
    from memtranslator.signals import content_tokens
    import re as _re
    digits = lambda t: set(_re.findall(r"\d+", t))
    active = [r for r in existing
              if r.status == "active" and r.kind == "requirement"]
    kept, flags = [], []
    by_id = {r.id: r for r in existing}
    for o in ops:
        if o.get("kind") == "new" and o.get("text"):
            ot = set(content_tokens(o["text"]))
            for r in active:
                rt = set(content_tokens(r.text))
                j = len(ot & rt) / max(1, len(ot | rt))
                if j >= 0.7 and digits(o["text"]) == digits(r.text):
                    flags.append(f"duplicate new -> reinforce "
                                 f"{r.text[:40]!r}")
                    o = {"kind": "reinforce", "target_id": r.id}
                    break
        elif o.get("kind") == "contradict" and o.get("text"):
            tgt = by_id.get(o.get("target_id") or "")
            if tgt is not None:
                ot = set(content_tokens(o["text"]))
                rt = set(content_tokens(tgt.text))
                j = len(ot & rt) / max(1, len(ot | rt))
                if j >= 0.8 and digits(o["text"]) == digits(tgt.text):
                    flags.append(f"no-change contradict -> reinforce "
                                 f"{tgt.text[:40]!r}")
                    o = {"kind": "reinforce", "target_id": tgt.id}
        kept.append(o)
    return kept, flags


def _apply_gates(ops: list[dict], a_candidates: list[str],
                 b_candidates: list[dict], existing: list[Requirement]
                 ) -> tuple[list[dict], list[str]]:
    """Named gate chain. MT_ABLATE=name1,name2 skips gates by name — the
    ablation harness's knob; production never sets it."""
    import os
    ablated = set(filter(None, os.environ.get("MT_ABLATE", "").split(",")))
    chain = [
        ("atomise", lambda o: _atomise_ops(o)),
        ("ground", lambda o: _ground_destructive_ops(
            o, a_candidates, b_candidates, existing)),
        ("intent", lambda o: _gate_destructive_intent(
            o, a_candidates, b_candidates, existing)),
        ("facet", lambda o: _gate_contradict_facet(
            o, a_candidates, b_candidates, existing)),
        ("fidelity", lambda o: _gate_op_fidelity(
            o, a_candidates, b_candidates)),
        ("oneoff", lambda o: _gate_one_off(o, a_candidates, b_candidates)),
        ("wnew", lambda o: _gate_withdrawal_new(
            o, a_candidates, b_candidates, existing)),
        ("dedup", lambda o: _dedup_against_store(o, existing)),
    ]
    flags: list[str] = []
    for name, fn in chain:
        if name in ablated:
            continue
        ops, f = fn(ops)
        flags += f
    return ops, flags


def _unaccounted_rule_spans(a_candidates: list[str], ops: list[dict],
                            existing: list[Requirement]) -> list[str]:
    """Spans that screening admitted for a rule-shaped reason but that no
    surviving op accounts for — the measured W1b class: the signal reached
    the model and silently produced nothing."""
    from memtranslator.signals import (_CORRECTION_PAT, _META_PAT,
                                       _RULE_PAT, _WITHDRAW_PAT,
                                       content_tokens, overlap_is_reference)
    by_id = {r.id: r for r in existing}
    silent = []
    for sp in a_candidates:
        if not (_RULE_PAT.search(sp) or _META_PAT.search(sp)
                or _WITHDRAW_PAT.search(sp) or _CORRECTION_PAT.search(sp)):
            continue
        st = content_tokens(sp)
        covered = False
        for o in ops:
            ot = content_tokens(o.get("text", ""))
            if ot and overlap_is_reference(st, ot):
                covered = True
                break
            tgt = by_id.get(o.get("target_id") or "")
            if tgt is not None and overlap_is_reference(
                    st, content_tokens(tgt.text)):
                covered = True
                break
        if not covered:
            silent.append(sp)
    return silent


VERIFY_SYSTEM = """You check extracted requirement entries against their source sentences.
For each numbered pair, the ENTRY must keep the SOURCE's rule intact on
three points only: direction (a minimum stays a minimum, a maximum stays a
maximum), negation (a ban stays a ban, a requirement stays a requirement),
and numbers (every number carried over unchanged). Wording, language, and
how broadly the rule is stated may all differ — judging the right category
breadth is another layer's job, not yours.
Output strictly one JSON object mapping each number to "ok" or "bad". No
other text."""


def _verify_ops(ops: list[dict], a_candidates: list[str],
                b_candidates: list[dict]) -> tuple[list[dict], list[str]]:
    """Birth-time fidelity vote (async budget, ≤1 call per flush): pair
    each text op with its best-grounding span and let one strict call mark
    distortions while the source is still in hand — after apply the span
    is gone and a drifted entry can never be re-checked. Parse failure or
    an unmatched number keeps the op (fail-open: this vote may only ever
    remove)."""
    from memtranslator.signals import content_tokens
    spans = list(a_candidates) + [
        f"{b.get('raw', '')} {b.get('final', '')}" for b in b_candidates]
    textops = [(i, o) for i, o in enumerate(ops)
               if o.get("kind") in ("new", "contradict") and o.get("text")]
    if not textops or not spans:
        return ops, []
    lines = []
    for n, (_i, o) in enumerate(textops, 1):
        ot = set(content_tokens(o["text"]))
        best = max(spans, key=lambda sp: len(ot & set(content_tokens(sp))))
        lines.append(f"[{n}] ENTRY: {o['text']}\n    SOURCE: {best}")
    writer = MODELS.get("writer") or MODELS["translator"]
    try:
        raw = llm.complete(writer, VERIFY_SYSTEM,
                           "\n".join(lines) + "\n\nJSON:",
                           max_tokens=llm.budget_for(
                               writer, 30 * len(textops) + 150),
                           temperature=GEN_TEMPERATURE)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        verdicts = json.loads(m.group(0)) if m else {}
    except Exception:
        return ops, []
    bad_idx = {textops[int(k) - 1][0] for k, v in verdicts.items()
               if isinstance(v, str) and v.strip().lower() == "bad"
               and k.isdigit() and 1 <= int(k) <= len(textops)}
    kept, flags = [], []
    for i, o in enumerate(ops):
        if i in bad_idx:
            flags.append(f"fidelity vote dropped: {o.get('text', '')[:40]!r}")
            continue
        kept.append(o)
    return kept, flags


def run_a_extraction(a_candidates: list[str],
                     existing: list[Requirement]) -> dict:
    """Route A: the user's own messages, one call."""
    from memtranslator.config import WRITE_RECHECK, WRITE_VERIFY
    user = build_a_user_prompt(a_candidates, existing)
    writer = MODELS.get("writer") or MODELS["translator"]
    raw = llm.complete(writer, A_EXTRACTION_SYSTEM, user,
                       max_tokens=llm.budget_for(writer, 1500),
                       temperature=GEN_TEMPERATURE)
    ops, flags = parse_ops(raw, existing)
    ops, gate_flags = _apply_gates(ops, a_candidates, [], existing)
    flags += gate_flags
    if WRITE_RECHECK:
        silent = _unaccounted_rule_spans(a_candidates, ops, existing)
        if silent:
            # Coverage recheck (async budget, ≤1 call per flush): the spans
            # below cleared screening for a rule-shaped reason yet produced
            # no op — the measured dominant never-learned class. A focused
            # second look either extracts or explicitly ignores them; all
            # gates re-apply, so precision discipline is unchanged.
            user2 = (build_a_user_prompt(silent, existing)
                     + "\n\n(Second pass: the spans above matched durable-"
                       "rule signals but produced no operation. For each, "
                       "either emit the correct operations or emit nothing "
                       "if it is noise or a one-task spec.)")
            raw2 = llm.complete(writer, A_EXTRACTION_SYSTEM, user2,
                                max_tokens=llm.budget_for(writer, 1000),
                                temperature=GEN_TEMPERATURE)
            ops2, f2 = parse_ops(raw2, existing)
            # a reinforce from the second look adds nothing but displaces
            # the contradict the span was silent about (measured: relation
            # family regressions were all old-rule reinforces from here)
            ops2 = [o for o in ops2 if o.get("kind") != "reinforce"]
            ops2, g2 = _apply_gates(ops2, silent, [], existing)
            # the recheck may re-emit a first-pass op verbatim — near-
            # identical text ops are the first pass's, not additions
            from memtranslator.signals import content_tokens as _ct
            first = [set(_ct(o["text"])) for o in ops if o.get("text")]
            fresh = []
            for o in ops2:
                if o.get("text"):
                    ot = set(_ct(o["text"]))
                    if any(len(ot & ft) / max(1, len(ot | ft)) >= 0.7
                           for ft in first):
                        continue
                fresh.append(o)
            flags += [f"recheck: {len(silent)} silent span(s), "
                      f"{len(fresh)} new op(s)"] + f2 + g2
            ops += fresh
    if WRITE_VERIFY:
        ops, vflags = _verify_ops(ops, a_candidates, [])
        flags += vflags
    return {"ops": ops, "flags": flags}


def run_b_extraction(candidates: list[dict]) -> dict:
    """Route B: one call over a batch of {entries, diff} signals. The budget
    is smaller than route A's because the output is one short judgement per
    signal-entry pair, never a sweep of the store.

    The gate chain does not apply here. Every gate exists to stop route A
    from aiming a destructive op at an entry the user never referred to;
    route B's targets are the entries the patch demonstrably used, and its
    only destructive op already needs a second vote to bite."""
    user = build_b_user_prompt(candidates)
    writer = MODELS.get("writer") or MODELS["translator"]
    raw = llm.complete(writer, B_EXTRACTION_SYSTEM, user,
                       max_tokens=llm.budget_for(writer, 900),
                       temperature=GEN_TEMPERATURE)
    ops, flags = parse_feedback_ops(raw, candidates)
    return {"ops": ops, "flags": flags}


def run_extraction(a_candidates: list[str], b_candidates: list[dict],
                   existing: list[Requirement]) -> dict:
    """Compatibility entry point for route A. The routes no longer share an
    operation vocabulary or an executor, so a mixed call cannot be honoured:
    route B's judgements go to `Store.apply_feedback_ops`, not `apply_ops`."""
    if b_candidates:
        raise ValueError("route B must use run_b_extraction")
    return run_a_extraction(a_candidates, existing)
