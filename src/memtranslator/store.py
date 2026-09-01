"""Append-only JSONL store for requirements, plus an event log.

Every mutation appends the full record; the latest record per id wins on
load. Nothing is ever rewritten in place — history stays in the file. The
event log records what the shell observes (translate calls, sends and their
edit diffs); v0 records, v1 learns from it (anchor §4 编辑回流).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from memtranslator.schema import (BUCKETS, KINDS, STATUSES, Requirement)
from memtranslator.scopes import migrate_genre_from_scope, normalize_kind, normalize_scope


AUTO_RETIRE_AT = -2          # strength ≤ -2 → implicit retire (design §3)
B_FEEDBACK_RETIRE_AT = -2    # two route-B delete judgements retire an entry


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._items: dict[str, Requirement] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                req = Requirement.from_dict(json.loads(line))
                migrate_genre_from_scope(req)
                self._items[req.id] = req
        self._prepare_indexes(list(self._items.values()))

    @staticmethod
    def _prepare_indexes(requirements: list[Requirement]) -> None:
        """Warm retrieval caches without ever making storage depend on them."""
        try:
            from memtranslator.retrieval import prepare_requirements
            prepare_requirements(requirements)
        except Exception:
            # Retrieval degrades to uncached BM25; an optional local embedding
            # backend must never make an append-only Store mutation fail.
            pass

    def _append(self, req: Requirement) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(req.to_dict(), ensure_ascii=False) + "\n")
        self._prepare_indexes([req])

    def add(self, text: str, *, kind: str = "requirement", key: str = "",
            scope: dict | None = None, source: str = "manual",
            applies_when: str = "",
            scope_mode: str = "",
            confidence: int | None = None, supersedes: str | None = None,
            bucket: str = "", evidence_id: str = "",
            kinds: list | None = None, sources: list | None = None,
            # Legacy salience accepted then mapped into confidence.
            salience: int | None = None) -> Requirement:
        text = text.strip()
        if not text:
            raise ValueError("requirement text is empty")
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind}")
        kinds = kinds or []
        if not isinstance(kinds, list):
            raise ValueError(f"unknown work kinds: {kinds!r}")
        normalised = []
        for value in kinds:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"unknown work kinds: {kinds!r}")
            kind_value = normalize_kind(value)
            if not kind_value:
                raise ValueError(f"unknown work kinds: {kinds!r}")
            normalised.append(kind_value)
        kinds = list(dict.fromkeys(normalised))
        scope = normalize_scope(scope)
        if bucket and bucket not in BUCKETS:
            raise ValueError(f"unknown bucket: {bucket}")
        if confidence is None:
            if isinstance(salience, int):
                confidence = max(0, min(10, salience * 2))
            else:
                confidence = 0
        elif not isinstance(confidence, int) or not 0 <= confidence <= 10:
            confidence = 0
        source_texts = []
        for entry in sources or []:
            if isinstance(entry, str) and entry.strip():
                text_entry = entry.strip()
                if text_entry not in source_texts:
                    source_texts.append(text_entry)
        req = Requirement(text=text, kind=kind, key=key, scope=scope,
                          applies_when=applies_when,
                          scope_mode=scope_mode,
                          kinds=kinds,
                          source=source, confidence=confidence,
                          supersedes=supersedes, bucket=bucket,
                          evidence_id=evidence_id, sources=source_texts)
        migrate_genre_from_scope(req)
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

    def insert_if_absent(self, req: Requirement) -> bool:
        """Append a caller-owned deterministic record exactly once."""
        if req.id in self._items:
            return False
        migrate_genre_from_scope(req)
        self._items[req.id] = req
        self._append(req)
        return True

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
                         applies_when=op.get("applies_when") or "",
                         scope_mode=op.get("scope_mode", ""),
                         confidence=op.get("confidence"),
                         bucket=op.get("bucket", ""),
                         evidence_id=op.get("evidence_id", ""),
                         kinds=op.get("kinds") or [],
                         sources=op.get("sources") or [],
                         salience=op.get("salience"))
                applied += 1
            elif kind == "reinforce":
                req = self._items.get(op.get("target_id") or "")
                if req is None:
                    skipped.append(op)
                    continue
                req.strength += 1
                for entry in op.get("sources") or []:
                    if isinstance(entry, str) and entry.strip():
                        text_entry = entry.strip()
                        if text_entry not in req.sources:
                            req.sources.append(text_entry)
                conf = op.get("confidence")
                if isinstance(conf, int) and 0 <= conf <= 10:
                    req.confidence = max(req.confidence, conf)
                req.updated_at = time.time()
                self._append(req)
                applied += 1
            elif kind == "contradict":
                old = self._items.get(op.get("target_id") or "")
                if old is None:
                    skipped.append(op)
                    continue
                heir = self.add(op["text"], key=op.get("key") or old.key,
                                scope=(op["scope"] if "scope" in op
                                       else dict(old.scope)),
                                scope_mode=(op["scope_mode"]
                                            if "scope_mode" in op
                                            else old.scope_mode),
                                applies_when=(op["applies_when"]
                                              if "applies_when" in op
                                              else old.applies_when),
                                source="learned",
                                confidence=op.get("confidence"),
                                supersedes=old.id,
                                bucket=op.get("bucket") or old.bucket,
                                evidence_id=op.get("evidence_id", ""),
                                kinds=(op["kinds"] if "kinds" in op
                                       else list(old.kinds)),
                                sources=op.get("sources") or [],
                                salience=op.get("salience"))
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
                    for entry in op.get("sources") or []:
                        if isinstance(entry, str) and entry.strip():
                            text_entry = entry.strip()
                            if text_entry not in req.sources:
                                req.sources.append(text_entry)
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
                    import os as _os
                    if (not op.get("withdrawal")
                            and not op.get("heir_id")
                            and "pop" not in _os.environ.get("MT_ABLATE", "")):
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
                                scope=(op["scope"] if "scope" in op
                                       else dict(targets[0].scope)),
                                scope_mode=(op["scope_mode"]
                                            if "scope_mode" in op
                                            else targets[0].scope_mode),
                                applies_when=(op["applies_when"]
                                              if "applies_when" in op
                                              else targets[0].applies_when),
                                source="learned",
                                confidence=op.get("confidence"),
                                supersedes=targets[0].id,
                                bucket=op.get("bucket") or targets[0].bucket,
                                evidence_id=op.get("evidence_id", ""),
                                kinds=(op["kinds"] if "kinds" in op
                                       else list(targets[0].kinds)),
                                sources=op.get("sources") or [],
                                salience=op.get("salience"))
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

    def apply_feedback_ops(self, ops: list[dict]) -> dict:
        """Apply route-B operations, which never travel through `apply_ops`.

        Route B judges the exact entries the rewrite used, so an update
        edits that entry in place rather than minting an heir: there is no
        new rule here, only the same rule as the user just corrected it.
        (The JSONL keeps the old version — every mutation still appends.)
        A retire is negative evidence, not a destructive command: it takes
        two such judgements, because one edit can drop a constraint for
        reasons that have nothing to do with wanting the rule gone.
        """
        applied, skipped, retired = 0, [], 0
        for op in ops:
            req = self._items.get(op.get("target_id") or "")
            if req is None or req.status != "active":
                skipped.append(op)
                continue
            kind = op.get("kind")
            if kind == "update":
                text = (op.get("text") or "").strip()
                if not text:
                    skipped.append(op)
                    continue
                req.text = text
                req.feedback_score = 0
                req.updated_at = time.time()
                self._append(req)
                applied += 1
            elif kind == "retire":
                req.feedback_score -= 1
                if req.feedback_score <= B_FEEDBACK_RETIRE_AT:
                    req.status = "retired"
                    retired += 1
                req.updated_at = time.time()
                self._append(req)
                applied += 1
            else:
                skipped.append(op)
        return {"applied": applied, "skipped": skipped, "retired": retired}

    def update(self, req_id: str, *, text: str | None = None,
               status: str | None = None, scope: dict | None = None,
               applies_when: str | None = None,
               scope_mode: str | None = None,
               kinds: list | None = None,
               bucket: str | None = None) -> Requirement:
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
        if kinds is not None:
            if not isinstance(kinds, list):
                raise ValueError(f"unknown work kinds: {kinds!r}")
            normalised = []
            for value in kinds:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"unknown work kinds: {kinds!r}")
                kind = normalize_kind(value)
                if not kind:
                    raise ValueError(f"unknown work kinds: {kinds!r}")
                normalised.append(kind)
            req.kinds = list(dict.fromkeys(normalised))
        if scope is not None:
            req.scope = normalize_scope(scope)
        if applies_when is not None:
            req.applies_when = applies_when
        if scope_mode is not None:
            req.scope_mode = scope_mode
        if bucket is not None:
            bucket = bucket.strip()
            if bucket and bucket not in BUCKETS:
                raise ValueError(f"unknown bucket: {bucket}")
            req.bucket = bucket
        migrate_genre_from_scope(req)
        req.normalize_applicability()
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
        self._lock = threading.Lock()

    def append(self, kind: str, payload: dict) -> dict:
        event = {"kind": kind, "at": time.time(), **payload}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read_all(self) -> list[dict]:
        with self._lock:
            if not self.path.exists():
                return []
            return [json.loads(l) for l in self.path.read_text().splitlines()
                    if l.strip()]
