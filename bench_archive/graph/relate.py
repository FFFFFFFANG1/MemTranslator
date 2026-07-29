"""The relation algebra: given two constraints' coords, COMPUTE their
relation. No LLM, no opinion — every edge in the gold graph is either
constructed (we authored the supersede) or derived by this module, and the
derived ones are reproducible from the coords alone.

    relate(a, b) ∈ INDEPENDENT | DUPLICATES | CONTRADICTS
                 | A_EXCEPTS_B | B_EXCEPTS_A | PARTIAL_CONFLICT

Reading:
- DUPLICATES      same rule twice (merge material)
- CONTRADICTS     same scope, incompatible demands (supersede material —
                  which one wins is temporal, not algebraic)
- A_EXCEPTS_B     a is a narrower exception carved out of b; both stay live
- PARTIAL_CONFLICT overlapping-but-not-nested scopes with incompatible
                  demands. No fold can decide who wins where, so I3 rejects
                  these at BUILD time — an episode must never contain one.
"""
from bench_archive.graph.schema import ANY, SCOPE_DIMS, Value, positive

# scope box relations
EQUAL, A_WITHIN_B, B_WITHIN_A, OVERLAP, DISJOINT = (
    "EQUAL", "A_WITHIN_B", "B_WITHIN_A", "OVERLAP", "DISJOINT")

# constraint relations
(INDEPENDENT, DUPLICATES, CONTRADICTS, A_EXCEPTS_B, B_EXCEPTS_A,
 PARTIAL_CONFLICT) = ("INDEPENDENT", "DUPLICATES", "CONTRADICTS",
                      "A_EXCEPTS_B", "B_EXCEPTS_A", "PARTIAL_CONFLICT")

# value relations (internal)
_EQUIVALENT, _OPPOSED, _UNRELATED = "EQUIVALENT", "OPPOSED", "UNRELATED"


def scope_relate(a: dict, b: dict) -> str:
    """Relation of two scope boxes over the closed dimensions. ANY is the
    whole axis; a concrete value is a point. Per-dim: equal, a-broader,
    b-broader, or disjoint; the box relation is the conjunction."""
    a_broader = b_broader = False
    for d in SCOPE_DIMS:
        va, vb = a[d], b[d]
        if va == vb:
            continue
        if va == ANY:
            a_broader = True
        elif vb == ANY:
            b_broader = True
        else:
            return DISJOINT
    if a_broader and b_broader:
        return OVERLAP
    if a_broader:
        return B_WITHIN_A
    if b_broader:
        return A_WITHIN_B
    return EQUAL


def _value_relate(a: Value, b: Value, a_pos: bool, b_pos: bool) -> str:
    """Are two demands on the same key the same demand, opposed demands, or
    incomparable? freeform is incomparable BY DESIGN: it buys honesty (no
    fake edges) at the price of never joining a chain."""
    if a.type == "freeform" or b.type == "freeform":
        return _UNRELATED
    if a.type != b.type:
        return _UNRELATED

    if a.type == "numeric":
        if a.cmp != b.cmp or a.unit != b.unit:
            return _UNRELATED
        same = a.num == b.num
    elif a.type == "enum":
        if a.domain != b.domain:
            return _UNRELATED
        same = a.val == b.val
    elif a.type == "lang":
        same = a.tag == b.tag
    elif a.type == "bool":
        same = a.bool_val == b.bool_val
    elif a.type == "set":
        if a.op != b.op:
            # include-X vs exclude-X on intersecting items is a direct clash
            if set(a.items) & set(b.items):
                return _OPPOSED if a_pos == b_pos else _EQUIVALENT
            return _UNRELATED
        same = set(a.items) == set(b.items)
    elif a.type == "ordering":
        if {a.before, a.after} != {b.before, b.after}:
            return _UNRELATED
        same = (a.before, a.after) == (b.before, b.after)
    else:                                # pragma: no cover
        return _UNRELATED

    if same:
        return _EQUIVALENT if a_pos == b_pos else _OPPOSED
    # different value, same sign: two competing demands on one key
    # ("max 96" vs "max 80") — opposed. Different value AND different sign
    # ("require bullets" vs "prohibit tables") — not comparable.
    return _OPPOSED if a_pos == b_pos else _UNRELATED


def relate(a, b) -> str:
    """a, b: Constraint. The first line is why the key registry must be a
    closed vocabulary — a key typo silently deletes every edge."""
    ca, cb = a.coords, b.coords
    if ca.key != cb.key:
        return INDEPENDENT
    sr = scope_relate(ca.scope, cb.scope)
    if sr == DISJOINT:
        return INDEPENDENT
    vr = _value_relate(ca.value, cb.value,
                       positive(ca.polarity), positive(cb.polarity))
    if vr == _UNRELATED:
        return INDEPENDENT
    if vr == _EQUIVALENT:
        return DUPLICATES
    # opposed demands: who wins depends on the scope geometry
    if sr == EQUAL:
        return CONTRADICTS
    if sr == A_WITHIN_B:
        return A_EXCEPTS_B
    if sr == B_WITHIN_A:
        return B_EXCEPTS_A
    return PARTIAL_CONFLICT
