"""Baseline memory adapters (baseline plan B1; configs frozen in
docs/baseline-b0-memo.md).

Uniform surface so arms.py can treat every memory pipeline identically:

    ingest(entries)          # instance memory_store: [{mid, text, topic}]
    inject(query) -> InjectResult   # memory block for the downstream prompt

Fairness rules (baseline plan §2): native ingestion and retrieval APIs, no
preference-targeted tuning, k = RECALL_K, per-instance isolation (fresh
store under a unique workdir).

Accounting: wall time per phase + retrieved count + injected text; internal
LLM call counts are estimated from documented behavior (a per-call hook is a
B2 item if the estimate proves too coarse).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    EMBEDDING_MODEL,
    GRAPHITI_INTERNAL_LLM,
    MEM0_INTERNAL_LLM,
    RECALL_K,
)

HEADER = "Relevant memories about this user:"


@dataclass
class InjectResult:
    text: str                 # "" when nothing retrieved
    n_retrieved: int
    wall_s: float
    raw: list[str] = field(default_factory=list)


def format_block(memories: list[str]) -> str:
    if not memories:
        return ""
    return HEADER + "\n" + "\n".join(f"- {m}" for m in memories)


class BaseAdapter:
    """Shared surface. Harness code should prefer ingest_and_inject(): it lets
    async adapters run the whole instance inside one event-loop run (httpx
    keep-alive pools go stale across run_until_complete gaps otherwise)."""

    ingest_wall_s = 0.0

    def ingest(self, entries: list[dict]) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def inject(self, query: str) -> InjectResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def ingest_and_inject(self, entries: list[dict], query: str) -> InjectResult:
        self.ingest(entries)
        return self.inject(query)

    def close(self) -> None:
        pass


class TopKInjectAdapter(BaseAdapter):
    """Arm A3: the instance's own store injected verbatim (k >= store size, so
    this is full injection — the classic raw-memory-injection baseline)."""

    name = "topk_inject"

    def __init__(self, workdir: Path | None = None, k: int = RECALL_K):
        self.k = k
        self.entries: list[dict] = []
        self.ingest_wall_s = 0.0

    def ingest(self, entries: list[dict]) -> None:
        self.entries = list(entries)

    def inject(self, query: str) -> InjectResult:
        t0 = time.time()
        texts = [e["text"] for e in self.entries[: self.k]]
        return InjectResult(text=format_block(texts), n_retrieved=len(texts),
                            wall_s=time.time() - t0, raw=texts)


class Mem0Adapter(BaseAdapter):
    """Mem0 OSS 2.0.12 — anthropic haiku internal LLM, openai embeddings,
    local qdrant under workdir (B0-frozen config)."""

    name = "mem0"

    def __init__(self, workdir: Path, user_id: str = "u"):
        from mem0 import Memory

        self.user_id = user_id
        self.ingest_wall_s = 0.0
        config = {
            "llm": {"provider": "anthropic",
                    "config": {"model": MEM0_INTERNAL_LLM, "max_tokens": 2000}},
            "embedder": {"provider": "openai", "config": {"model": EMBEDDING_MODEL}},
            "vector_store": {"provider": "qdrant",
                             "config": {"path": str(workdir / "qdrant"), "on_disk": True}},
        }
        self.mem = Memory.from_config(config)

    def ingest(self, entries: list[dict]) -> None:
        t0 = time.time()
        for e in entries:
            self.mem.add([{"role": "user", "content": e["text"]}], user_id=self.user_id)
        self.ingest_wall_s = time.time() - t0

    def inject(self, query: str) -> InjectResult:
        t0 = time.time()
        hits = self.mem.search(query, filters={"user_id": self.user_id}, limit=RECALL_K)
        rows = hits.get("results", hits) if isinstance(hits, dict) else hits
        texts = [r["memory"] if isinstance(r, dict) and "memory" in r else str(r) for r in rows]
        return InjectResult(text=format_block(texts), n_retrieved=len(texts),
                            wall_s=time.time() - t0, raw=texts)


class GraphitiAdapter(BaseAdapter):
    """Graphiti 0.29.2 on embedded FalkorDBLite. Explicit LLMConfig is
    mandatory (B0 finding 2). Retrieval uses the broadest official recipe
    (COMBINED_HYBRID_SEARCH_RRF: edges + nodes + episodes) so sparse-graph
    preferences remain reachable via the episode layer (B0 finding 4)."""

    name = "graphiti"

    def __init__(self, workdir: Path):
        workdir.mkdir(parents=True, exist_ok=True)
        self.workdir = workdir
        self.ingest_wall_s = 0.0

    async def _arun_instance(self, entries: list[dict], query: str) -> InjectResult:
        """Whole instance inside one running loop: client construction included.
        graphiti holds module-level async primitives and httpx pools that bind
        to the loop they first see — constructing outside a running loop (or
        reusing across run_until_complete gaps) yields TLS errors/timeouts."""
        from datetime import datetime, timezone

        from graphiti_core import Graphiti
        from graphiti_core.driver.falkordb_driver import FalkorDriver
        from graphiti_core.embedder.openai import OpenAIEmbedder
        from graphiti_core.llm_client import OpenAIClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.nodes import EpisodeType
        from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
        from openai import AsyncOpenAI
        from redislite.async_falkordb_client import AsyncFalkorDB

        # This network reaches api.openai.com slowly (~5s for a bare GET), so
        # be generous: long timeout + retries on one shared async client.
        oai = AsyncOpenAI(timeout=120.0, max_retries=5)
        lite = AsyncFalkorDB(str(self.workdir / "falkor.db"))
        llm = OpenAIClient(config=LLMConfig(model=GRAPHITI_INTERNAL_LLM,
                                            small_model=GRAPHITI_INTERNAL_LLM),
                           client=oai)
        embedder = OpenAIEmbedder(client=oai)
        g = Graphiti(graph_driver=FalkorDriver(falkor_db=lite), llm_client=llm,
                     embedder=embedder)
        try:
            await g.build_indices_and_constraints()
            t0 = time.time()
            for e in entries:
                await g.add_episode(
                    name=e["mid"],
                    episode_body=f"user: {e['text']}",
                    source=EpisodeType.message,
                    source_description="chat",
                    reference_time=datetime.now(timezone.utc),
                )
            self.ingest_wall_s = time.time() - t0

            t0 = time.time()
            config = COMBINED_HYBRID_SEARCH_RRF.model_copy(deep=True)
            config.limit = RECALL_K
            res = await g.search_(query, config=config)
            texts: list[str] = []
            for edge in getattr(res, "edges", []) or []:
                texts.append(edge.fact)
            for node in getattr(res, "nodes", []) or []:
                if node.summary:
                    texts.append(node.summary)
            for ep in getattr(res, "episodes", []) or []:
                texts.append(ep.content)
            seen: dict[str, None] = {}
            for t in texts:
                seen.setdefault(t.strip(), None)
            texts = list(seen)[:RECALL_K]
            return InjectResult(text=format_block(texts), n_retrieved=len(texts),
                                wall_s=time.time() - t0, raw=texts)
        finally:
            lite.close()

    def ingest_and_inject(self, entries: list[dict], query: str) -> InjectResult:
        return asyncio.run(self._arun_instance(entries, query))


ADAPTERS = {
    "topk_inject": TopKInjectAdapter,
    "mem0": Mem0Adapter,
    "graphiti": GraphitiAdapter,
}
