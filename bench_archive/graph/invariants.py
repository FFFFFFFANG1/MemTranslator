"""Build-time invariants over an episode's constraint graph. Zero LLM, zero
opinion — every check is mechanical, and a violation is a CASE-FILE bug, not
a product finding. Nothing here ever grades the system under test.

I4 and I6 from the original design are gone and their replacements are I10
and I11:

- I4 ("DUPLICATES must be merged") was circular: DUPLICATES only fires when
  a.key == b.key, and the way real duplicates get lost is precisely that the
  key got split — which deletes the edge the check would have read. I10 flags
  exactly that class (textually near, graph-independent) at zero cost.
- I6 keyed traps to shared key prefixes, but the SUT invents its own keys
  (open vocabulary, extraction rule 4), so bench-key assertions never touch
  the runtime. Alignment goes through distinctive token families instead, and
  I11 checks trap REACHABILITY: a must_not_fire trap that no lifecycle-free
  baseline would even inject is a free point for everyone — the audit
  simulated cp-06/07/08 and found 57-77% of naive trap placements were
  exactly that.
"""
from collections import defaultdict
from itertools import combinations

from memtranslator.bm25 import BM25, tokenize
from memtranslator.config import RECALL_CAP

from bench_archive.graph.derive import fold, scope_compatible, valid_at
from bench_archive.graph.relate import (CONTRADICTS, DUPLICATES, INDEPENDENT,
                                PARTIAL_CONFLICT, relate)

I10_JACCARD = 0.5


def _pairs(constraints):
    return combinations(constraints, 2)


def check_i1(constraints, effects, checkpoints) -> list[str]:
    """No CONTRADICTS pair is simultaneously active at any checkpoint."""
    errs = []
    by_cid = {c.cid: c for c in constraints}
    for cp in checkpoints:
        live = [by_cid[cid] for cid in valid_at(effects, cp) if cid in by_cid]
        for a, b in _pairs(live):
            if relate(a, b) == CONTRADICTS:
                errs.append(f"I1 cp-{cp}: {a.cid} and {b.cid} both active "
                            f"but CONTRADICTS")
    return errs


def check_i2(effects) -> list[str]:
    """Supersede chains propagate: if a superseded b and c later supersedes
    a, the final fold must show every ancestor dead. Checked over the
    transitive closure, not just direct edges."""
    errs = []
    final = fold(effects)
    supersedes = {e.cid: e.target for e in effects if e.kind == "contradict"}
    for start in supersedes:
        seen, cur = set(), start
        while cur in supersedes and cur not in seen:
            seen.add(cur)
            ancestor = supersedes[cur]
            st = final.get(ancestor)
            if st is not None and st.status == "active" \
                    and final.get(start, None) is not None:
                # an ancestor outliving a live descendant chain head
                errs.append(f"I2: {ancestor} still active although "
                            f"superseded via chain from {start}")
            cur = ancestor
    return errs


def check_i3(constraints) -> list[str]:
    """PARTIAL_CONFLICT pairs are rejected at build time: overlapping,
    non-nested scopes with opposed demands have no fold-decidable winner."""
    return [f"I3: {a.cid} / {b.cid} PARTIAL_CONFLICT"
            for a, b in _pairs(constraints)
            if relate(a, b) == PARTIAL_CONFLICT]


def check_i5(effects) -> list[str]:
    """Monotonicity: once dead, never active again. The product has no op
    that un-retires (only the manual HTTP path), so an episode scripting a
    revival is asserting behaviour the SUT cannot express."""
    errs = []
    seqs = sorted({e.seq for e in effects})
    dead_seen: dict[str, int] = {}
    for s in seqs:
        st = fold(effects, s)
        for cid, g in st.items():
            if g.status != "active" and cid not in dead_seen:
                dead_seen[cid] = s
            elif g.status == "active" and cid in dead_seen:
                errs.append(f"I5: {cid} dead at seq {dead_seen[cid]} but "
                            f"active again at seq {s}")
    return errs


