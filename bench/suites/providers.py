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

# op: {"kind": "new"|"reinforce"|"contradict"|"retire", "target_id": str|None,
#      "text": str}  |  {"kind": "merge", "target_ids": [str, ...], "text": str}


class ExtractionProvider(Protocol):
    def extract(self, events: list[dict],
                existing: list[Requirement]) -> list[dict]: ...

    def consolidate(self, existing: list[Requirement]) -> list[dict]: ...


class NullProvider:
    def extract(self, events, existing):
        return []

    def consolidate(self, existing):
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
id and the corrected text; if the user durably withdraws one with no
replacement ("不用了", "forget that rule"), emit retire with its id. A user
merely deleting a woven-in constraint from one request is a one-off signal —
emit nothing for it.
Output strictly a JSON array (possibly empty):
[{"kind": "new"|"reinforce"|"contradict"|"retire", "target_id": <id or null>, "text": "..."}]"""

CONSOLIDATE_SYSTEM = """You tidy a store of a user's delivery requirements.
Given the full store, find entries that express the SAME durable rule (near
duplicates, translations of each other) and merge them; leave distinct rules
alone. Only merge when the rules are genuinely equivalent.
Output strictly a JSON array (possibly empty):
[{"kind": "merge", "target_ids": ["<id>", "<id>", ...], "text": "<merged rule>"}]"""


def _parse_ops(raw: str) -> list[dict]:
    s = raw.strip()
    start, end = s.find("["), s.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        ops = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for o in ops:
        if not isinstance(o, dict):
            continue
        if o.get("kind") in ("new", "reinforce", "contradict") \
                and isinstance(o.get("text"), str):
            out.append(o)
        elif o.get("kind") == "retire" and o.get("target_id"):
            out.append(o)
        elif o.get("kind") == "merge" \
                and isinstance(o.get("target_ids"), list) \
                and isinstance(o.get("text"), str):
            out.append(o)
    return out


class ReferenceProvider:
    def extract(self, events, existing):
        idx = "\n".join(f"- [{r.id}] {r.text}" for r in existing) or "(none)"
        evs = json.dumps(events, ensure_ascii=False, indent=1)
        raw = llm.complete(MODELS["translator"], REFERENCE_SYSTEM,
                           f"Existing requirements:\n{idx}\n\nEvents:\n{evs}\n\nJSON:")
        return _parse_ops(raw)

    def consolidate(self, existing):
        idx = "\n".join(f"- [{r.id}] {r.text}" for r in existing) or "(none)"
        raw = llm.complete(MODELS["translator"], CONSOLIDATE_SYSTEM,
                           f"Store:\n{idx}\n\nJSON:")
        return _parse_ops(raw)


class V1Provider:
    """The real v1 pipeline behind the bench seam (design §9): signal layer
    (screening + span attribution) → batched extraction → ops. Thin on
    purpose — no time triggers (the bench feeds explicit batches), and
    style_rule ops are filtered out: they are product-internal rewrite
    feedback, not requirement ops in the bench contract."""

    def extract(self, events, existing):
        """Native ops from both channels, without collapsing their store
        semantics: route A's belong to `Store.apply_ops`, route B's only to
        `Store.apply_feedback_ops`, where an update edits the attributed
        entry in place."""
        from memtranslator.extraction import run_a_extraction, run_b_extraction
        from memtranslator.signals import patch_diff, screen_message

        keys = [r.key for r in existing if r.key]
        texts = [r.text for r in existing]
        a_spans, b_signals = [], []
        for e in events:
            if e.get("type") == "natural":
                a_spans += screen_message(e["text"], existing_keys=keys,
                                          existing_texts=texts)
            elif e.get("type") == "edited_diff":
                # The product records entry snapshots at translate time;
                # the fixtures name them as indices into their fixed local
                # store, which is the same thing one dereference earlier.
                entries = [existing[i].to_dict() for i in e.get("applied", [])
                           if isinstance(i, int) and 0 <= i < len(existing)]
                diff = patch_diff(e["polished"], e["final"])
                if entries and diff:
                    b_signals.append({"entries": entries, "diff": diff})
        ops = []
        if a_spans:
            by_id = {r.id: r for r in existing}
            for o in run_a_extraction(a_spans, existing)["ops"]:
                if o.get("rkind") == "style_rule":
                    continue
                # the bench contract grades reinforce text against the gist;
                # the rule being reinforced IS the target entry's text
                if o["kind"] == "reinforce" and "text" not in o:
                    o = {**o, "text": by_id[o["target_id"]].text}
                ops.append(o)
        if b_signals:
            ops += run_b_extraction(b_signals)["ops"]
        return ops

    def consolidate(self, existing):
        from memtranslator.consolidate import consolidation_ops
        return consolidation_ops(existing)["ops"]


PROVIDERS = {"null": NullProvider, "reference": ReferenceProvider,
             "v1": V1Provider}
