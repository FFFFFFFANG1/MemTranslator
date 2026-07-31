"""M0 acceptance: the bench's gold state machine is a HOMOMORPHISM of the
product store, verified by fuzz.

The gold side tracks four invalidation reasons (superseded / withdrawn /
merged / auto_retired); the product's `STATUSES` is two-valued. The assertion
therefore projects gold's reasons down to "retired" and compares THERE — a
test demanding identity would either fail forever or force the bench to
abandon the reason taxonomy that SUPPRESS attribution needs.

Two paths matter and both are covered:
- `Store.apply_ops` (new / reinforce / contradict / retire / merge), including
  ops with unknown targets, which both sides must skip, never crash on.
- `Store.bump_strength` crossing AUTO_RETIRE_AT — the second retirement path,
  which has NO op in the log. A gold fold that only reads ops would call these
  entries active and the suite would score zombie carries as correct.
"""
import random

import pytest

from memtranslator.store import AUTO_RETIRE_AT, Store


# ---------------------------------------------------------------------------
# reference gold fold — deliberately tiny and independent of Store internals
# ---------------------------------------------------------------------------

class Gold:
    """id → ("active", strength) | (dead_reason, strength).

    2026-07-31 semantics rev: mirrors the store's heir-liveness invariant.
    Supersede links are version stacks — an heirless, non-withdrawal retire
    of an entry POPS its ancestor back to active; an explicit withdrawal
    (op["withdrawal"]) terminates the chain; a retire with op["heir_id"]
    records succession and never pops."""

    DEAD = ("superseded", "withdrawn", "merged", "auto_retired")

    def __init__(self):
        self.state: dict[str, tuple[str, int]] = {}
        self.parent: dict[str, str] = {}    # entry -> the id it superseded
        self.heir: dict[str, str | None] = {}   # victim -> who replaced it

    def ids(self):
        return list(self.state)

    def apply(self, op: dict) -> None:
        kind = op.get("kind")
        if kind == "new":
            self.state[op["id"]] = ("active", 1)
        elif kind == "reinforce":
            t = self.state.get(op.get("target_id") or "")
            if t:
                self.state[op["target_id"]] = (t[0], t[1] + 1)
        elif kind == "contradict":
            tid = op.get("target_id") or ""
            if tid not in self.state:
                return                      # skipped, like the store
            s, k = self.state[tid]
            if s == "active":
                self.state[tid] = ("superseded", k)
            self.heir[tid] = op["id"]
            self.parent[op["id"]] = tid
            self.state[op["id"]] = ("active", 1)
        elif kind == "retire":
            tid = op.get("target_id") or ""
            if tid not in self.state:
                return
            s, k = self.state[tid]
            if s != "active":
                return
            self.state[tid] = ("withdrawn", k)
            self.heir[tid] = op.get("heir_id")
            if (not op.get("withdrawal") and not op.get("heir_id")
                    and tid in self.parent):
                anc = self.parent[tid]
                if anc in self.state:
                    astate, ak = self.state[anc]
                    if astate != "active" and self.heir.get(anc) == tid:
                        self.state[anc] = ("active", ak)
                        self.heir[anc] = None
        elif kind == "merge":
            tids = op.get("target_ids") or []
            if len(tids) < 2 or any(t not in self.state for t in tids):
                return
            for t in tids:
                s, k = self.state[t]
                if s == "active":
                    self.state[t] = ("merged", k)
                self.heir[t] = op["id"]
            self.parent[op["id"]] = tids[0]
            self.state[op["id"]] = ("active", 1)

    def bump(self, rid: str, delta: int) -> None:
        t = self.state.get(rid)
        if t is None:
            return
        s, k = t
        k += delta
        if k <= AUTO_RETIRE_AT and s == "active":
            s = "auto_retired"
        self.state[rid] = (s, k)

    def projected(self) -> dict[str, str]:
        """The two-valued view the product can express."""
        return {rid: ("active" if s == "active" else "retired")
                for rid, (s, _k) in self.state.items()}


# ---------------------------------------------------------------------------
# fuzz driver
# ---------------------------------------------------------------------------

