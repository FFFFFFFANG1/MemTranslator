"""Candidate-first CASE consolidator (route A call 2).

Each CASE is one extracted candidate plus its own retrieved top-3 memories.
Lifecycle decisions stay local to the CASE; Store mutations are append-only
ops produced by parse_consolidation_output.

The archived GROUPS store-tidy pass lives in consolidate_tidy_backup.py.
"""
from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from memtranslator.extraction import (
    CHANGE_REPLACE, CHANGE_WITHDRAW, POTENTIAL_CHANGE, MemoryCandidate, _array,
)
from memtranslator.schema import WORK_KIND_ANY, Requirement
from memtranslator.scopes import applicability_narrows

TOP_K = 3


@dataclass
class CandidateCase:
    candidate: MemoryCandidate
    memories: list[Requirement]


CONSOLIDATION_SYSTEM = """You reconcile extracted memory candidates with retrieved stored requirements.
The input contains independent CASES. Each CASE has exactly one candidate and
that candidate's own top-3 memories. Decide only inside that CASE; never borrow
a memory from another CASE. Candidate kind is a retrieval hint. For a
potential_change, change_mode is the Extractor's explicit lifecycle intent:
replace has a successor item; withdraw has no successor. Compare text together
with bucket, scope_mode, applies_when, work_kinds, and key.

Actions:
- add: the candidate item is a distinct durable rule.
- reaffirm: one retrieved memory already expresses the same rule; keep its text.
- merge: a near-synonym of one or more retrieved memories on the same single
  facet. Independently enforceable facets never merge merely because the user
  mentioned them together. Attributes (bucket/scope_mode/applies_when/work_kinds/key) must be
  compatible, and merge must not narrow a broad memory to one scoped instance.
  You may enrich wording on that same facet (optional "text").
- replace: the candidate item supersedes memories on the same facet with a
  changed rule (not a paraphrase). A potential_change must have change_mode
  replace.
- retire: change_mode withdraw explicitly removes a retrieved rule and has no
  successor item. A withdraw CASE may only retire a matching target or ignore
  the CASE; never reaffirm, merge, add, or replace it.
- ignore: evidence is unrelated, ambiguous, or insufficient for a safe state
  change.

Examples:
- candidate "Keep emails under 80 words" vs memory "under 120 words" with the
  same email scope and length facet → replace.
- candidate "Write reports as narrative prose" vs memory "only bullets in reports" in the
  same report scope and format facet → replace
- candidate "Add a sources section" vs memory "keep reports under 500 words"
  → add; these are orthogonal and can both hold.
- candidate and memory express the same rule in different languages → reaffirm.
- candidate "Cite primary sources in research surveys" vs memory "Research
  summaries must cite sources" on the same citation facet → merge.
- candidate "Put the conclusion first and cite sources" vs separate memories
  about conclusion order and citations → keep the independently enforceable
  facets separate; conjunction or co-occurrence is not synonymy.
- pure withdrawal of email greetings vs a matching email-greeting memory → retire.
- change_mode withdraw with a null item vs a matching stored constraint →
  retire; do not invent a successor.
- similar text but incompatible applicability or work_kinds → add or ignore, not merge
  or replace.

Use this judgement order for every CASE:
1. Applicability: compare scope_mode, applies_when, and work_kinds. If both sides explicitly name
   incompatible applicability, they are not the same rule; do not reaffirm,
   merge, replace, or retire that memory.
2. Facet: compare bucket and key together with the behavior described in text.
   Orthogonal facets coexist and therefore use add. A merge may only target
   one facet; it must not combine independently enforceable facets.
3. Relation: equivalent (keep text) → reaffirm; near-synonym / enrich → merge;
   same-facet successor with change_mode replace → replace; change_mode
   withdraw without a successor →
   retire; distinct → add; uncertain → ignore.

Use the candidate item's text for add/replace. For merge, optional "text" is
the unified wording; if omitted, use the candidate item. Do not invent a
successor for replace. Only an explicit potential_change with change_mode
replace may use replace; an ordinary merge must not narrow a stored rule,
and reaffirm keeps the stored text and metadata. Output one judgement per CASE as a strict JSON array:
[{"case":1,"action":"add|retire|replace|reaffirm|merge|ignore",
  "targets":[1],"text":"optional for merge only"}]
targets are memory numbers local to that CASE; add/ignore use [].
merge needs ≥1 target; reaffirm needs exactly 1."""

