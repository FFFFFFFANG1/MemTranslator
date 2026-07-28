"""Read-path recall (design §7): deterministic, zero-LLM, no embeddings.

1. active entries of kind "requirement" (style_rule never joins recall);
2. scope filter — an entry scoped to {task: email} is dropped when the
   context KNOWS the task is something else; unknown dimensions keep the
   entry (never exclude on missing information);
3. within RECALL_CAP everything goes through (v0 behavior); above the cap,
   BM25 over the entry's own text decides, recency breaking ties.
"""
from memtranslator.bm25 import BM25
from memtranslator.config import RECALL_CAP, STYLE_RULE_CAP
from memtranslator.schema import Requirement
from memtranslator.signals import _KEY_LEXICON


def _scope_ok(scope: dict, context: dict) -> bool:
    for dim, want in scope.items():
        have = context.get(dim)
        if have is not None and have != want:
            return False
    return True


def _key_hits_query(key: str, query: str) -> bool:
    if not key or not query:
        return False
    low = query.lower()
    for part in key.split("."):
        for term in _KEY_LEXICON.get(part, [part] if len(part) > 2 else []):
            if term.lower() in low:
                return True
    return False


def recall(requirements: list[Requirement], *, query: str = "",
           context: dict | None = None) -> list[Requirement]:
    context = context or {}
    pool = [r for r in requirements
            if r.status == "active" and r.kind == "requirement"
            and _scope_ok(r.scope, context)]
    pool.sort(key=lambda r: r.created_at)
    if len(pool) <= RECALL_CAP:
        return pool
    # Above the cap, rank by BM25 over the entry's own words. The previous
    # ranker keyed on `_KEY_LEXICON`, 14 registered roots, and M1 measured the
    # cost: a rule keyed `report.format` scored zero against "写一份季度服务器
    # 容量规划文档" because neither 报告 nor 格式 appears in it, so an old but
    # exactly-on-topic rule was dropped on recency alone (CARRY 0.00 on that
    # facet). BM25 needs no registry — 文档 matches 长文档 on its own.
    scores = BM25([f"{r.text} {r.key or ''}" for r in pool]).scores(query)
    order = sorted(range(len(pool)),
                   key=lambda i: (-scores[i], -pool[i].created_at))
    picked = [pool[i] for i in order[:RECALL_CAP]]
    picked.sort(key=lambda r: r.created_at)
    return picked


def style_block(requirements: list[Requirement]) -> str:
    """Learned rewrite-style rules for the translator prompt, ≤ cap entries
    (~250 tokens). Empty string when none exist — v0 prompt stays byte-equal."""
    styles = [r for r in requirements
              if r.status == "active" and r.kind == "style_rule"]
    if not styles:
        return ""
    styles.sort(key=lambda r: (-r.strength, -r.updated_at))
    lines = "\n".join(f"- {r.text}" for r in styles[:STYLE_RULE_CAP])
    return f"\nRewrite style rules learned from this user's edits:\n{lines}"
