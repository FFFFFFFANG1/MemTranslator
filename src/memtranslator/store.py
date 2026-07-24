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

from memtranslator.schema import KINDS, STATUSES, Requirement

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
            salience: int = 3, supersedes: str | None = None) -> Requirement:
        text = text.strip()
        if not text:
            raise ValueError("requirement text is empty")
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind}")
        req = Requirement(text=text, kind=kind, key=key, scope=scope or {},
                          source=source, salience=salience,
                          supersedes=supersedes)
        self._items[req.id] = req
        self._append(req)
        return req

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
                         salience=op.get("salience", 3))
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
                if old.status == "active":
                    old.status = "retired"
                    old.updated_at = time.time()
                    self._append(old)
                self.add(op["text"], key=op.get("key") or old.key,
                         scope=op.get("scope") or dict(old.scope),
                         source="learned", salience=op.get("salience", 3),
                         supersedes=old.id)
                applied += 1
            elif kind == "retire":
                req = self._items.get(op.get("target_id") or "")
                if req is None:
                    skipped.append(op)
                    continue
                if req.status == "active":
                    req.status = "retired"
                    req.updated_at = time.time()
                    self._append(req)
                applied += 1
            elif kind == "merge":
                targets = [self._items.get(t) for t in
                           (op.get("target_ids") or [])]
                if any(t is None for t in targets) or len(targets) < 2:
                    skipped.append(op)
                    continue
                for t in targets:
                    if t.status == "active":
                        t.status = "retired"
                        t.updated_at = time.time()
                        self._append(t)
                self.add(op["text"], key=op.get("key") or targets[0].key,
                         scope=op.get("scope") or dict(targets[0].scope),
                         source="learned", salience=op.get("salience", 3),
                         supersedes=targets[0].id)
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
