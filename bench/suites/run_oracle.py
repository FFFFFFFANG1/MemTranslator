"""Stable E1 oracle protocol: perfect per-probe memory, real Translator.

Oracle answers one question only: if memory is completely correct for the
current task, can Translator carry it into the request?  Each probe receives
exactly its gold ``should_apply`` items, including their audited Extractor
attributes. The run never executes the write path and never supplies the full
gold store, query-side labels, or pending conversation messages.

    python -m bench.suites.run_oracle --workers 12
    python -m bench.suites.run_oracle --model ark:glm-5.2 --save-trace
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from memtranslator import config

from bench.suites.config import (CASES, JUDGE_MODEL, METRIC_VERSION,
                                 RESULTS)
from bench.suites.report import hash_cases
from bench.suites.run_episodes import (ORACLE_PROTOCOL_VERSION,
                                       _owner_metrics, score_probe)

ORACLE_ARM = "oracle"
ORACLE_PROTOCOL = {
    "version": ORACLE_PROTOCOL_VERSION,
    "question": (
        "If memory is completely correct for this task, can Translator "
        "carry it into the request?"
    ),
    "memory": (
        "exactly turn.probe.should_apply golden items with authored "
        "attributes"),
    "round_attributes_visible_to_translator": False,
    "query_context": False,
    "catalogue_metadata_on_memory": True,
    "full_gold_store": False,
    "pending_raw_messages": False,
    "conversation_history": False,
    "gold_metadata_origin": "glm-5.3 draft, live-parser validated, audited",
    "llm_generated_gold_metadata": True,
    "write_path": False,
}


def _load_episodes(spec: str = "") -> list[dict]:
    if spec.strip():
        ids = [value.strip() for value in spec.split(",") if value.strip()]
    else:
        ids = [f"e-{number:02d}" for number in range(1, 13)]
    return [json.loads((CASES / "episodes" / f"{epid}.json").read_text())
            for epid in ids]


def _score_round(ep: dict, round_: dict) -> dict:
    """One independent oracle probe; no chain-derived state is admissible."""
    row = {
        "round": round_,
        "transcript": [],
        "pending_raw": [],
        "chained_polished": None,
        "store_state": [],
    }
    by_cid = {
        node["id"]: node
        for node in ep["ground_truth"]["requirements"]}
    scored = score_probe(ep, row, ORACLE_ARM, by_cid)
    scored["episode"] = ep["id"]
    return scored


def run_oracle(episodes: list[dict], *, workers: int = 12,
               save_trace: bool = False) -> dict:
    jobs = [(ep, round_) for ep in episodes for round_ in ep["user_turns"]
            if round_.get("probe")]
    rows_by_episode = {ep["id"]: [] for ep in episodes}
    started = time.time()
    done = 0
    print(f"oracle-v{ORACLE_PROTOCOL_VERSION}: {len(jobs)} probes, "
          f"model={config.MODELS['translator']}, workers={workers}",
          flush=True)

    if workers <= 1:
        scored_rows = (_score_round(*job) for job in jobs)
        for scored in scored_rows:
            rows_by_episode[scored["episode"]].append(scored)
            done += 1
    else:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(_score_round, *job) for job in jobs]
            for future in as_completed(futures):
                scored = future.result()
                rows_by_episode[scored["episode"]].append(scored)
                done += 1
                if done % 20 == 0 or done == len(jobs):
                    print(f"  {done}/{len(jobs)}  "
                          f"{time.time() - started:.0f}s", flush=True)

    episode_results = []
    all_rows = []
    for ep in episodes:
        rows = sorted(rows_by_episode[ep["id"]], key=lambda row: row["seq"])
        all_rows.extend(rows)
        owner = _owner_metrics(rows, ORACLE_ARM)
        accuracy = (owner["memory_hit"] / owner["memory_n"]
                    if owner["memory_n"] else None)
        per_task = (owner["tasks_perfect"] / owner["tasks_n"]
                    if owner["tasks_n"] else None)
        result = {
            "id": ep["id"],
            "category": "episode",
            "episode": ep["id"],
            "owner_metrics": owner,
            "accuracy": accuracy,
            "per_task": per_task,
        }
        if save_trace:
            result["probe_trace"] = rows
        episode_results.append(result)
        accuracy_text = "n/a" if accuracy is None else f"{accuracy:.2f}"
        task_text = "n/a" if per_task is None else f"{per_task:.2f}"
        print(f"{ep['id']}  memory {owner['memory_hit']}/"
              f"{owner['memory_n']}={accuracy_text}  task "
              f"{owner['tasks_perfect']}/{owner['tasks_n']}={task_text}")

    memory_hit = sum(result["owner_metrics"]["memory_hit"]
                     for result in episode_results)
    memory_n = sum(result["owner_metrics"]["memory_n"]
                   for result in episode_results)
    tasks_perfect = sum(result["owner_metrics"]["tasks_perfect"]
                        for result in episode_results)
    tasks_n = sum(result["owner_metrics"]["tasks_n"]
                  for result in episode_results)
    reasons = Counter(
        row["translator"].get("reason")
        or row["translator"].get("decision") or "unknown"
        for row in all_rows)
    judge_parse_flags = sum(
        bool(detail.get("judge_parse_flag"))
        for row in all_rows for detail in row["carry_detail"])
    pooled = {
        "accuracy": memory_hit / memory_n if memory_n else None,
        "memory_hit": memory_hit,
        "memory_n": memory_n,
        "per_task": tasks_perfect / tasks_n if tasks_n else None,
        "tasks_perfect": tasks_perfect,
        "tasks_n": tasks_n,
    }
    return {
        "suite": "E1-oracle",
        "metric_version": METRIC_VERSION,
        "oracle_protocol": dict(ORACLE_PROTOCOL),
        "model": config.MODELS["translator"],
        "judge_model": JUDGE_MODEL,
        "cases_file": str(CASES / "episodes"),
        "cases_hash": hash_cases(str(CASES / "episodes")),
        "expected_probes": len(jobs),
        "completed_probes": len(all_rows),
        "complete": len(all_rows) == len(jobs),
        "seconds": round(time.time() - started, 1),
        "save_trace": save_trace,
        "pooled": pooled,
        "score": pooled["accuracy"],
        "translate_reasons": dict(reasons),
        "judge_parse_flags": judge_parse_flags,
        "results": episode_results,
    }


def write_oracle_snapshot(result: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    payload = {"at": stamp, **result}
    model_slug = re.sub(r"[^a-z0-9]+", "-", str(
        result.get("model") or "default").lower()).strip("-")
    path = RESULTS / f"E1-oracle-{model_slug}-{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=ORACLE_PROTOCOL["question"])
    parser.add_argument("--episodes", default="",
                        help="comma-separated episode ids; default e-01..e-12")
    parser.add_argument("--model", default="",
                        help="Translator model; default project configuration")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--save-trace", action=argparse.BooleanOptionalAction,
                        default=False)
    args = parser.parse_args(argv)
    if args.model.strip():
        config.MODELS["translator"] = args.model.strip()
    result = run_oracle(_load_episodes(args.episodes),
                        workers=max(1, args.workers),
                        save_trace=args.save_trace)
    pooled = result["pooled"]
    print(f"POOLED memory {pooled['memory_hit']}/{pooled['memory_n']}="
          f"{pooled['accuracy']:.3f}  task {pooled['tasks_perfect']}/"
          f"{pooled['tasks_n']}={pooled['per_task']:.3f}")
    print(f"translate reasons {result['translate_reasons']}")
    print(f"snapshot: {write_oracle_snapshot(result)}")


if __name__ == "__main__":
    main()
