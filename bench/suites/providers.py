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

    def reconcile(self, candidate: dict,
                  existing: list[Requirement]) -> list[dict]: ...


class NullProvider:
    def extract(self, events, existing):
        return []

    def consolidate(self, existing):
        return []

    def reconcile(self, candidate, existing):
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

    def reconcile(self, candidate, existing):
        # Naive baseline: treat a near-duplicate candidate as reinforce of
        # the first existing entry; otherwise emit nothing.
        item = (candidate or {}).get("item") or {}
        text = item.get("text") or ""
        if not text or not existing:
            return []
        return [{"kind": "reinforce", "target_id": existing[0].id,
                 "text": existing[0].text}]


class V1Provider:
    """The real v1 pipeline behind the bench seam (design §9): natural
    messages → batched extraction → ops. Thin on purpose — no time triggers
    (the bench feeds explicit batches), and
    style_rule ops are filtered out: they are product-internal rewrite
    feedback, not requirement ops in the bench contract."""

    def extract(self, events, existing):
        """Native ops from both channels, without collapsing their store
        semantics: route A's belong to `Store.apply_ops`, route B's only to
        `Store.apply_feedback_ops`, where an update edits the attributed
        entry in place."""
        from memtranslator.extraction import run_a_extraction, run_b_extraction
        from memtranslator.signals import patch_diff

        self.last_trace = {"events": list(events), "route_a": None,
                           "route_b": None, "ops": []}
        a_messages, b_signals = [], []
        for e in events:
            if e.get("type") == "natural":
                text = e.get("text") or ""
                if text.strip():
                    # Keep bench and product admission identical: A sees the
                    # complete natural message and decides candidate/discard.
                    a_messages.append(text)
            elif e.get("type") == "edited_diff":
                # Prefer entry snapshots recorded at translate time (product
                # / E2E shape). Suite L fixtures still use indices into the
                # fixed local store via `applied`.
                if e.get("entries"):
                    entries = [entry for entry in e["entries"]
                               if isinstance(entry, dict) and entry.get("id")]
                else:
                    entries = [existing[i].to_dict()
                               for i in e.get("applied", [])
                               if isinstance(i, int)
                               and 0 <= i < len(existing)]
                diff = patch_diff(e["polished"], e["final"])
                if entries and diff:
                    b_signals.append({"entries": entries, "diff": diff})
        ops = []
        if a_messages:
            by_id = {r.id: r for r in existing}
            a_out = run_a_extraction(a_messages, existing)
            self.last_trace["route_a"] = a_out.get("trace")
            for o in a_out["ops"]:
                if o.get("rkind") == "style_rule":
                    continue
                # the bench contract grades reinforce text against the gist;
                # the rule being reinforced IS the target entry's text
                if o["kind"] == "reinforce" and "text" not in o:
                    o = {**o, "text": by_id[o["target_id"]].text}
                ops.append({**o, "channel": "a"})
        if b_signals:
            b_out = run_b_extraction(b_signals)
            self.last_trace["route_b"] = b_out.get("trace")
            for o in b_out["ops"]:
                ops.append({**o, "channel": "b"})
        self.last_trace["ops"] = list(ops)
        return ops

    def consolidate(self, existing):
        # GROUPS tidy consolidator archived to consolidate_tidy_backup.py.
        return []

    def reconcile(self, candidate, existing):
        """Feed one structured candidate to the live CASE consolidator.

        Retrieval is the product's hybrid top-3; the model only sees the
        CASE payload, never Store IDs.
        """
        from memtranslator import llm
        from memtranslator.config import GEN_TEMPERATURE, MODELS
        from memtranslator.consolidate import (
            CONSOLIDATION_SYSTEM, build_consolidation_user_prompt,
            parse_consolidation_output)
        from memtranslator.extraction import (
            POTENTIAL_CHANGE, CandidateItem, MemoryCandidate)
        from memtranslator.memory_write import retrieve_cases
        kind = candidate.get("kind") or "potential_new"
        item_raw = candidate.get("item")
        item = None
        if isinstance(item_raw, dict):
            item_kinds = list(item_raw.get("work_kinds") or [])
            item_condition = str(item_raw.get("applies_when") or "").strip()
            item_mode = str(item_raw.get("scope_mode") or (
                "global" if item_kinds in (["all"], ["any"])
                and not item_condition else "scoped"))
            item = CandidateItem(
                text=str(item_raw.get("text") or "").strip(),
                bucket=str(item_raw.get("bucket") or ""),
                applies_when=item_condition,
                scope_mode=item_mode,
                work_kinds=item_kinds,
                key=str(item_raw.get("key") or ""),
                confidence=int(item_raw.get("confidence") or 0))
        change = candidate.get("target_query", candidate.get("change_candidate"))
        change = change.strip() if isinstance(change, str) else None
        change_mode = candidate.get("change_mode")
        source_text = candidate.get("source_text") or (
            item.text if item else change or "")
        mem = MemoryCandidate(
            id="C1", kind=kind, item=item, change_candidate=change,
            source_signal_ids=[1], source_texts=[source_text], ordinal=1,
            bucket=(item.bucket if item else str(candidate.get("bucket") or "")),
            applies_when=(item.applies_when if item else str(
                candidate.get("applies_when") or "").strip()),
            scope_mode=(item.scope_mode if item else str(
                candidate.get("scope_mode") or "scoped")),
            work_kinds=(item.work_kinds if item else list(
                candidate.get("work_kinds") or [])),
            key=(item.key if item else str(candidate.get("key") or "")),
            confidence=(item.confidence if item else int(
                candidate.get("confidence") or 0)),
            change_mode=(change_mode if change_mode in {"replace", "withdraw"}
                         else None))
        if kind == POTENTIAL_CHANGE and not mem.change_candidate:
            return []
        if kind != POTENTIAL_CHANGE and (item is None or not item.text):
            return []

        cases = retrieve_cases([mem], existing)
        writer = MODELS.get("writer") or MODELS["translator"]
        raw = llm.complete(
            writer, CONSOLIDATION_SYSTEM,
            build_consolidation_user_prompt(cases),
            max_tokens=llm.budget_for(writer, 500),
            temperature=GEN_TEMPERATURE)
        ops, _flags = parse_consolidation_output(raw, cases)
        by_id = {r.id: r for r in existing}
        out = []
        for op in ops:
            if op.get("kind") == "reinforce" and "text" not in op:
                target = by_id.get(op.get("target_id") or "")
                if target is not None:
                    op = {**op, "text": target.text}
            out.append(op)
        return out


PROVIDERS = {"null": NullProvider, "reference": ReferenceProvider,
             "v1": V1Provider}
