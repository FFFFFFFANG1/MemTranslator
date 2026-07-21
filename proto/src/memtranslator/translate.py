"""Query-time translation (design §3.3 + idea.md patch-based translation).

The user input is split into REQUEST (the instruction) and CONTENT (attached
material). The translator may only rewrite the REQUEST segment; CONTENT is
reattached mechanically, so content fidelity is guaranteed by structure, not
by model compliance. Scope judgment happens here — the store's recall() only
does cheap candidate narrowing, and a no-op is a first-class outcome.

The polished request is a DRAFT shown to the user in an editable composer
(typeless-style); the user can amend or discard it before anything reaches
the downstream agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLM, parse_json_block
from .schema import MemoryEntry
from .store import MemoryStore

RECALL_K = 8

SYSTEM = """You are a user-input translator. You receive a user's REQUEST and a set of that user's standing REQUIREMENTS (long-term memory). Rewrite the request so it explicitly carries the requirements that apply — and only those.

Judge applicability strictly:
- Apply a requirement only if its scope_condition clearly covers THIS request.
- If the user's request already explicitly asks for something a memory covers, don't restate it redundantly.
- If the user's request explicitly contradicts a memory, THE REQUEST WINS — do not apply that memory.
- If NO requirement clearly applies, output a no-op. An underspecified request is often intentional; never pad the request with generic quality instructions.

Rewriting rules:
- Preserve the user's task, referents, and any wording that carries their intent; expand, don't replace.
- Write the polished request in the same language the user wrote in.
- Do not mention that memories or a translator exist; the output must read as the user's own request.

Output JSON:
{"action": "patch", "revised_request": "...", "applied_memory_ids": ["m-..."], "rationale": "one sentence"}
or
{"action": "noop", "applied_memory_ids": [], "rationale": "one sentence"}"""


@dataclass
class Translation:
    original_request: str
    polished_request: str
    content: str
    applied: list[MemoryEntry] = field(default_factory=list)
    noop: bool = True
    rationale: str = ""

    @property
    def polished_input(self) -> str:
        if self.content:
            return f"{self.polished_request}\n\n{self.content}"
        return self.polished_request


def _memory_view(entries: list[MemoryEntry]) -> str:
    lines = []
    for e in entries:
        lines.append(f"- mid: {e.mid} | polarity: {e.polarity} | strength: {e.strength}\n"
                     f"  requirement: {e.requirement}\n"
                     f"  scope_condition: {e.scope.condition}")
    return "\n".join(lines) if lines else "(none)"


def translate(llm: LLM, request: str, store: MemoryStore, content: str = "") -> Translation:
    noop = Translation(original_request=request, polished_request=request, content=content)
    recalled = store.recall(request, k=RECALL_K)
    if not recalled:
        noop.rationale = "no live memories to consider"
        return noop

    user = (f"<REQUIREMENTS>\n{_memory_view(recalled)}\n</REQUIREMENTS>\n\n"
            f"<REQUEST>\n{request}\n</REQUEST>")
    raw = llm.complete(SYSTEM, user)
    parsed = parse_json_block(raw)
    if not isinstance(parsed, dict) or parsed.get("action") not in ("patch", "noop"):
        noop.rationale = "translator output unparseable; passed through unchanged"
        return noop

    recalled_mids = {e.mid for e in recalled}
    applied_ids = [m for m in parsed.get("applied_memory_ids", []) if m in recalled_mids]
    revised = (parsed.get("revised_request") or "").strip()

    if parsed["action"] == "noop" or not applied_ids or not revised:
        noop.rationale = parsed.get("rationale", "")
        return noop

    store.mark_applied(applied_ids)
    return Translation(
        original_request=request,
        polished_request=revised,
        content=content,
        applied=[store.get(m) for m in applied_ids],
        noop=False,
        rationale=parsed.get("rationale", ""),
    )
