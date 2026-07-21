"""Write path Call 2: batch consolidation of candidates vs related memories.

One call for the whole batch (contrast: Mem0 spends one update call per fact).
Degradation is conservative per design §3.4: unparseable output drops the
whole batch into quarantine; a bad target_mid degrades that op to ADD.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .llm import LLM, parse_json_block
from .schema import OPS, Candidate, ConsolidationOp, MemoryEntry, Provenance
from .store import MemoryStore

SYSTEM = """You consolidate candidate user requirements into an existing requirement memory store.

You receive CANDIDATES (extracted from today's session) and RELATED existing memories. For EVERY candidate index, output exactly one operation:

- ADD: genuinely new requirement, distinct from all related memories.
- REINFORCE: semantically equivalent to one existing memory -> give its mid as target_mid. The store will bump that memory's strength; no new entry is created.
- SUPERSEDE: clearly CONFLICTS with or explicitly REVISES one existing memory covering the same scope -> give target_mid, and optionally merged_requirement (one sentence that the new AND old evidence both support).
- DROP: one-off, situational, unreliable, or you are unsure.

Rules:
- SUPERSEDE only for clear conflict or explicit revision. "Similar but not conflicting" is ADD, never a merge — merging loses information.
- Match by specific facet (same behavior under the same scope), not by broad topic: "write emails briefly" and "write emails informally" are different facets — never REINFORCE or SUPERSEDE across facets.
- Never infer requirements the user did not state: no combining two requirements into an implied third, no strengthening a requirement beyond its evidence. A merged_requirement must be supported by BOTH the old and the new evidence.
- When unsure between any two operations, choose the more conservative one (DROP > REINFORCE > ADD > SUPERSEDE).
- Candidates that duplicate EACH OTHER: keep the clearest one (ADD/REINFORCE/SUPERSEDE as appropriate), DROP the rest.

Output JSON: {"ops": [{"candidate_idx": 0, "op": "ADD"}, {"candidate_idx": 1, "op": "REINFORCE", "target_mid": "m-..."}, ...]}. Every candidate index must appear exactly once."""


def _related_view(entries: list[MemoryEntry]) -> list[dict]:
    return [
        {"mid": e.mid, "requirement": e.requirement, "polarity": e.polarity,
         "scope_condition": e.scope.condition, "strength": e.strength}
        for e in entries
    ]


def consolidate(llm: LLM, candidates: list[Candidate], related: list[MemoryEntry],
                store: MemoryStore, session_id: str) -> list[tuple[Candidate, ConsolidationOp]]:
    """Runs Call 2 and mechanically applies the returned ops. Returns what was applied."""
    if not candidates:
        return []

    payload = json.dumps(
        {"candidates": [asdict(c) for c in candidates], "related": _related_view(related)},
        ensure_ascii=False, indent=2,
    )
    raw = llm.complete(SYSTEM, payload)
    parsed = parse_json_block(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ops"), list):
        store.quarantine(raw, stage="consolidate", reason="unparseable consolidation output; whole batch dropped")
        return []

    known_mids = {e.mid for e in related}
    ops_by_idx: dict[int, ConsolidationOp] = {}
    for item in parsed["ops"]:
        try:
            op = ConsolidationOp(
                candidate_idx=int(item["candidate_idx"]),
                op=str(item["op"]).upper(),
                target_mid=item.get("target_mid"),
                merged_requirement=item.get("merged_requirement"),
                reason=item.get("reason"),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if op.op in OPS and 0 <= op.candidate_idx < len(candidates) and op.candidate_idx not in ops_by_idx:
            ops_by_idx[op.candidate_idx] = op
    # Candidates the model failed to mention get no op — i.e. an implicit DROP,
    # which is the conservative default direction.

    applied: list[tuple[Candidate, ConsolidationOp]] = []
    for idx, op in sorted(ops_by_idx.items()):
        cand = candidates[idx]
        if op.op in ("REINFORCE", "SUPERSEDE") and op.target_mid not in known_mids:
            op = ConsolidationOp(candidate_idx=idx, op="ADD", reason="degraded: unknown target_mid")

        if op.op == "DROP":
            applied.append((cand, op))
            continue
        if op.op == "REINFORCE":
            prov = Provenance(session_id=session_id, turn=cand.turn, signal=cand.signal, quote=cand.quote)
            store.reinforce(op.target_mid, prov)
            applied.append((cand, op))
            continue

        entry = cand.to_entry(session_id)
        if op.op == "SUPERSEDE":
            if op.merged_requirement:
                entry.requirement = op.merged_requirement.strip()
            old = store.get(op.target_mid)
            # Merged statement must stay auditable from both sides: carry the
            # superseded entry's provenance forward.
            if old is not None:
                entry.provenance = old.provenance + entry.provenance
            store.supersede(op.target_mid, entry)
        else:  # ADD
            store.add(entry)
        applied.append((cand, op))
    return applied
