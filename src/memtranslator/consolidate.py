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
entries grouped into GROUPS of possibly-redundant rules, and possibly a
STYLE section of rewrite-style rules exceeding its cap. Within each group,
numbers run OLDEST first — a later number is a more recent statement.

Rules:
1. Entries in one group that express the SAME durable rule (near
   duplicates, translations of each other, the same obligation phrased
   twice) → emit one "merge" with their numbers and a single merged text
   (clearest phrasing, user's language). The merged text PRESERVES every
   number, cap, and named format (a word-count limit, "APA", "snake_case")
   that appears in the entries it replaces — a merge that paraphrases the
   anchor away destroys the rule's testable core. Entries that are
   genuinely different rules → leave alone. When unsure, do NOT merge.
2. Entries in one group that CONFLICT — they govern the same aspect of the
   same kind of work but demand incompatible things (different caps,
   opposite tones, contradictory formats) → do NOT merge them: the LATEST
   number is the user's current preference; emit "retire" for each older
   conflicting number. Resolving the conflict here is the point — a store
   that keeps both sides forces every later rewrite to re-litigate it.
3. Never invent rules, never change meaning while merging, and never
   retire an entry that neither duplicates nor conflicts with a newer one.
4. STYLE section: keep the most broadly useful rules within the stated cap;
   emit "retire" for the numbers to drop (most redundant / narrowest first).

Output STRICTLY a JSON array (possibly empty), nothing else:
[{"op": "merge", "targets": [<num>, <num>, ...], "text": "...",
  "key": "facet.attr", "salience": 4}
 | {"op": "retire", "target": <num>, "salience": 4}]"""


def should_consolidate(store: Store, adds_since: int) -> bool:
    return (len(store.active()) > CONSOLIDATE_ACTIVE
            or adds_since >= CONSOLIDATE_ADDS)


def buckets(reqs: list[Requirement]) -> list[list[Requirement]]:
    """Group possibly-redundant entries for the merge call.

    Bucket first, key second. Two rules can share a facet word and still be
    different rules — "cite your sources" as an evidence standard and "cite in
    APA" as a format both key on citations, and merging them would destroy
    one. Grouping within a bucket makes that impossible by construction
    (docs/2026-07-26-bucket-taxonomy.md). Entries with no bucket keep the old
    key-only behaviour so pre-taxonomy records still deduplicate.

    Pass 2 (2026-07-29): vocabulary-overlap clustering across keys AND
    buckets. Measured miss that motivated it: one replay store held three
    near-identical "email must state the maintenance window and impact"
    rules under different keys/buckets — invisible to key grouping, obvious
    to content_tokens overlap. LLM extraction never spells keys
    consistently enough for exact-match grouping to be the only net.
    Only groups of ≥2 come back; each group is oldest-first (the prompt's
    conflict rule depends on that ordering).
    """
    from memtranslator.signals import content_tokens, overlap_is_reference

    reqs = [r for r in reqs if r.kind == "requirement"]
    out: list[list[Requirement]] = []
    for bucket in sorted({r.bucket for r in reqs}):
        pool = [r for r in reqs if r.bucket == bucket]
        by_key: dict[str, list[Requirement]] = {}
        for r in pool:
            if r.key:
                by_key.setdefault(r.key, []).append(r)
        out += [grp for grp in by_key.values() if len(grp) >= 2]
        singles = [r for r in pool if r.key and len(by_key[r.key]) == 1]
        by_facet: dict[str, list[Requirement]] = {}
        for r in singles:
            by_facet.setdefault(r.key.split(".", 1)[0], []).append(r)
        out += [grp for grp in by_facet.values() if len(grp) >= 2]
        unkeyed = [r for r in pool if not r.key]
        if len(unkeyed) >= 2:
            out.append(unkeyed)

    # pass 2: overlap clusters among entries no earlier group covers
    grouped = {r.id for grp in out for r in grp}
    rest = [r for r in reqs if r.id not in grouped]
    toks = {r.id: content_tokens(r.text) for r in rest}
    parent = {r.id: r.id for r in rest}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(rest):
        for b in rest[i + 1:]:
            if overlap_is_reference(toks[a.id], toks[b.id]):
                parent[find(a.id)] = find(b.id)
    clusters: dict[str, list[Requirement]] = {}
    for r in rest:
        clusters.setdefault(find(r.id), []).append(r)
    out += [grp for grp in clusters.values() if len(grp) >= 2]

    for grp in out:
        grp.sort(key=lambda r: r.created_at)
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

    writer = MODELS.get("writer") or MODELS["translator"]
    raw = llm.complete(writer, CONSOLIDATE_SYSTEM,
                       "\n\n".join(parts),
                       max_tokens=llm.budget_for(writer, 1200),
                       temperature=GEN_TEMPERATURE)
    ops, flags = parse_ops(raw, numbered)
    by_id = {r.id: r for r in numbered}
    ops, aflags = _drop_anchor_losing_merges(ops, by_id)
    ops, nflags = _sanitize_ops(ops, by_id)
    return {"ops": ops, "flags": flags + aflags + nflags}


def _sanitize_ops(ops: list[dict], by_id: dict
                  ) -> tuple[list[dict], list[str]]:
    """Zero-LLM guards against consolidation over-eagerness, measured on a
    chained-store replay (2026-07-30): rules the write path had learned
    CORRECTLY ended up retired — unrelated entries glued into one compound
    "merge" (its sources retired with it), plus bare retires that resolved
    no conflict. Three mechanical drops, all erring toward keeping entries:

    1. a merge whose sources share not a single content token is not a
       dedup — different rules stay separate;
    2. a retire aimed at an entry a same-batch merge already consumes is
       double bookkeeping;
    3. a retire whose target shares no content token with any entry that
       SURVIVES the batch is deletion, not conflict resolution — rule 2
       retires an entry because a newer conflicting statement exists, and
       "conflicting" is checkable as content overlap with a survivor.
    """
    from memtranslator.signals import content_tokens
    merged_ids = set()
    for o in ops:
        if o.get("kind") == "merge":
            merged_ids |= set(o.get("target_ids") or [])
    retired_ids = {o.get("target_id") for o in ops if o.get("kind") == "retire"}
    out, flags = [], []
    for o in ops:
        if o.get("kind") == "merge":
            srcs = [by_id[t].text for t in (o.get("target_ids") or [])
                    if t in by_id]
            toks = [set(content_tokens(t)) for t in srcs]
            def _script(t):
                return "cjk" if sum("一" <= ch <= "鿿" for ch in t) > \
                    len(t) * 0.25 else "latin"
            same_script = len({_script(t) for t in srcs}) == 1
            # Cross-script sources are plausibly translations of each other
            # (rule 1 merges those); token overlap cannot see that, so the
            # disjoint check only applies within one script. The anchor
            # guard still vets numbers on every merge.
            if (len(toks) >= 2 and same_script
                    and not set.intersection(*toks)):
                flags.append(f"disjoint merge dropped: "
                             f"{o.get('text', '')[:40]!r}")
                continue
            # Cross-facet compound guard (loop-7): sources under DIFFERENT
            # facet keys may merge only as near-duplicates (sloppy key
            # spellings of one rule — the measured maintenance-window
            # triple). Weakly-related texts under different keys are two
            # rules; compounding them sets up the collateral kill where a
            # supersede on one facet buries the other.
            srcs_r = [by_id[t] for t in (o.get("target_ids") or [])
                      if t in by_id]
            keys = {r.key for r in srcs_r if r.key}
            if len(keys) >= 2 and len(toks) >= 2:
                jmin = min(
                    len(a & b) / max(1, len(a | b))
                    for i, a in enumerate(toks) for b in toks[i + 1:])
                if jmin < 0.5:
                    flags.append(f"cross-facet merge dropped: "
                                 f"{o.get('text', '')[:40]!r}")
                    continue
        if o.get("kind") == "retire":
            tid = o.get("target_id")
            if tid in merged_ids:
                flags.append(f"redundant retire of merged source {tid}")
                continue
            target = by_id.get(tid)
            if target is not None:
                tt = set(content_tokens(target.text))
                survivors = [r for r in by_id.values()
                             if r.id != tid and r.id not in retired_ids
                             and r.id not in merged_ids]
                best, best_ov = None, 0
                for r in survivors:
                    ov = len(tt & set(content_tokens(r.text)))
                    if ov > best_ov:
                        best, best_ov = r, ov
                merge_ov = any(tt & set(content_tokens(o2.get("text", "")))
                               for o2 in ops if o2.get("kind") == "merge")
                if tt and best is None and not merge_ov:
                    flags.append(f"contentless retire dropped: {tid}")
                    continue
                # A consolidation retire is conflict resolution: the entry
                # that won the conflict is the victim's heir. Recording it
                # keeps the kill invariant-compliant (never heirless) and
                # makes the victim resurrectable if the winner later dies.
                if best is not None:
                    o = {**o, "heir_id": best.id}
        out.append(o)
    return out, flags


def _anchor_tokens(text: str) -> set:
    """Digit-bearing tokens — the mechanically checkable core of a rule
    (word caps, counts, versions). Named formats are covered by the prompt
    line; numbers are enforced here because they are exactly what the
    lifecycle bench aligns STATE on, and the measured failure was a merge
    paraphrasing a cap away (E1 round-3: e-05 STATE 0.60→0.51 while
    consolidation went from never firing to 17 triggers)."""
    from memtranslator.bm25 import tokenize
    return {t for t in tokenize(text) if any(c.isdigit() for c in t)}


def _drop_anchor_losing_merges(ops: list[dict], by_id: dict
                               ) -> tuple[list[dict], list[str]]:
    """Zero-LLM guard: a merge whose text loses a numeric anchor present in
    any source entry is dropped whole — the sources stay live, which is
    strictly safer than a lossy merge. Two sources with DIFFERENT numbers
    also land here: that pair is a conflict, not a duplicate, and the
    conflict path (retire the older) is the correct resolution."""
    kept, flags = [], []
    for o in ops:
        if o["kind"] == "merge":
            need = set()
            for tid in o.get("target_ids", []):
                src = by_id.get(tid)
                if src is not None:
                    need |= _anchor_tokens(src.text)
            have = _anchor_tokens(o.get("text", ""))
            if need - have:
                flags.append(f"merge dropped, loses anchors {need - have}: "
                             f"{o.get('text', '')[:40]!r}")
                continue
        kept.append(o)
    return kept, flags


def run_consolidation(store: Store) -> dict:
    out = consolidation_ops(store.active())
    applied = store.apply_ops(out["ops"])
    from memtranslator.kinds import backfill_kinds
    backfill_kinds(store)               # merged entries re-enter untagged
    return {"ops": out["ops"], "flags": out["flags"], "store": applied}
