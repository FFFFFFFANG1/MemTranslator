"""Derivations: gold validity at any prefix (a pure fold over the authored
effect log) and the scope projection into the product's runtime.

VALIDITY is constructively true: the log's author decided every effect, so
"is c still valid after seq N" is a lookup, never a judgment. The fold's
semantics deliberately mirror `memtranslator.store.Store.apply_ops` +
`bump_strength` — tests/test_gold_matches_store.py fuzzes that the two are
homomorphic (gold's four dead reasons project onto the store's two statuses).

Four dead reasons, and why the taxonomy exists at all: SUPPRESS attribution.
"The system carried a superseded rule" and "the system carried a withdrawn
rule" are different product defects; a two-valued gold could score them but
not attribute them.
"""
from dataclasses import dataclass, field

from memtranslator.store import AUTO_RETIRE_AT

from bench_archive.graph.schema import ANY, SCOPE_DIMS

DEAD_REASONS = ("superseded", "withdrawn", "merged", "auto_retired")


@dataclass
class Effect:
    """One authored effect. seq is the round number it lands on."""
    seq: int
    kind: str                            # assert|reinforce|contradict|retire|merge|bump
    cid: str = ""                        # the (new) constraint introduced
    target: str = ""                     # contradict/retire target
    targets: tuple = ()                  # merge targets
    delta: int = 0                       # bump only


@dataclass
class GoldState:
    status: str = "active"               # active | one of DEAD_REASONS
    strength: int = 1
    since_seq: int = 0                   # when this status was entered
    superseded_by: str = ""


def fold(effects: list[Effect], upto_seq: int | None = None) -> dict:
    """Effect log → {cid: GoldState} at the given prefix. Order within a seq
    follows list order (the author wrote the log; ties are authored too)."""
    st: dict[str, GoldState] = {}
    for e in sorted(effects, key=lambda x: x.seq):
        if upto_seq is not None and e.seq > upto_seq:
            break
        if e.kind == "assert":
            st[e.cid] = GoldState(since_seq=e.seq)
        elif e.kind == "reinforce":
            t = st.get(e.target)
            if t:
                t.strength += 1
        elif e.kind == "contradict":
            t = st.get(e.target)
            if t is None:
                continue                 # unknown target: skipped, like the store
            if t.status == "active":
                t.status, t.since_seq = "superseded", e.seq
                t.superseded_by = e.cid
            st[e.cid] = GoldState(since_seq=e.seq)
        elif e.kind == "retire":
            t = st.get(e.target)
            if t and t.status == "active":
                t.status, t.since_seq = "withdrawn", e.seq
        elif e.kind == "merge":
            ts = [st.get(t) for t in e.targets]
            if len(e.targets) < 2 or any(t is None for t in ts):
                continue
            for tid, t in zip(e.targets, ts):
                if t.status == "active":
                    t.status, t.since_seq = "merged", e.seq
                    t.superseded_by = e.cid
            st[e.cid] = GoldState(since_seq=e.seq)
        elif e.kind == "bump":
            t = st.get(e.target)
            if t is None:
                continue
            t.strength += e.delta
            if t.strength <= AUTO_RETIRE_AT and t.status == "active":
                t.status, t.since_seq = "auto_retired", e.seq
    return st


def valid_at(effects: list[Effect], seq: int) -> set[str]:
    return {cid for cid, s in fold(effects, seq).items()
            if s.status == "active"}


def project_status(state: GoldState) -> str:
    """Gold's reasons → the product's two-valued STATUSES."""
    return "active" if state.status == "active" else "retired"


# ---------------------------------------------------------------------------
# scope: bench semantics + projection into the product
# ---------------------------------------------------------------------------

def scope_compatible(scope: dict, context: dict) -> bool:
    """Bench-side activation semantics, mirroring recall._scope_ok: a
    dimension excludes only when the context KNOWS a different value; ANY and
    unknown-context both keep the entry."""
    for d in SCOPE_DIMS:
        want = scope[d]
        if want == ANY:
            continue
        have = context.get(d)
        if have is not None and have != want:
            return False
    return True


def to_product_scope(scope: dict) -> dict:
    """Bench 4-dim scope → the product's {app?, task?, lang?} dict.

    The product's `lang` is one overloaded field serving both natural and
    programming language. Projection rule (spec §4.4): code_lang wins when
    both are concrete, nat_lang otherwise, ANY dims are omitted. This is a
    KNOWN DISTORTION — a rule scoped {code_lang: python, nat_lang: zh-CN}
    cannot round-trip — and it is recorded here rather than worked around,
    because the workaround would be testing a product that does not exist."""
    out = {}
    if scope["app"] != ANY:
        out["app"] = scope["app"]
    if scope["task"] != ANY:
        out["task"] = scope["task"]
    if scope["code_lang"] != ANY:
        out["lang"] = scope["code_lang"]
    elif scope["nat_lang"] != ANY:
        out["lang"] = scope["nat_lang"]
    return out


def to_product_context(context: dict) -> dict:
    """Same projection for the runtime context dict."""
    out = {}
    if context.get("app") is not None:
        out["app"] = context["app"]
    if context.get("task") is not None:
        out["task"] = context["task"]
    if context.get("code_lang") is not None:
        out["lang"] = context["code_lang"]
    elif context.get("nat_lang") is not None:
        out["lang"] = context["nat_lang"]
    return out


def derive_roles(constraints: list, edges: dict) -> dict:
    """cid → chain | duplicate | independent, from graph degree (I9: role is
    DERIVED, never authored — an authored role field would be a second copy
    of the answer sheet).

    edges: {(cid_a, cid_b): relation} for authored + derived edges."""
    roles = {c.cid: "independent" for c in constraints}
    for (a, b), rel in edges.items():
        if rel in ("CONTRADICTS", "A_EXCEPTS_B", "B_EXCEPTS_A",
                   "SUPERSEDES"):
            roles[a] = roles[b] = "chain"
        elif rel == "DUPLICATES":
            for x in (a, b):
                if roles[x] != "chain":
                    roles[x] = "duplicate"
    return roles
