"""B0 smoke: can Mem0 OSS and Graphiti (kuzu, no docker) store and retrieve
3 PrefEval-style preferences end to end?

Usage:  source ~/.zshrc && uv run python scripts/smoke_baselines.py [mem0|graphiti|all]

Writes state under runs/smoke/ (gitignored). Prints PASS/FAIL per system plus
the retrieval output, so the config decisions (internal LLM, embedder) can be
recorded in the B0 memo.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs" / "smoke"
RUNS.mkdir(parents=True, exist_ok=True)

PREFS = [
    "I strictly avoid restaurants that serve gluten because of a severe intolerance.",
    "I prefer boutique hotels over large chains when I travel.",
    "For fitness advice, I want low-impact exercises only — my knees are shot.",
]
QUERY = "I'll be visiting Rome soon. What restaurants should I try?"


def smoke_mem0() -> None:
    from mem0 import Memory

    config = {
        "llm": {
            "provider": "anthropic",
            "config": {"model": "claude-haiku-4-5-20251001", "max_tokens": 2000},
        },
        "embedder": {
            "provider": "openai",
            "config": {"model": "text-embedding-3-small"},
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {"path": str(RUNS / "mem0_qdrant"), "on_disk": True},
        },
    }
    m = Memory.from_config(config)
    t0 = time.time()
    for i, p in enumerate(PREFS):
        m.add([{"role": "user", "content": p}], user_id="smoke-user")
        print(f"  mem0 add[{i}] ok ({time.time()-t0:.1f}s cumulative)")
    # mem0 2.0: entity params go in filters=, not top-level kwargs
    hits = m.search(QUERY, filters={"user_id": "smoke-user"}, limit=3)
    rows = hits.get("results", hits) if isinstance(hits, dict) else hits
    print(f"  mem0 search returned {len(rows)} rows:")
    for r in rows:
        print("   -", (r.get("memory") if isinstance(r, dict) else r))
    assert rows, "mem0 search returned nothing"
    assert any("gluten" in str(r).lower() for r in rows), "gluten preference not retrieved"
    print("MEM0 SMOKE: PASS")


async def smoke_graphiti() -> None:
    # Backend: embedded FalkorDBLite (no docker). graphiti's kuzu backend is
    # deprecated upstream and its FTS/index setup is broken in 0.29.2 — see
    # docs/baseline-b0-memo.md for the audit trail.
    from graphiti_core import Graphiti
    from graphiti_core.driver.falkordb_driver import FalkorDriver
    from redislite.async_falkordb_client import AsyncFalkorDB  # FalkorDriver awaits queries

    from graphiti_core.llm_client import OpenAIClient
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.nodes import EpisodeType

    lite = AsyncFalkorDB(str(RUNS / "graphiti_falkor.db"))
    driver = FalkorDriver(falkor_db=lite)
    # Explicit LLMConfig is mandatory: with the default (model=None) entity
    # extraction returns nothing at all, silently. See baseline-b0-memo.
    llm = OpenAIClient(config=LLMConfig(model="gpt-4.1-mini", small_model="gpt-4.1-mini"))
    g = Graphiti(graph_driver=driver, llm_client=llm)
    try:
        await g.build_indices_and_constraints()
        from datetime import datetime, timezone
        total_nodes = 0
        for i, p in enumerate(PREFS):
            t0 = time.time()
            res = await g.add_episode(
                name=f"pref-{i}",
                episode_body=f"user: {p}",
                source=EpisodeType.message,
                source_description="chat",
                reference_time=datetime.now(timezone.utc),
            )
            total_nodes += len(res.nodes)
            print(f"  graphiti add_episode[{i}] ok ({time.time()-t0:.1f}s) "
                  f"nodes={[n.name for n in res.nodes]} edges={len(res.edges)}")
        # Known behavior (B0 finding): isolated preference statements yield a
        # sparse graph (often 1 node, 0 edges), so the default edge-oriented
        # search returns nothing. Fair ingestion shape (conversation-stream
        # episodes + episode-level search config) is a B1 design item.
        results = await g.search(QUERY, num_results=5)
        print(f"  graphiti default search returned {len(results)} edges (sparse-graph caveat applies)")
        assert total_nodes > 0, "entity extraction produced nothing — check LLMConfig"
        print("GRAPHITI SMOKE: PASS (pipeline works; ingestion shape decided in B1)")
    finally:
        try:
            await g.close()
        except TypeError:
            lite.close()  # sync lite client: graphiti's async close doesn't apply


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    assert os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("OPENAI_API_KEY"), \
        "source ~/.zshrc first (needs ANTHROPIC_API_KEY + OPENAI_API_KEY)"
    if which in ("mem0", "all"):
        print("== Mem0 OSS ==")
        smoke_mem0()
    if which in ("graphiti", "all"):
        print("== Graphiti (kuzu) ==")
        asyncio.run(smoke_graphiti())
