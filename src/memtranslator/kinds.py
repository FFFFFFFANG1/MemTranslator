"""Write-time work-kind tagging + read-time zero-LLM matching (2026-07-30).

Why this exists: selection quality, not ranking. Style/format rules share no
vocabulary with the tasks they govern, so every lexical ranker degrades to a
recency lottery, and a capped top-N drops genuinely applicable rules
whenever more than N apply (measured: many rounds carry 10-23 applicable
rules). The fix pays the semantic cost on the WRITE path — tags each stored
rule with the work kinds it governs — so the read path becomes a mechanical
filter: keep the rules whose kinds cover this request's kind, inject them
all, and only trim on a safety valve.

Product kinds are open slugs (seed email|report|postmortem|code|any plus
store-invented values). Genre filtering lives here; scope holds free
key:value narrowness only.

Degradation contract: an entry with EMPTY kinds (legacy store, annotation
failure, mocked LLM) always matches — the filter can only ever narrow with
evidence, never drop on missing information (same principle recall's scope
filter follows).
"""
import json
import re

from memtranslator import llm
from memtranslator.config import MODELS
from memtranslator.schema import WORK_KIND_ANY, WORK_KINDS
from memtranslator.scopes import normalize_kind

# Compatibility names retained for callers; schema.py owns the seed.
TASK_KINDS = WORK_KINDS
KIND_ANY = WORK_KIND_ANY

KINDS_SYSTEM = """You classify a user's stored preference rules by which kinds of work they govern.
Prefer the seed kinds email, report, postmortem, code, or any. You may use a
new short English slug only when none of those fit (e.g. weekly_report).
For each numbered rule decide which kinds it governs:
- a rule naming a specific deliverable governs only the kind covering that deliverable;
- a rule about output shape (length, line width, sentence/word/row counts, headings, tables, tone, emoji, wording, style) with no named deliverable governs "any";
- a rule about code constructs, tooling, naming, comments, or program structure governs "code".
Output strictly one JSON object mapping each number to a list of kind slugs. No other text."""

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

# Seed-only aliases when context.task uses historical spellings.
_SEED_ALIASES = {"code_write": "code", "coding": "code"}

# prose-document family: a rule tagged for one written-document kind covers
# the sibling kinds (a postmortem IS a prose document; measured misses were
# document rules tagged report firing on postmortem rounds).
_PROSE = {"report", "postmortem"}


def infer_task_kind(query: str, context: dict | None = None) -> str | None:
    """Zero-LLM: explicit context.task wins (any normalised slug); otherwise
    earliest seed lexicon marker in the request text; None when nothing
    matches (= no filtering)."""
    context = context or {}
    raw = context.get("task")
    if raw is not None and str(raw).strip():
        slug = normalize_kind(str(raw))
        return _SEED_ALIASES.get(slug, slug)
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
    family bridges report<->postmortem. No silent parent-child beyond that."""
    if (not kinds or tkind is None or KIND_ANY in kinds
            or "agent_response" in kinds):
        return True
    normalised = {normalize_kind(k) for k in kinds if str(k).strip()}
    tkind = normalize_kind(tkind)
    tkind = _SEED_ALIASES.get(tkind, tkind)
    if tkind in normalised:
        return True
    if tkind in _PROSE and _PROSE & normalised:
        return True
    return False


def _annotate_raw(texts: list[str]) -> tuple[list[list[str]], bool]:
    """Returns (tags, call_failed). call_failed=True only when the LLM call
    itself raised — a successful reply that parses to nothing is a model
    answer, not an outage, and is not worth retrying."""
    block = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
    call_failed = False
    try:
        writer = MODELS.get("writer") or MODELS["translator"]
        raw = llm.complete(writer, KINDS_SYSTEM,
                           block + "\n\nJSON:",
                           max_tokens=llm.budget_for(
                               writer, 60 * len(texts) + 200),
                           temperature=0)
    except Exception:
        raw, call_failed = "", True
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}
    out = []
    for i in range(len(texts)):
        vals = parsed.get(str(i + 1), [])
        if not isinstance(vals, list):
            vals = []
        cleaned = []
        for v in vals:
            if isinstance(v, str) and v.strip():
                cleaned.append(normalize_kind(v))
        out.append(list(dict.fromkeys(cleaned)))
    return out, call_failed


def annotate_kinds(texts: list[str]) -> list[list[str]]:
    """One batched flash call tagging each rule text. Any failure — call,
    parse, unknown label — yields [] (untagged) for the affected entries so
    the read path degrades to no filtering, never to a wrong drop."""
    if not texts:
        return []
    return _annotate_raw(texts)[0]
