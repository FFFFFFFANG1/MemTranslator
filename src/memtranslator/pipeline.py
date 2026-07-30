"""Write-path triggers + op executor (design §5).

Holds the candidate queues and decides WHEN the extraction call fires:
at BATCH_N queued candidates, or FLUSH_IDLE_S after the oldest one — never
per message. Callers pass `now` explicitly so daemons and tests share the
same code path (and so the bench adapter can drive it without wall clocks).
"""
from memtranslator.config import BATCH_N, FLUSH_IDLE_S
from memtranslator.extraction import run_extraction
from memtranslator.kinds import backfill_kinds
from memtranslator.store import Store


class Pipeline:
    def __init__(self, store: Store):
        self.store = store
        self._a: list[str] = []          # route-A spans
        self._b: list[dict] = []         # route-B diff triples (+ survival)
        self._oldest_at: float | None = None
        self.adds_since_consolidate = 0  # M3 reads this

    def pending_count(self) -> int:
        return len(self._a) + len(self._b)

    def _note(self, now: float) -> None:
        if self._oldest_at is None:
            self._oldest_at = now

    def add_natural(self, spans: list[str], now: float) -> None:
        for s in spans:
            self._a.append(s)
            self._note(now)

    def add_diff(self, triple: dict, now: float) -> None:
        self._b.append(triple)
        self._note(now)

    def maybe_flush(self, now: float, force: bool = False) -> dict | None:
        if self.pending_count() == 0:
            return None
        due = (self.pending_count() >= BATCH_N
               or (self._oldest_at is not None
                   and now - self._oldest_at >= FLUSH_IDLE_S))
        if not (due or force):
            return None
        out = run_extraction(self._a, self._b, self.store.active())
        self._a, self._b, self._oldest_at = [], [], None
        applied = self.store.apply_ops(out["ops"])
        self.adds_since_consolidate += sum(
            1 for o in out["ops"] if o["kind"] in ("new", "contradict"))
        backfill_kinds(self.store)
        return {"ops": out["ops"], "flags": out["flags"], "store": applied}
