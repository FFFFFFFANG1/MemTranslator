"""Read-path recall (design §7): deterministic, zero-LLM, no embeddings.

1. active entries of kind "requirement" (style_rule never joins recall);
2. scope filter — an entry scoped to {task: email} is dropped when the
   context KNOWS the task is something else; unknown dimensions keep the
   entry (never exclude on missing information);
3. within RECALL_CAP everything goes through (v0 behavior); above the cap,
   entries whose facet-key surface forms appear in the query rank first,
   then recency fills the rest.
"""
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
    hits = [r for r in pool if _key_hits_query(r.key, query)]
    rest = [r for r in pool if r not in hits]
    picked = hits[-RECALL_CAP:] + rest[-(RECALL_CAP - min(len(hits), RECALL_CAP)):]
    picked = picked[:RECALL_CAP]
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
