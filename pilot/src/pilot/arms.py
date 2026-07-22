"""Prompt assembly for the downstream arms. Downstream sees ONLY what its arm
allows (plan Task 5). Baseline arms (B1_mem0/B2_graphiti) reuse the A2 shape
but their memory block comes from the baseline system's own retrieval
(injected_block), not from the oracle store."""

from __future__ import annotations

DOWNSTREAM_SYSTEM = "You are a helpful assistant."

MEMORY_HEADER = (
    "The following are stored long-term memories about this user, collected "
    "from past conversations. Apply them when they are relevant to the "
    "current request.")


def _memory_block(memories) -> str:
    return "\n".join(f"- [{m['mid']}] {m['text']}" for m in memories)


def _with_content(request: str, content: str) -> str:
    return request if not content else f"{request}\n\n{content}"


def build_downstream_call(arm: str, instance: dict,
                          polished_request: str | None = None,
                          injected_block: str | None = None):
    """Returns (system, user_text) for one downstream call."""
    req = instance["request"]
    content = instance["content"]
    if arm == "A0_none":
        return DOWNSTREAM_SYSTEM, _with_content(req, content)
    if arm == "A1_system":
        system = (f"{DOWNSTREAM_SYSTEM}\n\n{MEMORY_HEADER}\n"
                  f"{_memory_block(instance['memory_store'])}")
        return system, _with_content(req, content)
    if arm == "A2_inject":
        user = (f"{_with_content(req, content)}\n\n<user_memories>\n"
                f"{_memory_block(instance['memory_store'])}\n</user_memories>")
        return DOWNSTREAM_SYSTEM, user
    if arm == "A3_translator":
        if polished_request is None:
            raise ValueError("A3 requires polished_request")
        return DOWNSTREAM_SYSTEM, _with_content(polished_request, content)
    if arm.startswith("B"):
        if injected_block is None:
            raise ValueError(f"{arm} requires injected_block")
        base = _with_content(req, content)
        if not injected_block:
            return DOWNSTREAM_SYSTEM, base  # baseline retrieved nothing
        user = f"{base}\n\n<user_memories>\n{injected_block}\n</user_memories>"
        return DOWNSTREAM_SYSTEM, user
    raise ValueError(f"unknown arm: {arm}")
