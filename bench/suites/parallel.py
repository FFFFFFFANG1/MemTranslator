"""Run bench items concurrently, checkpointing each result as it lands.

Two problems this solves, both learned the hard way on 2026-07-27:

1. **Serial runs waste wall clock.** Every case spends almost all its time
   waiting on a network round trip, so the suites were running at a few
   percent utilisation. Cases are independent — the only reason to serialise
   was rate-limit politeness, which lives in ratelimit.py now, not in the
   shape of the loop.
2. **An interrupted run lost everything.** The snapshot was written after the
   loop, so killing a run at 53/60 discarded all 53. Results are now appended
   to a checkpoint file as each one completes, and a re-run skips whatever is
   already there — a killed or rate-limited run resumes instead of restarting.

Three M0 changes:

- **No item-level retry.** Retries sit on the individual LLM calls (judge.py,
  and the runners wrap their SUT calls); re-running a whole multi-call item
  because one call flapped multiplied cost and wall clock. An exception that
  reaches this level is one the call-level retry already gave up on.
- **Checkpoints key on a run_key.** The old file keyed on item.id alone, so
  editing a case and re-running silently mixed results from two versions of
  the case file. Runners pass the cases hash; a changed file never resumes a
  stale checkpoint. Checkpoints live under config.RUN_DIR (outside the repo).
- **LPT ordering.** With a `weight` function, heavy items are submitted first
  (longest processing time): a handful of shards run 8-20x longer than the
  rest, and submitting them last leaves the tail of the run on one worker.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from bench.suites.config import RUN_DIR

DEFAULT_WORKERS = int(os.environ.get("BENCH_WORKERS", "4"))


class Checkpoint:
    """Append-only per-item results, keyed by item id, scoped by run_key."""

    def __init__(self, suite: str, run_key: str = ""):
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{suite}-{run_key}" if run_key else suite
        self.path = RUN_DIR / f"{name}.checkpoint.jsonl"
        self._lock = Lock()
        self.done: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.done[r["id"]] = r

    def record(self, result: dict) -> None:
        with self._lock:
            self.done[result["id"]] = result
            with self.path.open("a") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def run_items(suite: str, items, run_one, *, workers: int = DEFAULT_WORKERS,
              resume: bool = True, run_key: str = "",
              weight=None) -> list[dict]:
    """Map `run_one` over `items` concurrently, in checkpointed order.

    `items` must expose `.id`. Results come back in the input order regardless
    of completion order, so a snapshot never depends on scheduling.
    """
    ckpt = Checkpoint(suite, run_key)
    if not resume:
        ckpt.clear()
        ckpt.done = {}
    todo = [it for it in items if it.id not in ckpt.done]
    if weight is not None:
        todo.sort(key=weight, reverse=True)
    if ckpt.done:
        print(f"resuming: {len(ckpt.done)} already done, {len(todo)} to go",
              flush=True)

    total, counter = len(items), [len(ckpt.done)]
    progress_lock = Lock()

    def one(item):
        result = run_one(item)
        ckpt.record(result)
        with progress_lock:
            counter[0] += 1
            verdict = ("PASS" if result.get("pass") else "FAIL")
            print(f"[{counter[0]}/{total}] {item.id} {verdict}", flush=True)
        return result

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, todo))

    ordered = [ckpt.done[it.id] for it in items if it.id in ckpt.done]
    if len(ordered) == total:
        ckpt.clear()          # a complete run leaves no resume state behind
    return ordered
