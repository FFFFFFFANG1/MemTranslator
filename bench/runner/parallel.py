"""Run bench items concurrently, checkpointing each result as it lands.

Two problems this solves, both learned the hard way on 2026-07-27:

1. **Serial runs waste wall clock.** Every case spends almost all its time
   waiting on a network round trip, so the suites were running at a few
   percent utilisation. Cases are independent — the only reason to serialise
   was rate-limit politeness, which belongs in the backoff, not in the shape
   of the loop.
2. **An interrupted run lost everything.** The snapshot was written after the
   loop, so killing a run at 53/60 discarded all 53. Results are now appended
   to a checkpoint file as each one completes, and a re-run skips whatever is
   already there — a killed or rate-limited run resumes instead of restarting.

Concurrency is deliberately modest. The judge channel returned 429 at serial
pace, so the goal here is to use the idle time between round trips, not to
push a higher request rate than one suite already did.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from bench.runner.config import RESULTS
from bench.runner.retry import with_retry

DEFAULT_WORKERS = int(os.environ.get("BENCH_WORKERS", "4"))


class Checkpoint:
    """Append-only per-item results, keyed by item id."""

    def __init__(self, suite: str):
        RESULTS.mkdir(parents=True, exist_ok=True)
        self.path = RESULTS / f".{suite}.checkpoint.jsonl"
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
              resume: bool = True) -> list[dict]:
    """Map `run_one` over `items` concurrently, in checkpointed order.

    `items` must expose `.id`. Results come back in the input order regardless
    of completion order, so a snapshot never depends on scheduling.
    """
    ckpt = Checkpoint(suite)
    if not resume:
        ckpt.clear()
        ckpt.done = {}
    todo = [it for it in items if it.id not in ckpt.done]
    if ckpt.done:
        print(f"resuming: {len(ckpt.done)} already done, {len(todo)} to go",
              flush=True)

    total, counter = len(items), [len(ckpt.done)]
    progress_lock = Lock()

    def one(item):
        result = with_retry(lambda: run_one(item), item.id)
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