def _candidate_payload(candidate: MemoryCandidate) -> dict:
    """Fields shown to the consolidator. Sources and confidence stay out."""
    if candidate.item is not None:
        item = {
            "text": candidate.item.text,
            "bucket": candidate.item.bucket,
            "scope_mode": candidate.item.scope_mode,
            "applies_when": candidate.item.applies_when,
            "work_kinds": candidate.item.work_kinds,
            "key": candidate.item.key,
        }
    else:
        item = None
    payload = {
        "id": candidate.id,
        "kind": candidate.kind,
        "change_mode": _effective_change_mode(candidate),
        "item": item,
        "target_query": candidate.change_candidate,
    }
    if candidate.item is None:
        payload.update({"bucket": candidate.bucket,
                        "scope_mode": candidate.scope_mode,
                        "applies_when": candidate.applies_when,
                        "work_kinds": candidate.work_kinds,
                        "key": candidate.key})
    return payload


def _memory_payload(requirement: Requirement) -> dict:
    return {"text": requirement.text, "bucket": requirement.bucket,
            "scope_mode": requirement.scope_mode,
            "applies_when": requirement.applies_when,
            "legacy_scope": requirement.scope,
            "work_kinds": requirement.kinds,
            "key": requirement.key}


def build_consolidation_user_prompt(cases: list[CandidateCase]) -> str:
    blocks = []
    for case_idx, case in enumerate(cases, 1):
        candidate = json.dumps(_candidate_payload(case.candidate),
                               ensure_ascii=False, sort_keys=True)
        memories = "\n".join(
            f"[{memory_idx}] " + json.dumps(_memory_payload(memory),
                                             ensure_ascii=False,
                                             sort_keys=True)
            for memory_idx, memory in enumerate(case.memories, 1)) or "(none)"
        blocks.append(f"CASE {case_idx}\nCANDIDATE: {candidate}\n"
                      f"MEMORIES:\n{memories}")
    return "\n\n".join(blocks) + "\n\nJSON:"


def _store_fields(candidate: MemoryCandidate) -> dict:
    item = candidate.item
    assert item is not None
    return {"text": item.text, "bucket": item.bucket,
            "scope_mode": item.scope_mode,
            "applies_when": item.applies_when,
            "kinds": item.work_kinds, "key": item.key,
            "confidence": item.confidence,
            "sources": list(candidate.source_texts)}


def _source_fields(candidate: MemoryCandidate) -> dict:
    confidence = (candidate.item.confidence if candidate.item is not None
                  else candidate.confidence)
    return {"sources": list(candidate.source_texts),
            "confidence": confidence}


def _candidate_applicability(candidate: MemoryCandidate
                             ) -> tuple[str, list[str]]:
    if candidate.item is not None:
        return candidate.item.applies_when, candidate.item.work_kinds
    return candidate.applies_when, candidate.work_kinds


def _effective_change_mode(candidate: MemoryCandidate) -> str | None:
    """Infer the pre-schema lifecycle bit for legacy in-memory candidates."""
    if candidate.kind != POTENTIAL_CHANGE:
        return None
    if candidate.change_mode in {CHANGE_REPLACE, CHANGE_WITHDRAW}:
        return candidate.change_mode
    return CHANGE_WITHDRAW if candidate.item is None else CHANGE_REPLACE


def _work_kinds_compatible(left: list[str], right: list[str]) -> bool:
    """Unknown legacy metadata does not exclude; explicit disjoint kinds do."""
    if not left or not right or WORK_KIND_ANY in left or WORK_KIND_ANY in right:
        return True
    if set(left) & set(right):
        return True
    prose = {"report", "postmortem"}
    return bool(set(left) & prose and set(right) & prose)


