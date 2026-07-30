"""Read-path recall (design §7): deterministic, zero-LLM, no embeddings.

1. active entries of kind "requirement" (style_rule never joins recall);
2. scope filter — an entry scoped to {task: email} is dropped when the
   context KNOWS the task is something else; unknown dimensions keep the
   entry (never exclude on missing information). Both sides are compared
   through the controlled scope vocabulary (scopes.normalize_scope) so
   spelling variants cannot break the match;
3. injection pre-screen (2026-07-29) — above INJECT_CAP candidates, BM25
   over the entry's own text ranks and only the top slice is injected,
   recency breaking ties, with a facet-freshness guard: a selected entry
   is swapped for an UNSELECTED newer entry with the same key, so the
   newest statement of a facet is never cut while an older one stays.

Why the pre-screen exists: at 32 flat-injected rules the flash translator
refused a task 5/5 with two squarely applicable rules in plain sight; the
same task over 2 injected rules applied 3/3. The failure mode is selection
difficulty across competing conditional rules, not context length (32
rules ≈ 1.1k tokens). Known limit, accepted for now: a semantically
applicable rule sharing no vocabulary with the task scores BM25 zero and
survives only on recency — the adapt-style abstract rules. Semantic
ranking is phase-③ work; the dilution family referees this line.
"""
from memtranslator.bm25 import BM25
from memtranslator.config import INJECT_CAP, STYLE_RULE_CAP
from memtranslator.kinds import infer_task_kind, kind_matches
from memtranslator.schema import Requirement
from memtranslator.scopes import normalize_scope


def _root_terms(text: str) -> list[str]:
    from memtranslator.signals import _KEY_LEXICON
    low = text.lower()
    return [root for root, surfaces in _KEY_LEXICON.items()
            if any(x.lower() in low for x in surfaces)]


def _scope_ok(scope: dict, context: dict) -> bool:
    scope = normalize_scope(scope)
    context = normalize_scope(context)
    for dim, want in scope.items():
        have = context.get(dim)
        if have is not None and have != want:
            return False
    return True


def recall(requirements: list[Requirement], *, query: str = "",
           context: dict | None = None) -> list[Requirement]:
    context = context or {}
    pool = [r for r in requirements
            if r.status == "active" and r.kind == "requirement"
            and _scope_ok(r.scope, context)]
    # Work-kind filter (2026-07-30): the write path tags each rule with the
    # kinds of work it governs; here the request's kind (context, else
    # zero-LLM lexicon) drops the rules for OTHER kinds of work, and every
    # survivor is injected. Selection quality lives in the tags, not in a
    # ranker: measured across the episode suite, style/format rules score
    # BM25 zero against the tasks they govern, so any lexical top-N is a
    # recency lottery that drops applicable rules whenever more than N
    # apply. Untagged entries always survive the filter (legacy stores,
    # annotation failure) — evidence can narrow, absence cannot.
    tkind = infer_task_kind(query, context)
    pool = [r for r in pool if kind_matches(r.kinds, tkind)]
    pool.sort(key=lambda r: r.created_at)
    if len(pool) <= INJECT_CAP:
        return pool
    # Safety valve beyond the cap: BM25 over the entry's own words, recency
    # breaking ties (an old but exactly-on-topic rule must not be dropped
    # on recency alone — M1 measured that failure when ranking keyed on a
    # 14-root lexicon). With English as the store's canonical language a
    # Chinese query shares no surface token with the very rule it targets,
    # so both sides are augmented with lexicon ROOT names — the same bridge
    # content_tokens uses ("会议纪要" and "meeting minutes" both contribute
    # "meeting").
    docs = [f"{r.text} {r.key or ''} {' '.join(_root_terms(r.text))}"
            for r in pool]
    scores = BM25(docs).scores(f"{query} {' '.join(_root_terms(query))}")
    order = sorted(range(len(pool)),
                   key=lambda i: (-scores[i], -pool[i].created_at))
    picked = set(order[:INJECT_CAP])
    # Facet-freshness guard: never inject an OLDER statement of a facet
    # while a newer one sits outside the slice — the read prompt's
    # newest-wins conflict rule only works on what the model can see.
    for i in list(picked):
        for j in range(len(pool)):
            if (j not in picked and pool[j].key and pool[i].key
                    and pool[j].key == pool[i].key
                    and pool[j].created_at > pool[i].created_at):
                picked.discard(i)
                picked.add(j)
                break
    out = [pool[i] for i in sorted(picked)]
    out.sort(key=lambda r: r.created_at)
    return out


def style_block(requirements: list[Requirement]) -> str:
    """Learned rewrite-style rules for the translator prompt, ≤ cap entries
    (~250 tokens). Empty string when none exist — v0 prompt stays byte-equal."""
    styles = [r for r in requirements
              if r.status == "active" and r.kind == "style_rule"]
    if not styles:
        return ""
    styles.sort(key=lambda r: (-r.strength, -r.updated_at))
    lines = "\n".join(f"- {r.text}" for r in styles[:STYLE_RULE_CAP])
    return f"\nRewrite style rules learned from this user's edits:\n{lines}"
