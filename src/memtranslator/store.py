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

from memtranslator.schema import STATUSES, Requirement


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

    def add(self, text: str) -> Requirement:
        text = text.strip()
        if not text:
            raise ValueError("requirement text is empty")
        req = Requirement(text=text)
        self._items[req.id] = req
        self._append(req)
        return req

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
