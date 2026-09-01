"""Replay E1's read path against frozen Store states.

Unlike a second chained-real run, this isolates the retrieval/Translator
variable: every probe sees the exact Store state from the source snapshot;
only ``SCOPED_RECALL_CAP`` changes.  It intentionally
does not call the carry/STATE judge.  Each episode is checkpointed separately.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import memtranslator.recall as recall_mod
from memtranslator import translate as tr_mod
from memtranslator.schema import Requirement

from bench.suites.config import RESULTS
from bench.suites.retry import with_retry


def _replay_one(path: Path, cap: int) -> Path:
    source = json.loads(path.read_text())
    source_result = source["results"][0]
    episode = source_result["episode"]
    rows = []
    for row in source_result["probe_trace"]["chained"]:
        requirements = [Requirement.from_dict(item)
                        for item in row["store_state"]
                        if item.get("status") == "active"]
        request = row["round"]["user_input"]
        out = with_retry(
            lambda: tr_mod.translate(request, requirements),
            f"read-cap{cap}/{episode}/seq{row['round']['seq']}")
        rows.append({"round": row["round"],
                     "store_state": row["store_state"],
                     "chained_out": out})

    stamp = time.strftime("%Y%m%d-%H%M%S")
    payload = {
        "suite": f"E1-read-cap{cap}-{episode}",
        "at": stamp,
        "scoped_recall_cap": cap,
        "replay_protocol": "fixed-store-read-ablation-v1",
        "source_snapshot": str(path),
        "results": [{
            "id": episode,
            "episode": episode,
            "probe_trace": {"chained": rows, "scores": []},
        }],
    }
    output = RESULTS / f"E1-read-cap{cap}-{episode}-{stamp}.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"{episode}: {len(rows)} probes -> {output}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--scoped-cap", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.scoped_cap <= 0:
        parser.error("--scoped-cap must be positive")
    recall_mod.SCOPED_RECALL_CAP = args.scoped_cap

    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_replay_one, path, args.scoped_cap): path
                   for path in args.snapshots}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # retain every completed episode
                failures.append((futures[future], exc))
                print(f"FAILED {futures[future]}: {exc}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