def _condition(requirement: Requirement) -> str:
    if requirement.applies_when:
        return requirement.applies_when
    if requirement.scope:
        return json.dumps(requirement.scope, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
    return ""


def _conditions_compatible(left: str, right: str) -> bool:
    """Explicitly different conditions are not deterministic synonyms."""
    left = _normalized_text(left)
    right = _normalized_text(right)
    return not left or not right or left == right


def _target_contract_valid(action: object, target_ids: list[str],
                           candidate: MemoryCandidate) -> bool:
    mode = _effective_change_mode(candidate)
    if action == "reaffirm":
        return len(target_ids) == 1 and mode != CHANGE_WITHDRAW
    if action == "merge":
        return (bool(target_ids) and candidate.item is not None
                and mode != CHANGE_WITHDRAW)
    if action == "replace":
        return (bool(target_ids) and candidate.item is not None
                and candidate.kind == POTENTIAL_CHANGE
                and mode == CHANGE_REPLACE)
    if action == "retire":
        return (bool(target_ids) and candidate.kind == POTENTIAL_CHANGE
                and mode == CHANGE_WITHDRAW and candidate.item is None)
    return False


def _same_facet(candidate: MemoryCandidate,
                memories: list[Requirement]) -> bool:
    """Reject only explicit facet disagreement; blanks are legacy unknowns."""
    item = candidate.item
    candidate_bucket = item.bucket if item is not None else candidate.bucket
    candidate_key = item.key if item is not None else candidate.key
    buckets = {value for value in
               [candidate_bucket, *(memory.bucket for memory in memories)]
               if value}
    keys = {value for value in
            [candidate_key, *(memory.key for memory in memories)] if value}
    return len(buckets) <= 1 and len(keys) <= 1


def _action_guard_error(action: object, candidate: MemoryCandidate,
                        memories: list[Requirement]) -> str | None:
    """Mechanical state-safety checks beyond the action shape contract."""
    if action in {"merge", "replace"} and not _same_facet(
            candidate, memories):
        return "different facets"
    if action == "merge" and candidate.item is not None:
        item = candidate.item
        if any((bool(item.applies_when) and not _condition(memory))
               or applicability_narrows(
                {}, item.work_kinds, {}, memory.kinds)
                for memory in memories):
            return "merge narrows applicability"
    return None


def _merge_text(value: dict, candidate: MemoryCandidate) -> str | None:
    """Optional judgement text, else candidate item; None if unusable."""
    raw = value.get("text")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if candidate.item is not None and candidate.item.text.strip():
        return candidate.item.text.strip()
    return None


def _normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _exact_duplicate_target(case: CandidateCase) -> int | None:
    """Return the one local target that is textually identical and applicable."""
    if _effective_change_mode(case.candidate) == CHANGE_WITHDRAW:
        return None
    item = case.candidate.item
    if item is None:
        return None
    matches = [
        index for index, memory in enumerate(case.memories, 1)
        if (_normalized_text(item.text) == _normalized_text(memory.text)
            and _work_kinds_compatible(item.work_kinds, memory.kinds)
            and _conditions_compatible(
                item.applies_when, _condition(memory)))]
    return matches[0] if len(matches) == 1 else None


def parse_consolidation_output(raw: str, cases: list[CandidateCase]
                               ) -> tuple[list[dict], list[str]]:
    values = _array(raw)
    if values is None:
        return [], ["consolidation output unparseable"]
    by_case, flags = {}, []
    for value in values:
        if not isinstance(value, dict):
            flags.append("consolidation judgement is not an object")
            continue
        case_idx = value.get("case")
        if not isinstance(case_idx, int) or not 1 <= case_idx <= len(cases):
            flags.append(f"consolidation case out of range: {case_idx!r}")
            continue
        if case_idx in by_case:
            flags.append(f"duplicate consolidation case: {case_idx}")
            continue
        by_case[case_idx] = value

    # Exact duplicates have a deterministic lifecycle. Normalise any
    # non-retirement judgement before conflict detection so the target
    # participates in the same fail-closed collision policy as an explicit
    # reaffirm; an erroneous replace/merge must not mint a text-identical heir.
    for case_idx, value in list(by_case.items()):
        if value.get("action") not in {
                "add", "ignore", "replace", "reaffirm", "merge"}:
            continue
        target = _exact_duplicate_target(cases[case_idx - 1])
        targets = value.get("targets", [])
        multi_target_merge = (value.get("action") == "merge"
                              and isinstance(targets, list)
                              and len(targets) > 1)
        if target is not None and not multi_target_merge:
            by_case[case_idx] = {**value, "action": "reaffirm",
                                 "targets": [target]}

    # Pre-scan the whole batch before building any op. If two otherwise-valid
    # actions claim one Store target, every action involved in that collision
    # is dropped. This is intentionally fail-closed rather than first-wins:
    # CASE order is a rendering detail, not evidence priority.
    target_cases: dict[str, list[int]] = defaultdict(list)
    for case_idx, value in by_case.items():
        case = cases[case_idx - 1]
        targets = value.get("targets", [])
        if (not isinstance(targets, list) or len(set(targets)) != len(targets)
                or any(not isinstance(target, int)
                       or not 1 <= target <= len(case.memories)
                       for target in targets)):
            continue
        target_ids = [case.memories[target - 1].id for target in targets]
        memories = [case.memories[target - 1] for target in targets]
        if (_target_contract_valid(value.get("action"), target_ids,
                                   case.candidate)
                and _action_guard_error(value.get("action"), case.candidate,
                                        memories) is None):
            for target_id in target_ids:
                target_cases[target_id].append(case_idx)
    conflicted_cases = set()
    for target_id, claimants in target_cases.items():
        if len(claimants) < 2:
            continue
        ordered = sorted(claimants)
        conflicted_cases.update(ordered)
        flags.append(f"target conflict {target_id}: cases {ordered}")

    ops = []
    for case_idx, case in enumerate(cases, 1):
        value = by_case.get(case_idx)
        if value is None:
            flags.append(f"missing consolidation case: {case_idx}")
            continue
        action = value.get("action")
        targets = value.get("targets", [])
        if not isinstance(targets, list) or any(
                not isinstance(target, int)
                or not 1 <= target <= len(case.memories)
                for target in targets):
            flags.append(f"case {case_idx}: target outside own top-{TOP_K}")
            continue
        if len(set(targets)) != len(targets):
            flags.append(f"case {case_idx}: duplicate target")
            continue
        target_ids = [case.memories[target - 1].id for target in targets]
        if case_idx in conflicted_cases:
            continue

        item = case.candidate.item
        candidate_ops: list[dict] = []
        if action == "ignore" and not targets:
            continue
        mode = _effective_change_mode(case.candidate)
        if action in {"reaffirm", "merge", "replace", "retire"}:
            if not _target_contract_valid(
                    action, target_ids, case.candidate):
                flags.append(f"case {case_idx}: invalid {action!r} contract")
                continue
            target_memories = [case.memories[target - 1]
                               for target in targets]
            guard_error = _action_guard_error(
                action, case.candidate, target_memories)
            if guard_error:
                flags.append(f"case {case_idx}: {guard_error}")
                continue
        if action == "add" and not targets and item is not None \
                and mode != CHANGE_WITHDRAW:
            candidate_ops = [{"kind": "new", **_store_fields(case.candidate)}]
        elif (action == "reaffirm" and len(target_ids) == 1
              and mode != CHANGE_WITHDRAW):
            candidate_ops = [{"kind": "reinforce",
                              "target_id": target_ids[0],
                              **_source_fields(case.candidate)}]
        elif (action == "merge" and target_ids and item is not None
              and mode != CHANGE_WITHDRAW):
            merged = _merge_text(value, case.candidate)
            if merged is None:
                flags.append(f"case {case_idx}: merge missing text")
                continue
            fields = {**_store_fields(case.candidate), "text": merged}
            if len(target_ids) == 1:
                candidate_ops = [{"kind": "contradict",
                                  "target_id": target_ids[0], **fields}]
            else:
                candidate_ops = [{"kind": "merge",
                                  "target_ids": target_ids, **fields}]
        elif (action == "replace" and target_ids and item is not None
              and case.candidate.kind == POTENTIAL_CHANGE
              and mode == CHANGE_REPLACE):
            fields = _store_fields(case.candidate)
            if len(target_ids) == 1:
                candidate_ops = [{"kind": "contradict",
                                  "target_id": target_ids[0], **fields}]
            else:
                candidate_ops = [{"kind": "merge",
                                  "target_ids": target_ids, **fields}]
        elif (action == "retire" and target_ids
              and case.candidate.kind == POTENTIAL_CHANGE
              and mode == CHANGE_WITHDRAW and item is None):
            extras = _source_fields(case.candidate)
            candidate_ops = [{"kind": "retire", "target_id": target_id,
                              "withdrawal": True, **extras}
                             for target_id in target_ids]
        else:
            flags.append(f"case {case_idx}: invalid {action!r} contract")
            continue

        if action in {"reaffirm", "merge", "replace", "retire"}:
            candidate_condition, candidate_kinds = _candidate_applicability(
                case.candidate)
            incompatible = [
                memory.id for memory in
                (case.memories[target - 1] for target in targets)
                if (not _work_kinds_compatible(candidate_kinds, memory.kinds)
                    or not _conditions_compatible(
                        candidate_condition, _condition(memory)))]
            if incompatible:
                flags.append(
                    f"case {case_idx}: incompatible applicability targets "
                    f"{incompatible}")
                continue
        ops.extend(candidate_ops)
    return ops, flags


__all__ = [
    "CONSOLIDATION_SYSTEM", "CandidateCase", "TOP_K",
    "build_consolidation_user_prompt", "parse_consolidation_output",
]
