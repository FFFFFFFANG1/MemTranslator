"""Write-time work-kind tagging + read-time zero-LLM matching (2026-07-30).

Why this exists: selection quality, not ranking. Style/format rules share no
vocabulary with the tasks they govern, so every lexical ranker degrades to a
recency lottery, and a capped top-N drops genuinely applicable rules
whenever more than N apply (measured: many rounds carry 10-23 applicable
rules). The fix pays the semantic cost on the WRITE path — one batched
flash call tags each stored rule with the work kinds it governs — so the
read path becomes a mechanical filter: keep the rules whose kinds cover
this request's kind, inject them all, and only trim on a safety valve.

Degradation contract: an entry with EMPTY kinds (legacy store, annotation
failure, mocked LLM) always matches — the filter can only ever narrow with
evidence, never drop on missing information (same principle recall's scope
filter follows).
"""
import json
import re

from memtranslator import llm
from memtranslator.config import MODELS

TASK_KINDS = ("email", "report", "postmortem", "code")
KIND_ANY = "any"

KINDS_SYSTEM = """You classify a user's stored preference rules by which kinds of work they govern.
Work kinds: email (emails and messages), report (prose document deliverables: reports, articles, summaries, slide decks, write-ups), postmortem (incident write-ups), code (writing code or scripts).
For each numbered rule decide which kinds it governs:
- a rule naming a specific deliverable governs only the kind covering that deliverable;
- a rule about output shape (length, line width, sentence/word/row counts, headings, tables, tone, emoji, wording, style) with no named deliverable governs "any";
- a rule about code constructs, tooling, naming, comments, or program structure governs "code".
Output strictly one JSON object mapping each number to a list drawn from ["email","report","postmortem","code","any"]. No other text."""

# Query-side task-kind markers, earliest match wins. Deliberately short
# strings (spelling-level), no bench phrases.
_MARKERS = {
    "email": ["邮件", "email", "写封邮", "回封邮"],
    "code": ["脚本", "函数", "代码", "script", "function", "写个go",
             "写个python", "重构", "cli"],
    "postmortem": ["postmortem", "复盘"],
    "report": ["报告", "report", "周报", "月报", "摘要", "summary",
               "总结", "slide", "deck", "文章", "简报"],
}

_CTX_TASK = {"email": "email", "report": "report",
             "postmortem": "postmortem",
             "code-write": "code", "code_write": "code", "code": "code"}

# prose-document family: a rule tagged for one written-document kind covers
# the sibling kinds (a postmortem IS a prose document; measured misses were
# document rules tagged report firing on postmortem rounds).
_PROSE = {"report", "postmortem"}


def infer_task_kind(query: str, context: dict | None = None) -> str | None:
    """Zero-LLM: explicit context wins; otherwise earliest lexicon marker in
    the request text; None when nothing matches (= no filtering)."""
    context = context or {}
    t = _CTX_TASK.get(str(context.get("task", "")).lower())
    if t:
        return t
    low = query.lower()
    best, best_pos = None, None
    for kind, markers in _MARKERS.items():
        for m in markers:
            p = low.find(m)
            if p >= 0 and (best_pos is None or p < best_pos):
                best, best_pos = kind, p
    return best


def kind_matches(kinds: list, tkind: str | None) -> bool:
    """Empty kinds / "any" / unknown task kind always match; the prose
    family bridges report<->postmortem."""
    if not kinds or tkind is None or KIND_ANY in kinds or tkind in kinds:
        return True
    if tkind in _PROSE and _PROSE & set(kinds):
        return True
    return False


def _annotate_raw(texts: list[str]) -> tuple[list[list[str]], bool]:
    """Returns (tags, call_failed). call_failed=True only when the LLM call
    itself raised — a successful reply that parses to nothing is a model
    answer, not an outage, and is not worth retrying."""
    block = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
    call_failed = False
    try:
        raw = llm.complete(MODELS["translator"], KINDS_SYSTEM,
                           block + "\n\nJSON:",
                           max_tokens=60 * len(texts) + 200, temperature=0)
    except Exception:
        raw, call_failed = "", True
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}
    allowed = set(TASK_KINDS) | {KIND_ANY}
    out = []
    for i in range(len(texts)):
        vals = parsed.get(str(i + 1), [])
        if not isinstance(vals, list):
            vals = []
        out.append([v for v in vals if v in allowed])
    return out, call_failed


def annotate_kinds(texts: list[str]) -> list[list[str]]:
    """One batched flash call tagging each rule text. Any failure — call,
    parse, unknown label — yields [] (untagged) for the affected entries so
    the read path degrades to no filtering, never to a wrong drop."""
    if not texts:
        return []
    return _annotate_raw(texts)[0]

def backfill_kinds(store) -> int:
    """Tag every active untagged requirement in one batched call — covers
    fresh extractions, consolidation merges, and legacy entries alike
    (self-healing: whatever slipped through gets tagged on the next flush).
    Returns how many entries were tagged.

    Retries with backoff, but only when the CALL failed (429/outage): this
    runs right after an extraction flush, i.e. at the top of a rate-limit
    burst, and a swallowed 429 here left whole chained stores untagged
    (measured 2026-07-30: 1-2/17 tagged) — which silently switches off
    every read-side feature that keys on the tags. The write path is
    asynchronous; sleeping is free. A successful-but-empty reply is a model
    answer and is left for the next flush's self-heal instead.
    """
    import time as _time
    todo = [r for r in store.active()
            if r.kind == "requirement" and not r.kinds]
    if not todo:
        return 0
    texts = [r.text for r in todo]
    tags, failed = _annotate_raw(texts)
    for delay in (1.0, 4.0):
        if not failed:
            break
        _time.sleep(delay)
        tags, failed = _annotate_raw(texts)
    n = 0
    for r, k in zip(todo, tags):
        if k:
            r.kinds = k
            if hasattr(store, "persist"):
                store.persist(r)
            n += 1
    return n
