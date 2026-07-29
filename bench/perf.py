"""Performance suite: the archive's realistic user turns, replayed through
the REAL write path, probing the read path at growing store sizes.

What "performance" means here, measured per store size {4, 8, 16, 24, 32}:
- canary carry: one marked rule (78-word email cap) is planted first; an
  email probe at every size checks mechanically whether it still gets woven.
  This is the dilution curve on stores the product BUILT ITSELF, not on
  synthetic layouts.
- noop rate over a fixed probe battery (the episode's own R-round tasks —
  real user voices from the archive corpus).
- latency and injected-block size (prompt cost) per translate call.

No answer key is claimed: quality-vs-gold lives in the robustness suite;
this suite measures how behavior and cost MOVE as memory accumulates.

    uv run python -m bench.perf --episodes e-01,e-05 --sizes 4,8,16,24,32
"""
import argparse
import json
import time
import uuid
from pathlib import Path

from memtranslator.store import Store
from memtranslator.translate import translate

from bench_archive.runner.config import RUN_DIR
from bench_archive.runner.providers import V1Provider
from bench_archive.runner.retry import with_retry

ARCHIVE = Path(__file__).resolve().parents[1] / "bench_archive"
BENCH = Path(__file__).resolve().parent

CANARY = "我让你写的邮件一律不超过78词"
CANARY_PROBE = "帮我写封邮件给供应商，催一下上个月的发票"
CANARY_ANCHOR = "78"


def replay_episode(epid: str, sizes: list[int], flush_every: int = 4) -> dict:
    ep = json.loads((ARCHIVE / "cases" / "episodes" / f"{epid}.json")
                    .read_text())
    probes = [r["text"] for r in ep["rounds"]
              if r.get("probe")][:4]                    # fixed battery
    d = RUN_DIR / "perf-stores"
    d.mkdir(parents=True, exist_ok=True)
    store = Store(d / f"{epid}-{uuid.uuid4().hex[:8]}.jsonl")
    store.add(CANARY, source="manual")                  # planted first = oldest
    provider = V1Provider()

    pending, rows, taken = [], [], set()
    for r in ep["rounds"]:
        pending.append({"type": "natural", "text": r["text"]})
        if len(pending) >= flush_every:
            ops = with_retry(lambda: provider.extract(pending,
                                                      store.active()),
                             f"perf/{epid}/extract")
            store.apply_ops(ops)
            pending = []
            n = len(store.active())
            due = [s for s in sizes if s <= n and s not in taken]
            if due:
                taken.update(due)
                rows.append(probe_at(store, max(due), probes, epid))
        if taken >= set(sizes):
            break
    # final snapshot if the store never reached the larger sizes
    n = len(store.active())
    if not rows or rows[-1]["size"] != n:
        rows.append(probe_at(store, n, probes, epid))
    return {"episode": epid, "rows": rows,
            "final_active": len(store.active()),
            "final_retired": sum(1 for x in store.list()
                                 if x.status == "retired")}


def canary_state(store: Store) -> dict:
    """The canary doubles as a spurious-retirement detector. If it is dead,
    record who superseded it — a successor on a DIFFERENT facet (no email
    vocabulary) means the write path aimed a contradict at the wrong target,
    which the first run caught twice (a postmortem word-cap killing an email
    word-cap)."""
    for r in store.list():
        if CANARY_ANCHOR in r.text and "邮件" in r.text:
            if r.status == "active":
                return {"alive": True}
            heirs = [h for h in store.list() if h.supersedes == r.id]
            legit = any("邮件" in h.text or "email" in h.text.lower()
                        for h in heirs)
            return {"alive": False, "legit_supersession": legit,
                    "successor": heirs[0].text[:60] if heirs else None}
    return {"alive": False, "legit_supersession": False,
            "successor": "(gone entirely)"}


def probe_at(store: Store, size: int, probes: list[str], epid: str) -> dict:
    outs = []
    for task in [CANARY_PROBE] + probes:
        t0 = time.time()
        out = with_retry(lambda: translate(task, store.active()),
                         f"perf/{epid}/probe")
        outs.append({"task": task, "decision": out["decision"],
                     "polished": out["polished"],
                     "ms": int((time.time() - t0) * 1000)})
    canary = outs[0]
    carried = bool(canary["polished"]) and CANARY_ANCHOR in canary["polished"]
    block_chars = sum(len(x.text) for x in store.active())
    return {"size": size,
            "canary": canary_state(store),
            "canary_carried": carried,
            "noop_rate": sum(1 for o in outs[1:]
                             if o["decision"] == "noop") / max(1, len(outs) - 1),
            "mean_ms": sum(o["ms"] for o in outs) // len(outs),
            "block_chars": block_chars}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="e-01,e-03,e-05,e-09")
    ap.add_argument("--sizes", default="4,8,16,24,32")
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]
    eps = [e.strip() for e in args.episodes.split(",")]

    results = [replay_episode(e, sizes) for e in eps]

    print(f"\n{'size':>5} {'carry@alive':>12} {'':>7} {'noop%':>6} {'ms':>6} {'chars':>7}")
    by_size: dict[int, list] = {}
    for r in results:
        for row in r["rows"]:
            by_size.setdefault(row["size"], []).append(row)
    for s in sorted(by_size):
        rows = by_size[s]
        alive = [x for x in rows if x.get("canary", {}).get("alive", True)]
        carried = sum(1 for x in alive if x["canary_carried"])
        spurious = sum(1 for x in rows
                       if not x.get("canary", {}).get("alive", True)
                       and not x["canary"].get("legit_supersession"))
        print(f"{s:>5} {carried}/{len(alive):>2}@alive "
              f"{'spur:' + str(spurious) if spurious else '      '} "
              f"{100 * sum(x['noop_rate'] for x in rows) / len(rows):>5.0f} "
              f"{sum(x['mean_ms'] for x in rows) // len(rows):>6} "
              f"{sum(x['block_chars'] for x in rows) // len(rows):>7}")
    out = BENCH / "perf_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
