"""B1 live dry-run: one real positive instance through each adapter.

Usage: source ~/.zshrc && PYTHONPATH=src uv run python scripts/dryrun_b1.py

Prints, per adapter: ingest wall time, retrieved count, whether the GOLD
preference text appears in the injected block (recall hit), and the block
itself. This is a wiring check, not an experiment (that's B2/B3).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from pilot.baselines import ADAPTERS
from pilot.config import DATA_INSTANCES, RUNS

WORK = RUNS / "dryrun_b1"


def main() -> None:
    inst = json.loads((DATA_INSTANCES / "positives.jsonl").read_text().splitlines()[0])
    print(f"instance {inst['iid']}")
    print(f"query: {inst['query']}")
    print(f"gold:  {inst['gold_preference']}\n")

    which = sys.argv[1:] or list(ADAPTERS)
    for name in which:
        cls = ADAPTERS[name]
        workdir = WORK / name
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)
        adapter = cls(workdir) if name != "topk_inject" else cls()
        r = adapter.ingest_and_inject(inst["memory_store"], inst["query"])
        # Loose recall check: systems rephrase (mem0 stores third person), so
        # count a hit when >=2 distinctive gold words survive in the block.
        gold_words = [w.strip(".,").lower() for w in inst["gold_preference"].split()
                      if len(w) > 6]
        hits = sum(1 for w in gold_words if w in r.text.lower())
        gold_hit = hits >= min(2, len(gold_words))
        print(f"== {name}: ingest {adapter.ingest_wall_s:.1f}s, "
              f"retrieved {r.n_retrieved}, inject {r.wall_s:.2f}s, gold_hit={gold_hit}")
        for line in (r.text or "(empty injection)").splitlines():
            print("   ", line[:120])
        if hasattr(adapter, "close"):
            adapter.close()
        print()


if __name__ == "__main__":
    main()
