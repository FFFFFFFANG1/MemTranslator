"""Inspect saved E1 real traces at the Translator-entry level.

This is a read-only diagnostic.  It reconstructs the exact recalled list from
each probe's saved Store state, joins prompt-local entry numbers back to Store
entries, and aligns golden requirements through their introducing raw message.
No LLM call is made.

Usage:
    PYTHONPATH=src .venv/bin/python -m bench.suites.analyze_e1_translator \
        bench/results/E1-e-*-20260819-*.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import memtranslator.recall as recall_mod
from memtranslator.config import TRANSLATOR_MESSAGE_MAX_TOKENS
from memtranslator.recall import recall
from memtranslator.retrieval import default_embedding_ranker
from memtranslator.schema import Requirement
from memtranslator.signals import compact_message

from bench.suites.config import CASES


def _episode(snapshot: dict) -> dict:
    episode_id = snapshot["results"][0]["episode"]
    cases_path = Path(snapshot.get("cases_file") or CASES / "episodes")
    episode_path = (cases_path / f"{episode_id}.json"
                    if cases_path.is_dir() else cases_path)
    return json.loads(episode_path.read_text())


def _introduced_by(episode: dict) -> dict[str, str]:
    turns = {turn["seq"]: turn["user_input"]
             for turn in episode["user_turns"]}
    result = {}
    for effect in episode["ground_truth"]["lifecycle"]:
        # ``contradict`` may introduce a successor id (e.g. c19 -> s04), so
        # the first lifecycle effect carrying an id is its introducing turn.
        if effect.get("id") and effect["id"] not in result:
            result[effect["id"]] = turns[effect["seq"]]
    return result


def _evidence_sources_by_id(episode: dict) -> dict[str, list[str]]:
    """All positive source turns for each golden item.

    A later reinforce can produce a better canonical Store entry than the
    first assertion.  Using only the introducing source misaligned those
    successors to stale, narrower entries in the saved E1 traces.
    """
    turns = {turn["seq"]: turn["user_input"]
             for turn in episode["user_turns"]}
    result: dict[str, list[str]] = defaultdict(list)
    for effect in episode["ground_truth"]["lifecycle"]:
        cid = effect.get("id")
        if cid:
            result[cid].append(turns[effect["seq"]])
        target = effect.get("target")
        if effect.get("op") == "reinforce" and target:
            result[target].append(turns[effect["seq"]])
    return {cid: list(dict.fromkeys(sources))
            for cid, sources in result.items()}


def _gold_kind_set(golden: dict) -> set[str]:
    return {"any" if kind == "all" else str(kind)
            for kind in golden.get("work_kinds") or []}


def _normalized_key(key: str | None) -> str:
    """Normalize known namespace spelling variants used by gold and Store."""
    parts = str(key or "").strip().casefold().split(".")
    if parts and parts[0] == "formatting":
        parts[0] = "format"
    return ".".join(parts)


def _align_requirement(golden: dict, sources: list[str],
                       requirements: list[Requirement], *,
                       ambiguous_introduction: bool = False
                       ) -> tuple[Requirement | None, str]:
    """Align a golden item to one real Store item without another model."""
    source_matches = [requirement for requirement in requirements
                      if any(source in requirement.sources
                             for source in sources)]
    if not source_matches:
        return None, "no_source_match"
    key_matches = [requirement for requirement in source_matches
                   if golden.get("key") and requirement.key == golden["key"]]
    if len(key_matches) == 1:
        return key_matches[0], "source+key"
    normalized_key = _normalized_key(golden.get("key"))
    normalized_key_matches = [
        requirement for requirement in source_matches
        if normalized_key
        and _normalized_key(requirement.key) == normalized_key]
    if len(normalized_key_matches) == 1:
        return normalized_key_matches[0], "source+normalized_key"
    anchor = str(golden.get("anchor") or "").strip().casefold()
    anchor_matches = [requirement for requirement in source_matches
                      if anchor and anchor in requirement.text.casefold()]
    if len(anchor_matches) == 1:
        return anchor_matches[0], "source+anchor"
    if len(source_matches) == 1:
        candidate = source_matches[0]
        if (ambiguous_introduction and golden.get("key") and candidate.key
                and _normalized_key(candidate.key)
                != _normalized_key(golden["key"])):
            return None, "ambiguous_source_key_mismatch"
    attribute_matches = [
        requirement for requirement in source_matches
        if requirement.scope_mode == golden.get("scope_mode")
        and set(requirement.kinds) == _gold_kind_set(golden)]
    if len(attribute_matches) == 1:
        return attribute_matches[0], "source+attributes"
    candidates = key_matches or anchor_matches or source_matches
    if len(candidates) == 1:
        return candidates[0], "source_only"
    ranker = default_embedding_ranker()
    if ranker is not None:
        query = f"{golden['text']}\n{golden.get('paraphrase', '')}"
        order = ranker.rank(query, [candidate.text for candidate in candidates])
        if order:
            return candidates[order[0]], "source+dense"
    return candidates[0], "source+first"


def analyze(paths: list[Path], *, verdict_only: bool = False) -> dict:
    lane_verdicts: Counter[tuple[str, str]] = Counter()
    decisions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    candidate_counts: Counter[int] = Counter()
    stages: Counter[str] = Counter()
    alignments: Counter[str] = Counter()
    details = []
    probes = 0
    pooled = Counter()

    for path in paths:
        snapshot = json.loads(path.read_text())
        result = snapshot["results"][0]
        real_scores = [row for row in result["probe_trace"]["scores"]
                       if row["arm"] == "real"]
        pooled["carry_hits"] += sum(
            row["carry_hits"] for row in real_scores)
        pooled["carry_n"] += sum(row["carry_n"] for row in real_scores)
        pooled["suppress_hits"] += sum(
            row["suppress_hits"] for row in real_scores)
        pooled["suppress_n"] += sum(
            row["suppress_n"] for row in real_scores)
        owner = result.get("owner_metrics") or {}
        pooled["tasks_perfect"] += owner.get("tasks_perfect", 0)
        pooled["tasks_n"] += owner.get("tasks_n", 0)
        pooled["memory_hit"] += owner.get("memory_hit", 0)
        pooled["memory_n"] += owner.get("memory_n", 0)
        pooled["state_ok"] += sum(
            row["ok"] for row in snapshot.get("state_rows", []))
        pooled["state_n"] += sum(
            row["n"] for row in snapshot.get("state_rows", []))
        instrument_rows = snapshot.get("instrument_rows", [])
        pooled["canary_samples"] += len(instrument_rows)
        pooled["canary_kills"] += sum(
            not row.get("canary", {}).get("alive")
            for row in instrument_rows)
        episode = _episode(snapshot)
        golden_by_id = {item["id"]: item
                        for item in episode["ground_truth"]["requirements"]}
        introduced_by_id = _introduced_by(episode)
        sources_by_id = _evidence_sources_by_id(episode)
        introduction_counts = Counter(introduced_by_id.values())
        scores_by_seq = {
            row["seq"]: row
            for row in result["probe_trace"]["scores"]
            if row["arm"] == "real"
        }
        cap = int(snapshot.get("scoped_recall_cap", 16))
        recall_mod.SCOPED_RECALL_CAP = cap
        recall_mod.SCOPED_ATTRIBUTE_POOL_CAP = int(
            snapshot.get("scoped_attribute_pool_cap", 0))

        for row in result["probe_trace"]["chained"]:
            out = row.get("chained_out") or {}
            verdicts = out.get("entry_verdicts") or []
            probes += 1
            request = row["round"]["user_input"]
            requirements = [Requirement.from_dict(item)
                            for item in row["store_state"]]
            shown = compact_message(
                request, max_tokens=TRANSLATOR_MESSAGE_MAX_TOKENS)
            recalled = recall(requirements, query=shown, context=None)
            if verdicts and len(recalled) != len(verdicts):
                raise ValueError(
                    f"{path.name} seq={row['round']['seq']}: reconstructed "
                    f"{len(recalled)} entries, trace has {len(verdicts)}")

            candidate_counts[len(recalled)] += 1
            decisions[out.get("decision") or "missing"] += 1
            reasons[out.get("reason") or "ok"] += 1
            global_ids = {requirement.id for requirement in recalled
                          if recall_mod._is_global(requirement)}
            scoped_seen = 0
            verdict_by_id = {}
            position_by_id = {}
            for index, requirement in enumerate(recalled):
                verdict = (verdicts[index] if index < len(verdicts)
                           else {"entry": index + 1,
                                 "verdict": "no_verdict"})
                if requirement.id in global_ids:
                    lane = "global"
                else:
                    scoped_seen += 1
                    lane = "scoped_1_8" if scoped_seen <= 8 else "scoped_9_16"
                lane_verdicts[(lane, verdict["verdict"])] += 1
                verdict_by_id[requirement.id] = verdict["verdict"]
                position_by_id[requirement.id] = {
                    "entry": verdict["entry"], "lane": lane}

            seq = row["round"]["seq"]
            score = scores_by_seq.get(seq, {})
            carry = {item["cid"]: item["hit"]
                     for item in score.get("carry_detail", [])}
            for cid in row["round"]["probe"]["should_apply"]:
                golden = golden_by_id[cid]
                source = introduced_by_id[cid]
                sources = sources_by_id.get(cid, [source])
                ambiguous = introduction_counts[source] > 1
                active = [requirement for requirement in requirements
                          if requirement.status == "active"
                          and requirement.kind == "requirement"]
                aligned, method = _align_requirement(
                    golden, sources, active,
                    ambiguous_introduction=ambiguous)
                alignments[method] += 1
                detail = {"episode": episode["id"], "seq": seq, "cid": cid,
                          "gold": golden["text"], "hit": carry.get(cid),
                          "alignment": method,
                          "user_request": request,
                          "effective_text": score.get("effective_text")}
                if aligned is None:
                    inactive = [requirement for requirement in requirements
                                if requirement.kind == "requirement"]
                    retired, retired_method = _align_requirement(
                        golden, sources, inactive,
                        ambiguous_introduction=ambiguous)
                    stage = ("store_inactive" if retired is not None
                             else "store_missing")
                    detail["inactive_alignment"] = retired_method
                elif aligned.id not in position_by_id:
                    stage = "retrieval_miss"
                    detail.update({"store_id": aligned.id,
                                   "store_text": aligned.text})
                else:
                    verdict = verdict_by_id[aligned.id]
                    detail.update({"store_id": aligned.id,
                                   "store_text": aligned.text,
                                   "store_scope_mode": aligned.scope_mode,
                                   "store_work_kinds": aligned.kinds,
                                   "store_applies_when": aligned.applies_when,
                                   "store_bucket": aligned.bucket,
                                   "store_key": aligned.key,
                                   **position_by_id[aligned.id],
                                   "verdict": verdict})
                    position = position_by_id[aligned.id]["entry"]
                    if position <= len(verdicts):
                        detail["verdict_evidence"] = verdicts[
                            position - 1].get("evidence")
                    if verdict_only:
                        if verdict in {"apply", "already_satisfied"}:
                            stage = "translator_accept"
                        elif verdict == "no_verdict":
                            stage = "translator_no_verdict"
                        else:
                            stage = "translator_reject"
                    elif carry.get(cid):
                        stage = "hit"
                    elif verdict == "no_verdict":
                        stage = "translator_no_verdict"
                    elif verdict == "not_applicable":
                        stage = "translator_reject"
                    elif verdict == "already_satisfied":
                        stage = "already_satisfied_but_judge_miss"
                    else:
                        stage = "applied_but_carry_miss"
                stages[stage] += 1
                detail["stage"] = stage
                details.append(detail)

    lane_rows = []
    for lane in ("global", "scoped_1_8", "scoped_9_16"):
        counts = {verdict: lane_verdicts[(lane, verdict)]
                  for verdict in ("apply", "already_satisfied",
                                  "not_applicable", "no_verdict")}
        counts["total"] = sum(counts.values())
        lane_rows.append({"lane": lane, **counts})
    return {
        "snapshots": [str(path) for path in paths],
        "probes": probes,
        "candidate_count_histogram": dict(sorted(candidate_counts.items())),
        "decisions": dict(decisions),
        "reasons": dict(reasons),
        "lane_verdicts": lane_rows,
        "should_apply_stages": dict(stages),
        "alignment_methods": dict(alignments),
        "pooled_scores": {
            **dict(pooled),
            "accuracy": (
                (pooled["carry_hits"] + pooled["suppress_hits"])
                / (pooled["carry_n"] + pooled["suppress_n"])
                if pooled["carry_n"] + pooled["suppress_n"] else 1.0),
            "per_task": (pooled["tasks_perfect"] / pooled["tasks_n"]
                         if pooled["tasks_n"] else 1.0),
            "per_memory": (pooled["memory_hit"] / pooled["memory_n"]
                           if pooled["memory_n"] else 1.0),
            "state": (pooled["state_ok"] / pooled["state_n"]
                      if pooled["state_n"] else 1.0),
        },
        "should_apply_details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--verdict-only", action="store_true",
        help="classify recalled gold by per-entry verdict without carry judge")
    args = parser.parse_args()
    report = analyze(args.snapshots, verdict_only=args.verdict_only)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text)
        print(args.output)
    else:
        print(text)


if __name__ == "__main__":
    main()