def _random_op(rng: random.Random, gold: Gold, n: int) -> dict:
    ids = gold.ids()
    # unknown targets are part of the contract: an LLM op batch can point
    # anywhere and neither side may crash or diverge on it
    def target():
        if ids and rng.random() > 0.1:
            return rng.choice(ids)
        return f"req-missing{rng.randrange(999)}"

    roll = rng.random()
    if roll < 0.40 or not ids:
        return {"kind": "new", "text": f"rule {n}"}
    if roll < 0.55:
        return {"kind": "reinforce", "target_id": target()}
    if roll < 0.75:
        return {"kind": "contradict", "target_id": target(),
                "text": f"rule {n} (corrected)"}
    if roll < 0.88:
        op = {"kind": "retire", "target_id": target()}
        # exercise the invariant's three retire flavors: bare (may pop),
        # explicit withdrawal (chain-terminal), conflict-with-heir (no pop)
        flavor = rng.random()
        if flavor < 0.3:
            op["withdrawal"] = True
        elif flavor < 0.5 and ids:
            op["heir_id"] = rng.choice(ids)
        return op
    k = rng.randrange(1, 4)              # includes the degenerate 1-target merge
    return {"kind": "merge",
            "target_ids": [target() for _ in range(k)],
            "text": f"rule {n} (merged)"}


def _drive(seed: int, n_ops: int, tmp_path) -> tuple[Store, Gold]:
    rng = random.Random(seed)
    store = Store(tmp_path / f"fuzz-{seed}.jsonl")
    gold = Gold()
    for n in range(n_ops):
        if gold.ids() and rng.random() < 0.15:
            # strength path, no op in the log
            rid = rng.choice(gold.ids())
            delta = rng.choice((-1, -1, -2, 1))
            store.bump_strength([rid], delta)
            gold.bump(rid, delta)
            continue
        op = _random_op(rng, gold, n)
        before = {r.id for r in store.list()}
        store.apply_ops([op])
        created = [r.id for r in store.list() if r.id not in before]
        # bind the store-generated id back into the gold op so both sides
        # talk about the same entry
        if op["kind"] in ("new", "contradict", "merge"):
            if created:
                gold.apply({**op, "id": created[0]})
            # no created id → the store skipped it; gold skips too, except
            # "new" which the store never skips
            elif op["kind"] == "new":       # pragma: no cover — cannot happen
                raise AssertionError("store dropped a new op")
        else:
            gold.apply(op)
    return store, gold


def _assert_homomorphic(store: Store, gold: Gold, seed: int) -> None:
    got = {r.id: r.status for r in store.list()}
    want = gold.projected()
    assert got == want, (
        f"seed {seed}: store/gold diverged\n"
        f"only-store: { {k: v for k, v in got.items() if want.get(k) != v} }\n"
        f"only-gold:  { {k: v for k, v in want.items() if got.get(k) != v} }")
    # strength must agree too — auto-retire depends on it
    strengths = {r.id: r.strength for r in store.list()}
    for rid, (_s, k) in gold.state.items():
        assert strengths[rid] == k, f"seed {seed}: strength diverged on {rid}"


@pytest.mark.parametrize("seed", range(200))
def test_gold_matches_store_fuzz(seed, tmp_path):
    """200 sequences × 50 ops = 10k operations."""
    store, gold = _drive(seed, 50, tmp_path)
    _assert_homomorphic(store, gold, seed)


def test_auto_retire_is_projected_not_evented(tmp_path):
    """The AUTO_RETIRE_AT path retires with no op in any log — the exact case
    a log-only gold fold would miss."""
    store = Store(tmp_path / "s.jsonl")
    r = store.add("emails under 120 words")
    store.bump_strength([r.id], -1)
    store.bump_strength([r.id], -1)
    store.bump_strength([r.id], -1)      # 1 → 0 → -1 → -2 = AUTO_RETIRE_AT
    assert store.get(r.id).status == "retired"

    gold = Gold()
    gold.apply({"kind": "new", "id": r.id})
    gold.bump(r.id, -1)
    gold.bump(r.id, -1)
    gold.bump(r.id, -1)
    assert gold.state[r.id][0] == "auto_retired"          # reason preserved
    assert gold.projected()[r.id] == "retired"            # projection agrees


def test_reload_preserves_the_homomorphism(tmp_path):
    """Store is append-only JSONL; a reload replays latest-per-id. The
    projection must survive the round trip (from_dict keeps created_at)."""
    store, gold = _drive(seed=7, n_ops=60, tmp_path=tmp_path)
    reloaded = Store(store.path)
    _assert_homomorphic(reloaded, gold, seed=7)
