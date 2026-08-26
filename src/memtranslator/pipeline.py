"""Write-path triggers + op executor (design §5).

Holds the candidate queues and decides WHEN each extraction call fires:
at its channel's batch size, or FLUSH_IDLE_S after that channel's oldest
candidate — never per message. Callers pass `now` explicitly so daemons and
tests share the same code path (and so the bench adapter can drive it
without wall clocks).

The two channels are independent all the way down: separate queues, clocks,
thresholds, prompts, parsers and store executors. Route A turns statements
into store ops; route B judges the entries a patch actually used and edits
those entries in place. Only the low-frequency consolidation pass sees the
results of both.
"""
from memtranslator.config import A_BATCH_N, B_BATCH_N, FLUSH_IDLE_S
from memtranslator.extraction import run_a_extraction, run_b_extraction
from memtranslator.store import Store


class Pipeline:
    def __init__(self, store: Store):
        self.store = store
        self._a: list[str] = []          # route-A spans
        self._b: list[dict] = []         # route-B {entries, diff} signals
        self._a_oldest_at: float | None = None
        self._b_oldest_at: float | None = None
        self.adds_since_consolidate = 0  # M3 reads this

    def pending_count(self, channel: str | None = None) -> int:
        if channel == "a":
            return len(self._a)
        if channel == "b":
            return len(self._b)
        return len(self._a) + len(self._b)

    def add_natural(self, messages: list[str], now: float) -> int:
        """Queue non-empty raw messages for Route A.

        Source eligibility is enforced by the server before background
        capture reaches this method.  There is intentionally no lexical or
        rule-based filter here.  The extraction prompt applies the sole
        content guardrail: a deterministic per-message length truncation.
        """
        added = 0
        for s in messages:
            if not s.strip():
                continue
            self._a.append(s)
            added += 1
            if self._a_oldest_at is None:
                self._a_oldest_at = now
        return added

    def add_feedback(self, entries: list[dict], diff: list[dict],
                     now: float) -> bool:
        """Queue a route-B signal only when it can be judged: attributed
        entries AND a real diff. An untouched patch produces no diff hunks,
        so an accepted rewrite costs nothing — it never reaches a call."""
        entries = [e for e in entries if e.get("id") and e.get("text")]
        if not entries or not diff:
            return False
        self._b.append({"entries": entries, "diff": diff})
        if self._b_oldest_at is None:
            self._b_oldest_at = now
        return True

    @staticmethod
    def _due(size: int, threshold: int, oldest_at: float | None,
             now: float, force: bool) -> bool:
        return bool(size) and (force or size >= threshold
                               or (oldest_at is not None
                                   and now - oldest_at >= FLUSH_IDLE_S))

    def maybe_flush(self, now: float, force: bool = False) -> dict | None:
        due_a = self._due(len(self._a), A_BATCH_N, self._a_oldest_at,
                          now, force)
        due_b = self._due(len(self._b), B_BATCH_N, self._b_oldest_at,
                          now, force)
        if not (due_a or due_b):
            return None

        result = {"a": None, "b": None, "ops": [], "flags": [],
                  "store": {"applied": 0, "skipped": [], "retired": 0}}
        if due_a:
            out = run_a_extraction(self._a, self.store.active())
            self._a, self._a_oldest_at = [], None
            applied = self.store.apply_ops(out["ops"])
            self.adds_since_consolidate += sum(
                1 for o in out["ops"] if o["kind"] in ("new", "contradict"))
            result["a"] = {**out, "store": applied}
            result["ops"] += out["ops"]
            result["flags"] += out["flags"]
            result["store"]["applied"] += applied["applied"]
            result["store"]["skipped"] += applied["skipped"]

        if due_b:
            out = run_b_extraction(self._b)
            self._b, self._b_oldest_at = [], None
            applied = self.store.apply_feedback_ops(out["ops"])
            result["b"] = {**out, "store": applied}
            result["ops"] += out["ops"]
            result["flags"] += out["flags"]
            result["store"]["applied"] += applied["applied"]
            result["store"]["skipped"] += applied["skipped"]
            result["store"]["retired"] += applied["retired"]
        return result
