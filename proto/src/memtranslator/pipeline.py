"""Orchestration: the ≤2-LLM-call write path and the query-time read path."""

from __future__ import annotations

from .consolidate import consolidate
from .extract import extract
from .llm import LLM
from .schema import Candidate, ConsolidationOp
from .store import MemoryStore
from .translate import Translation, translate


def run_write_path(llm: LLM, transcript: str, store: MemoryStore,
                   session_id: str) -> list[tuple[Candidate, ConsolidationOp]]:
    """Session-end trigger. Call 1 extraction; zero candidates ends the run
    at one LLM call, otherwise related-memory lookup (no LLM) + Call 2."""
    candidates = extract(llm, transcript, store)
    if not candidates:
        return []
    related_mids: dict[str, None] = {}
    for cand in candidates:
        probe = " ".join([cand.requirement, cand.scope_condition, *cand.keywords])
        for entry in store.recall(probe, k=5):
            related_mids.setdefault(entry.mid, None)
    related = [store.get(mid) for mid in related_mids]
    return consolidate(llm, candidates, related, store, session_id)


def run_translate(llm: LLM, request: str, store: MemoryStore, content: str = "") -> Translation:
    return translate(llm, request, store, content=content)
