"""Append-only JSONL store for requirements, plus an event log.

Every mutation appends the full record; the latest record per id wins on
load. Nothing is ever rewritten in place — history stays in the file. The
event log records what the shell observes (translate calls, sends and their
edit diffs); v0 records, v1 learns from it (anchor §4 编辑回流).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from memtranslator.schema import (BINDINGS, BUCKETS, KINDS, POLARITIES,
                                  STATUSES, Requirement)

AUTO_RETIRE_AT = -2          # strength ≤ -2 → implicit retire (design §3)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._items: dict[str, Requirement] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                req = Requirement.from_dict(json.loads(line))
                self._items[req.id] = req

    def _append(self, req: Requirement) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(req.to_dict(), ensure_ascii=False) + "\n")

    def add(self, text: str, *, kind: str = "requirement", key: str = "",
            scope: dict | None = None, source: str = "manual",
            salience: int = 3, supersedes: str | None = None,
            bucket: str = "", binding: str = "", polarity: str = "",
            evidence_id: str = "") -> Requirement:
        text = text.strip()
        if not text:
            raise ValueError("requirement text is empty")
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind}")
        # Empty means unclassified, which is legal; a NON-empty value outside
        # the vocabulary is a bug upstream and must not be persisted silently.
        for value, allowed, label in ((bucket, BUCKETS, "bucket"),
                                      (binding, BINDINGS, "binding"),
                                      (polarity, POLARITIES, "polarity")):
            if value and value not in allowed:
                raise ValueError(f"unknown {label}: {value}")
        req = Requirement(text=text, kind=kind, key=key, scope=scope or {},
                          source=source, salience=salience,
                          supersedes=supersedes, bucket=bucket,
                          binding=binding, polarity=polarity,
                          evidence_id=evidence_id)
        self._items[req.id] = req
        self._append(req)
        return req

    def persist(self, req: Requirement) -> None:
        """Re-append an in-place-mutated entry (e.g. work-kind tagging).
        Without this the mutation lives only in memory and a restarted
        store loses it — measured as chained-store files whose entries all
        carried kinds=[] while the running process saw them tagged."""
        if req.id in self._items:
            self._append(req)

    def bump_strength(self, req_ids: list[str], delta: int) -> None:
        """Mechanical strength rule (0 token): accepted → +1, reverted → -1;
        crossing AUTO_RETIRE_AT retires implicitly (recoverable via update)."""
        for rid in req_ids:
            req = self._items.get(rid)
            if req is None:
                continue
            req.strength += delta
            req.updated_at = time.time()
            if req.strength <= AUTO_RETIRE_AT and req.status == "active":
                req.status = "retired"
            self._append(req)

    def apply_ops(self, ops: list[dict]) -> dict:
        """Apply extraction/consolidation ops (design §3 落库映射).

        Unknown targets are skipped, never fatal — an op batch from an LLM
        must not be able to crash the store."""
        applied, skipped = 0, []
        for op in ops:
            kind = op.get("kind")
            if kind == "new":
                self.add(op["text"], kind=op.get("rkind", "requirement"),
                         key=op.get("key", ""),
                         scope=op.get("scope") or {}, source="learned",
                         salience=op.get("salience", 3),
                         bucket=op.get("bucket", ""),
                         binding=op.get("binding", ""),
                         polarity=op.get("polarity", ""),
                         evidence_id=op.get("evidence_id", ""))
                applied += 1
            elif kind == "reinforce":
                req = self._items.get(op.get("target_id") or "")
                if req is None:
                    skipped.append(op)
                    continue
                req.strength += 1
                req.updated_at = time.time()
                self._append(req)
                applied += 1
            elif kind == "contradict":
                old = self._items.get(op.get("target_id") or "")
                if old is None:
                    skipped.append(op)
                    continue
                heir = self.add(op["text"], key=op.get("key") or old.key,
                                scope=op.get("scope") or dict(old.scope),
                                source="learned",
                                salience=op.get("salience", 3),
                                supersedes=old.id,
                                bucket=op.get("bucket") or old.bucket,
                                binding=op.get("binding") or old.binding,
                                polarity=op.get("polarity") or old.polarity,
                                evidence_id=op.get("evidence_id", ""))
                if old.status == "active":
                    old.status = "retired"
                old.superseded_by = heir.id
                old.updated_at = time.time()
                self._append(old)
                applied += 1
            elif kind == "retire":
                req = self._items.get(op.get("target_id") or "")
                if req is None:
                    skipped.append(op)
                    continue
                if req.status == "active":
                    req.status = "retired"
                    req.superseded_by = op.get("heir_id")
                    req.updated_at = time.time()
                    self._append(req)
                    # Heir-liveness invariant (2026-07-31): a retire that
                    # carries neither withdrawal evidence nor an heir is
                    # bookkeeping, not user intent — if the victim had
                    # itself replaced an older version, that version pops
                    # back (version-stack semantics). Measured motivation:
                    # a correct "≤11 sentences" cap was superseded by a
                    # mis-extracted rule which then died, leaving the facet
                    # with nothing — the ancestor was the right survivor.
                    # An explicitly withdrawn entry never pops its chain.
                    if (not op.get("withdrawal")
                            and not op.get("heir_id")):
                        # Generalized pop: EVERY entry this victim had
                        # replaced comes back — the contradict ancestor
                        # (superseded_by == victim) and all merge sources
                        # alike. A compound merge dying heirless un-merges
                        # instead of taking its sources to the grave.
                        for anc in self._items.values():
                            if (anc.status == "retired"
                                    and anc.superseded_by == req.id):
                                anc.status = "active"
                                anc.superseded_by = None
                                anc.updated_at = time.time()
                                self._append(anc)
                applied += 1
            elif kind == "merge":
                targets = [self._items.get(t) for t in
                           (op.get("target_ids") or [])]
                if any(t is None for t in targets) or len(targets) < 2:
                    skipped.append(op)
                    continue
                heir = self.add(op["text"],
                                key=op.get("key") or targets[0].key,
                                scope=op.get("scope")
                                or dict(targets[0].scope),
                                source="learned",
                                salience=op.get("salience", 3),
                                supersedes=targets[0].id,
                                bucket=op.get("bucket") or targets[0].bucket,
                                binding=op.get("binding")
                                or targets[0].binding,
                                polarity=op.get("polarity")
                                or targets[0].polarity,
                                evidence_id=op.get("evidence_id", ""))
                # EVERY merge source records its heir — supersedes can only
                # name one ancestor, but the reverse pointer is per-victim;
                # without it targets[1:] looked heirless in forensics and
                # could never pop back if the merged entry later dies.
                for t in targets:
                    if t.status == "active":
                        t.status = "retired"
                    t.superseded_by = heir.id
                    t.updated_at = time.time()
                    self._append(t)
                applied += 1
            else:
                skipped.append(op)
        return {"applied": applied, "skipped": skipped}

    def update(self, req_id: str, *, text: str | None = None,
               status: str | None = None) -> Requirement:
        req = self._items[req_id]
        if text is not None:
            text = text.strip()
            if not text:
                raise ValueError("requirement text is empty")
            req.text = text
        if status is not None:
            if status not in STATUSES:
                raise ValueError(f"unknown status: {status}")
            req.status = status
        req.updated_at = time.time()
        self._append(req)
        return req

    def get(self, req_id: str) -> Requirement:
        return self._items[req_id]

    def list(self, *, include_retired: bool = True) -> list[Requirement]:
        items = sorted(self._items.values(), key=lambda r: r.created_at)
        if include_retired:
            return items
        return [r for r in items if r.status == "active"]

    def active(self) -> list[Requirement]:
        return self.list(include_retired=False)


class EventLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, kind: str, payload: dict) -> dict:
        event = {"kind": kind, "at": time.time(), **payload}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines()
                if l.strip()]