def check_i8(constraints, effects) -> list[str]:
    """Reachability/ordering: every effect target was asserted earlier, and
    every constraint in the catalogue is introduced by exactly one
    assert/contradict/merge effect."""
    errs = []
    introduced_at: dict[str, int] = {}
    for e in sorted(effects, key=lambda x: x.seq):
        if e.kind in ("assert", "contradict", "merge") and e.cid:
            if e.cid in introduced_at:
                errs.append(f"I8: {e.cid} introduced twice")
            introduced_at[e.cid] = e.seq
        targets = list(e.targets) if e.kind == "merge" else \
            ([e.target] if e.target else [])
        for t in targets:
            if t not in introduced_at:
                errs.append(f"I8: seq {e.seq} {e.kind} targets {t} "
                            f"before/without its introduction")
            elif introduced_at[t] > e.seq:
                errs.append(f"I8: seq {e.seq} {e.kind} targets {t} "
                            f"introduced later (seq {introduced_at[t]})")
    for c in constraints:
        if c.cid not in introduced_at:
            errs.append(f"I8: {c.cid} in catalogue but never introduced")
    return errs


def check_i9(constraints, episode_meta: dict) -> list[str]:
    """Role is derived, never authored. The episode file carrying a role
    field would be a second copy of the answer sheet."""
    if "roles" in episode_meta:
        return ["I9: episode file authors a 'roles' field — roles are "
                "derived from graph degree, delete it"]
    return []


def _content_jaccard(a: str, b: str) -> float:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def check_i10(constraints) -> list[str]:
    """Semantic-neighbour gate: textually near but graph-INDEPENDENT pairs
    are exactly what a KEY SPLIT produces. Same-key pairs are exempt — a
    same-key pair that reads INDEPENDENT got there through deliberately
    disjoint scopes (the fleet's manufactured-disjointness admission), which
    is intended construction, not a lost edge."""
    errs = []
    for a, b in _pairs(constraints):
        if a.coords.key == b.coords.key:
            continue
        if relate(a, b) == INDEPENDENT \
                and _content_jaccard(a.text, b.text) >= I10_JACCARD:
            errs.append(f"I10: {a.cid} / {b.cid} textually near "
                        f"(J≥{I10_JACCARD}) but INDEPENDENT — key split?")
    return errs


def simulate_no_retire_injection(constraints, effects, probe) -> set[str]:
    """Which cids a lifecycle-free arm would inject at this probe: everything
    introduced by then (dead included), scope-filtered against the probe
    context, ranked by the product's own BM25 when over the cap. This mirrors
    m1_separation.select_no_retire, on gold structures."""
    by_cid = {c.cid: c for c in constraints}
    introduced = [(e.seq, e.cid) for e in sorted(effects, key=lambda x: x.seq)
                  if e.kind in ("assert", "contradict", "merge")
                  and e.cid and e.seq <= probe["seq"]]
    pool = [by_cid[cid] for _s, cid in introduced if cid in by_cid
            and scope_compatible(by_cid[cid].coords.scope,
                                 probe.get("context") or {})]
    if len(pool) <= RECALL_CAP:
        return {c.cid for c in pool}
    scores = BM25([c.text for c in pool]).scores(probe.get("query", ""))
    seq_of = {cid: s for s, cid in introduced}
    order = sorted(range(len(pool)),
                   key=lambda i: (-scores[i], -seq_of[pool[i].cid]))
    return {pool[i].cid for i in order[:RECALL_CAP]}


def check_i11(constraints, effects, probes) -> list[str]:
    """Trap reachability: every must_not_fire cid must actually be injected
    by the no_retire simulation at that probe — otherwise the trap assertion
    hands free points to any system, lifecycle logic or none."""
    errs = []
    for p in probes:
        traps = p.get("must_not_fire") or []
        if not traps:
            continue
        injected = simulate_no_retire_injection(constraints, effects, p)
        for t in traps:
            if t not in injected:
                errs.append(f"I11: probe seq {p['seq']}: trap {t} is not "
                            f"injected by a no-retire baseline — free point, "
                            f"re-place the trap or tighten the gap")
    return errs


def lint_episode(constraints, effects, probes, checkpoints,
                 episode_meta: dict | None = None) -> list[str]:
    """All invariants over one episode. Empty list = green."""
    errs = []
    errs += check_i8(constraints, effects)      # ordering first: others assume it
    errs += check_i3(constraints)
    errs += check_i1(constraints, effects, checkpoints)
    errs += check_i2(effects)
    errs += check_i5(effects)
    errs += check_i9(constraints, episode_meta or {})
    errs += check_i10(constraints)
    errs += check_i11(constraints, effects, probes)
    return errs
