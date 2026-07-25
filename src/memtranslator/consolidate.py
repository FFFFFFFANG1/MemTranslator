"""Write-path call #2: low-frequency store tidying (design §6).

Mechanical bucketing first — exact facet key, then same-facet prefix for the
leftovers — and ONLY buckets with ≥2 entries reach the prompt, so most
trigger checks return without any LLM call. Entries are shown to the model
with global index numbers (design R6); ops come back through the same
numbered-candidate parser as extraction. Style_rule curation rides the same
call when the cap is exceeded.
"""
from memtranslator import llm
from memtranslator.config import (CONSOLIDATE_ACTIVE, CONSOLIDATE_ADDS,
                                  GEN_TEMPERATURE, MODELS, STYLE_RULE_CAP)
from memtranslator.extraction import _index_block, parse_ops
from memtranslator.schema import Requirement
from memtranslator.store import Store

CONSOLIDATE_SYSTEM = """You tidy a store of a user's delivery requirements. You receive numbered
entries grouped into BUCKETS of possibly-redundant rules, and possibly a
STYLE section of rewrite-style rules exceeding its cap.

Rules:
1. Within a bucket, entries that express the SAME durable rule (near
   duplicates, translations of each other) → emit one "merge" with their
   numbers and a single merged text (clearest phrasing, user's language).
   Entries that are genuinely different rules → leave alone. When unsure,
   do NOT merge.
2. Never invent rules, never change meaning while merging.
3. STYLE section: keep the most broadly useful rules within the stated cap;
   emit "retire" for the numbers to drop (most redundant / narrowest first).

Output STRICTLY a JSON array (possibly empty), nothing else:
[{"op": "merge", "targets": [<num>, <num>, ...], "text": "...",
  "key": "facet.attr", "salience": 4}
 | {"op": "retire", "target": <num>, "salience": 4}]"""


def should_consolidate(store: Store, adds_since: int) -> bool:
    return (len(store.active()) > CONSOLIDATE_ACTIVE
            or adds_since >= CONSOLIDATE_ADDS)


def buckets(reqs: list[Requirement]) -> list[list[Requirement]]:
    """Exact-key buckets, then same-facet buckets for the leftovers, then one
    unclassified bucket: manually added entries carry no key, and they must
    still be deduplicable — the model decides equivalence, we only group.
    Only groups of ≥2 come back."""
    reqs = [r for r in reqs if r.kind == "requirement"]
    by_key: dict[str, list[Requirement]] = {}
    for r in reqs:
        if r.key:
            by_key.setdefault(r.key, []).append(r)
    out = [grp for grp in by_key.values() if len(grp) >= 2]
    leftovers = [r for r in reqs
                 if r.key and len(by_key[r.key]) == 1]
    by_facet: dict[str, list[Requirement]] = {}
    for r in leftovers:
        by_facet.setdefault(r.key.split(".", 1)[0], []).append(r)
    out += [grp for grp in by_facet.values() if len(grp) >= 2]
    unkeyed = [r for r in reqs if not r.key]
    if len(unkeyed) >= 2:
        out.append(unkeyed)
    return out


def consolidation_ops(reqs: list[Requirement]) -> dict:
    """Pure half of consolidation: bucket → (maybe) call → parsed ops.
    Persisting is the caller's job — the bench adapter grades these ops
    directly, the product path applies them via run_consolidation."""
    active = [r for r in reqs if r.status == "active"]
    bucket_groups = buckets(active)
    styles = [r for r in active if r.kind == "style_rule"]
    style_over = len(styles) > STYLE_RULE_CAP

    if not bucket_groups and not style_over:
        return {"ops": [], "flags": []}

    numbered: list[Requirement] = []
    for grp in bucket_groups:
        numbered += grp
    if style_over:
        numbered += styles
    pos = {r.id: n for n, r in enumerate(numbered, 1)}

    parts = [f"ENTRIES:\n{_index_block(numbered)}"]
    if bucket_groups:
        lines = [" & ".join(f"[{pos[r.id]}]" for r in grp)
                 for grp in bucket_groups]
        parts.append("BUCKETS (each line = one possibly-redundant group):\n"
                     + "\n".join(lines))
    if style_over:
        nums = ", ".join(f"[{pos[r.id]}]" for r in styles)
        parts.append(f"STYLE section: entries {nums} are rewrite-style "
                     f"rules; keep at most {STYLE_RULE_CAP}, retire the rest.")
    parts.append("JSON:")

    raw = llm.complete(MODELS["translator"], CONSOLIDATE_SYSTEM,
                       "\n\n".join(parts), max_tokens=1200,
                       temperature=GEN_TEMPERATURE)
    ops, flags = parse_ops(raw, numbered)
    return {"ops": ops, "flags": flags}


def run_consolidation(store: Store) -> dict:
    out = consolidation_ops(store.active())
    applied = store.apply_ops(out["ops"])
    return {"ops": out["ops"], "flags": out["flags"], "store": applied}
