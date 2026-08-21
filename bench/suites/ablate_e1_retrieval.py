"""Offline E1 retrieval ablation over frozen probe-time Store states.

No LLM is called.  The experiment compares the production text-first recall
with attribute-first candidate pools followed by body-text BM25+dense recall.
Golden rules are used only for scoring, never as query-side attributes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import memtranslator.recall as recall_mod
from memtranslator.config import TRANSLATOR_MESSAGE_MAX_TOKENS
from memtranslator.recall import (_is_global, recall,
                                  select_within_token_budget)
from memtranslator.retrieval import (default_embedding_ranker,
                                     flatten_applicability_fields,
                                     quota_interleave_order,
                                     rerank_by_best_rank, sparse_order)
from memtranslator.schema import Requirement
from memtranslator.signals import compact_message

from bench.suites.analyze_e1_translator import (
    _align_requirement, _episode, _evidence_sources_by_id, _introduced_by)


ATTRIBUTE_CONFIGS = (
    (24, 8),
    (32, 16),
    (24, 16),
    (32, 8),
)


def _active_requirements(requirements: list[Requirement]) -> list[Requirement]:
    pool = [requirement for requirement in requirements
            if requirement.status == "active"
            and requirement.kind == "requirement"]
    pool.sort(key=lambda requirement: requirement.created_at)
    return pool


def _selected_globals(pool: list[Requirement]) -> list[Requirement]:
    global_pool = [requirement for requirement in pool
                   if _is_global(requirement)]
    global_pool.sort(key=lambda requirement: (
        -requirement.strength, -requirement.updated_at,
        -requirement.created_at))
    selected = select_within_token_budget(
        global_pool, recall_mod.GLOBAL_RECALL_MAX_TOKENS)
    selected.sort(key=lambda requirement: requirement.created_at)
    return selected


def attribute_then_text_candidates(
        requirements: list[Requirement], query: str, *,
        attribute_pool_cap: int, final_cap: int, embedding_ranker
        ) -> tuple[list[Requirement], list[Requirement]]:
    """Return the attribute pool and final prompt candidates.

    Applicability embedding determines membership in a deliberately wider
    pool.  Body BM25+dense then chooses the final scoped seats.  Globals use
    the unchanged always-on token budget and appear in both returned lists.
    """
    active = _active_requirements(requirements)
    selected_global = _selected_globals(active)
    global_ids = {requirement.id for requirement in selected_global}
    scoped = [requirement for requirement in active
              if requirement.id not in global_ids
              and not _is_global(requirement)]
    if not scoped:
        return selected_global, selected_global
    if embedding_ranker is None:
        raise RuntimeError("local embedding ranker is required")

    applicability_docs = [
        flatten_applicability_fields(
            work_kinds=requirement.kinds,
            applies_when=requirement.applies_when,
            scope=requirement.scope)
        for requirement in scoped]
    attribute_order = embedding_ranker.rank(query, applicability_docs)
    attribute_order = [
        index for index in attribute_order
        if isinstance(index, int) and 0 <= index < len(scoped)]
    fallback = sorted(
        range(len(scoped)),
        key=lambda index: (-scoped[index].strength,
                           -scoped[index].updated_at,
                           -scoped[index].created_at))
    attribute_order = list(dict.fromkeys(attribute_order + fallback))
    attribute_pool = [scoped[index]
                      for index in attribute_order[:attribute_pool_cap]]

    if len(attribute_pool) <= final_cap:
        selected_scoped = attribute_pool
    else:
        body_docs = [requirement.text for requirement in attribute_pool]
        sparse = sparse_order(query, body_docs, positive_only=True)
        dense = embedding_ranker.rank(query, body_docs)
        dense = [index for index in dense
                 if isinstance(index, int)
                 and 0 <= index < len(attribute_pool)]
        half = final_cap // 2
        order = quota_interleave_order(
            sparse, dense, cap=final_cap,
            sparse_quota=half, dense_quota=final_cap - half)
        for index in dense + sparse + list(range(len(attribute_pool))):
            if index not in order:
                order.append(index)
            if len(order) == final_cap:
                break
        order = rerank_by_best_rank(order, sparse, dense)
        selected_scoped = [attribute_pool[index]
                           for index in order[:final_cap]]
    return (selected_global + attribute_pool,
            selected_global + selected_scoped)


def _production_candidates(requirements: list[Requirement], query: str,
                           cap: int) -> list[Requirement]:
    previous = recall_mod.SCOPED_RECALL_CAP
    try:
        recall_mod.SCOPED_RECALL_CAP = cap
        return recall(requirements, query=query, context=None)
    finally:
        recall_mod.SCOPED_RECALL_CAP = previous


def _metric_row(counter: Counter) -> dict:
    total = counter["total"]
    available = counter["available"]
    return {
        "should_pairs": total,
        "store_available": available,
        "attribute_pool_hits": counter["pool_hit"],
        "final_hits": counter["final_hit"],
        "recall_all": counter["final_hit"] / total if total else 1.0,
        "recall_available": (
            counter["final_hit"] / available if available else 1.0),
        "pool_recall_available": (
            counter["pool_hit"] / available if available else 1.0),
    }


def ablate(paths: list[Path], embedding_ranker=None) -> dict:
    ranker = embedding_ranker or default_embedding_ranker()
    if ranker is None:
        raise RuntimeError("configured local embedding model is unavailable")
    configs = {
        "text_first_top8": None,
        "text_first_top16": None,
        **{f"attribute{pool}_text{final}": (pool, final)
           for pool, final in ATTRIBUTE_CONFIGS},
    }
    totals = {name: Counter() for name in configs}
    episodes = {name: defaultdict(Counter) for name in configs}
    alignment_methods = Counter()
    pair_details = []

    for path in paths:
        snapshot = json.loads(path.read_text())
        result = snapshot["results"][0]
        episode = _episode(snapshot)
        episode_id = episode["id"]
        golden_by_id = {
            item["id"]: item
            for item in episode["ground_truth"]["requirements"]}
        introduced = _introduced_by(episode)
        sources = _evidence_sources_by_id(episode)
        introduction_counts = Counter(introduced.values())

        for row in result["probe_trace"]["chained"]:
            request = compact_message(
                row["round"]["user_input"],
                max_tokens=TRANSLATOR_MESSAGE_MAX_TOKENS)
            requirements = [Requirement.from_dict(item)
                            for item in row["store_state"]]
            active = _active_requirements(requirements)
            selected = {
                "text_first_top8": (
                    _production_candidates(requirements, request, 8),) * 2,
                "text_first_top16": (
                    _production_candidates(requirements, request, 16),) * 2,
            }
            for pool_cap, final_cap in ATTRIBUTE_CONFIGS:
                name = f"attribute{pool_cap}_text{final_cap}"
                selected[name] = attribute_then_text_candidates(
                    requirements, request,
                    attribute_pool_cap=pool_cap, final_cap=final_cap,
                    embedding_ranker=ranker)

            for cid in row["round"]["probe"]["should_apply"]:
                golden = golden_by_id[cid]
                initial = introduced[cid]
                aligned, method = _align_requirement(
                    golden, sources.get(cid, [initial]), active,
                    ambiguous_introduction=introduction_counts[initial] > 1)
                alignment_methods[method] += 1
                detail = {
                    "episode": episode_id,
                    "seq": row["round"]["seq"],
                    "cid": cid,
                    "alignment": method,
                    "store_available": aligned is not None,
                    "results": {},
                }
                for name, (attribute_pool, final) in selected.items():
                    counter = totals[name]
                    episode_counter = episodes[name][episode_id]
                    counter["total"] += 1
                    episode_counter["total"] += 1
                    if aligned is None:
                        detail["results"][name] = {
                            "pool_hit": False, "final_hit": False}
                        continue
                    counter["available"] += 1
                    episode_counter["available"] += 1
                    pool_hit = aligned.id in {
                        item.id for item in attribute_pool}
                    final_hit = aligned.id in {item.id for item in final}
                    detail["results"][name] = {
                        "pool_hit": pool_hit, "final_hit": final_hit}
                    if pool_hit:
                        counter["pool_hit"] += 1
                        episode_counter["pool_hit"] += 1
                    if final_hit:
                        counter["final_hit"] += 1
                        episode_counter["final_hit"] += 1
                pair_details.append(detail)

    return {
        "snapshots": [str(path) for path in paths],
        "protocol": "raw-query-only; attribute embedding pool; body BM25+dense final",
        "alignment_methods": dict(alignment_methods),
        "pair_details": pair_details,
        "configs": {
            name: {
                **_metric_row(totals[name]),
                "episodes": {
                    episode: _metric_row(counter)
                    for episode, counter in sorted(episodes[name].items())},
            }
            for name in configs
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = ablate(args.snapshots)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1))
        print(args.output)
    print("config\tfinal/available\trecall_available\trecall_all\tpool_recall")
    for name, row in report["configs"].items():
        print(f"{name}\t{row['final_hits']}/{row['store_available']}\t"
              f"{row['recall_available']:.3f}\t{row['recall_all']:.3f}\t"
              f"{row['pool_recall_available']:.3f}")


if __name__ == "__main__":
    main()
