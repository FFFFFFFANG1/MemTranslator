"""Orchestrates the pilot (plan Task 8): per instance -> translate once ->
arms x 2 downstream tiers -> judges -> append one JSON line. Resumable by id;
heartbeat per instance (run under nohup for the full run).

Baseline arms (B1_mem0/B2_graphiti) are opt-in via --with-baselines: their
ingest+retrieval runs once per (arm, instance) and is cached as an
InjectResult JSON under runs/baseline_cache/, so re-runs and multi-tier use
are free (mem0 ~64s, graphiti ~156s per instance otherwise — see B0 memo)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pilot import llm
from pilot.arms import build_downstream_call
from pilot.config import ARMS, BASELINE_ARMS, DOWNSTREAM_TIERS, INSTANCES, MODELS, RESULTS, RUNS
from pilot.judge import judge_adherence, judge_far, judge_preservation
from pilot.translator import translate

BASELINE_CACHE = RUNS / "baseline_cache"


def load_instances(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def baseline_inject(arm: str, inst: dict) -> dict:
    """Cached {text, n_retrieved, wall_s, ingest_wall_s} for a baseline arm."""
    name = {"B1_mem0": "mem0", "B2_graphiti": "graphiti"}[arm]
    cache = BASELINE_CACHE / name / f"{inst['id']}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    from pilot.baselines import ADAPTERS

    workdir = BASELINE_CACHE / name / f"{inst['id']}.work"
    adapter = ADAPTERS[name](workdir)
    r = adapter.ingest_and_inject(inst["memory_store"], inst["request"])
    out = {"text": r.text, "n_retrieved": r.n_retrieved,
           "wall_s": r.wall_s, "ingest_wall_s": adapter.ingest_wall_s}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False))
    if hasattr(adapter, "close"):
        adapter.close()
    return out


def process_one(inst: dict, arms: list[str]) -> dict:
    row = {"id": inst["id"], "kind": inst["kind"], "topic": inst["topic"]}
    tr = translate(inst)
    row["translator"] = {k: v for k, v in tr.items() if k != "polished_request"}
    row["polished_request"] = tr["polished_request"]

    if inst["kind"] == "positive":
        row["preservation"] = judge_preservation(
            inst["memory_store"], inst["request"], tr["polished_request"])

    injected: dict[str, dict] = {}
    for arm in arms:
        if arm in BASELINE_ARMS:
            injected[arm] = baseline_inject(arm, inst)
    row["baseline_inject"] = {a: {k: v for k, v in d.items() if k != "text"}
                              for a, d in injected.items()}

    row["arms"] = {}
    for tier in DOWNSTREAM_TIERS:
        model = MODELS[tier]
        for arm in arms:
            polished = tr["polished_request"] if arm == "A3_translator" else None
            block = injected[arm]["text"] if arm in injected else None
            system, user = build_downstream_call(arm, inst, polished, block)
            resp = llm.call(model, user, system=system, max_tokens=1024)
            cell = {"input_tokens": resp["input_tokens"],
                    "output_tokens": resp["output_tokens"]}
            if inst["kind"] == "positive":
                cell["adherence"] = judge_adherence(
                    inst["preference"], inst["request"], resp["text"])
            else:
                cell["far"] = judge_far(
                    inst["memory_store"], inst["request"], resp["text"])
            row["arms"][f"{tier}/{arm}"] = cell
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="pilot")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--instances", default=str(INSTANCES / "pilot.jsonl"))
    ap.add_argument("--with-baselines", action="store_true",
                    help="also run B1_mem0/B2_graphiti (slow ingest; cached)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print planned call counts and exit")
    args = ap.parse_args()

    arms = ARMS + (BASELINE_ARMS if args.with_baselines else [])
    instances = load_instances(Path(args.instances))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / f"{args.run_id}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.open()}
    todo = [i for i in instances if i["id"] not in done]
    if args.limit:
        todo = todo[:args.limit]

    n_down = len(todo) * len(arms) * len(DOWNSTREAM_TIERS)
    print(f"{len(todo)} instances to run ({len(done)} already done); "
          f"arms={arms}; ~{len(todo)} translator + {n_down} downstream + "
          f"~{n_down} judge calls", flush=True)
    if args.dry_run:
        return

    t0 = time.time()
    with out_path.open("a") as f:
        for n, inst in enumerate(todo, 1):
            row = process_one(inst, arms)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            el = time.time() - t0
            eta = el / n * (len(todo) - n) / 60
            print(f"[{n}/{len(todo)}] {inst['id']} ({el/n:.0f}s/inst, "
                  f"ETA {eta:.0f}min)", flush=True)
    print(f"done -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
