"""Orchestration: the write path (batched extract + consolidate) and read path."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .consolidate import consolidate
from .extract import extract
from .llm import LLM
from .schema import Candidate, ConsolidationOp
from .store import MemoryStore
from .transcript import USER_BATCH_SIZE, format_transcript, iter_user_batches
from .translate import Translation, translate


def run_write_path(
    llm: LLM,
    transcript: str | Sequence[Mapping[str, Any]],
    store: MemoryStore,
    session_id: str,
    *,
    user_batch_size: int = USER_BATCH_SIZE,
) -> list[tuple[Candidate, ConsolidationOp]]:
    """Session-end trigger.

    - str transcript: one extract call (legacy / smoke tests).
    - turn list: compress-ready turns; extract in user-batches of
      `user_batch_size` (default 5), then one consolidate over all candidates.
    Zero candidates ends the run without a consolidate call.
    """
    if isinstance(transcript, str):
        candidates = extract(llm, transcript, store)
    else:
        candidates = []
        for batch in iter_user_batches(transcript, batch_size=user_batch_size):
            candidates.extend(extract(llm, format_transcript(batch), store))
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
