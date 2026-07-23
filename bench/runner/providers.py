"""ExtractionProvider: the seam between this bench and the v1 pipeline.

The bench ships two stand-ins — NullProvider (floor) and ReferenceProvider
(a deliberately naive single-call baseline for harness smoke + a number to
beat). NEITHER is the v1 implementation; when the real pipeline lands in
src/, wrap it behind this protocol and pass --provider v1."""
import json
from typing import Protocol

from memtranslator import llm
from memtranslator.config import MODELS
from memtranslator.schema import Requirement

# op: {"kind": "new"|"reinforce"|"contradict", "target_id": str|None, "text": str}


class ExtractionProvider(Protocol):
    def extract(self, events: list[dict],
                existing: list[Requirement]) -> list[dict]: ...


class NullProvider:
    def extract(self, events, existing):
        return []


REFERENCE_SYSTEM = """You maintain a store of a user's delivery requirements —
rules about HOW tasks should be executed and delivered (length, format, tone,
method, workflow). From the events below, extract requirement operations.
Only extract durable "how the task is done" rules the user actually expressed.
Never extract: content preferences (what to recommend, personal facts),
one-off instructions scoped to a single task ("this time", "例外", "这次"),
or task content itself.
Existing requirements are listed with ids; if an event restates one, emit
reinforce with its id; if it durably overrides one, emit contradict with its
id and the corrected text. Otherwise emit new.
Output strictly a JSON array (possibly empty):
[{"kind": "new"|"reinforce"|"contradict", "target_id": <id or null>, "text": "..."}]"""


class ReferenceProvider:
    def extract(self, events, existing):
        idx = "\n".join(f"- [{r.id}] {r.text}" for r in existing) or "(none)"
        evs = json.dumps(events, ensure_ascii=False, indent=1)
        raw = llm.complete(MODELS["translator"], REFERENCE_SYSTEM,
                           f"Existing requirements:\n{idx}\n\nEvents:\n{evs}\n\nJSON:")
        s = raw.strip()
        start, end = s.find("["), s.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            ops = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            return []
        return [o for o in ops if isinstance(o, dict)
                and o.get("kind") in ("new", "reinforce", "contradict")
                and isinstance(o.get("text"), str)]


PROVIDERS = {"null": NullProvider, "reference": ReferenceProvider}
