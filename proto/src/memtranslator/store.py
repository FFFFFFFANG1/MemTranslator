"""Append-only memory store per docs/memory-design.md §2.2–2.3, §3.4.

Physical format: one JSON snapshot of an entry per line; a mutation appends a
new full snapshot of the same mid and the loader keeps the last one. The file
is never rewritten, so every historical version stays inspectable and a torn
final line (crash mid-write) is detected and skipped on load.

Quarantine: raw LLM outputs that failed parsing/validation are appended to a
sidecar file for later audit instead of being silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import MemoryEntry, Provenance, now_iso


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.quarantine_path = self.path.with_suffix(".quarantine.jsonl")
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                entry = MemoryEntry.from_dict(d)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue  # torn or foreign line; later snapshots are self-contained
            self._entries[entry.mid] = entry

    def _append(self, entry: MemoryEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        self._entries[entry.mid] = entry

    # --- write ops (the only mutations that exist; no free UPDATE/DELETE) ---

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        self._append(entry)
        return entry

    def reinforce(self, mid: str, provenance: Provenance) -> MemoryEntry:
        entry = self._entries[mid]
        entry.strength += 1
        entry.provenance.append(provenance)
        entry.updated_at = now_iso()
        self._append(entry)
        return entry

    def supersede(self, old_mid: str, new_entry: MemoryEntry) -> MemoryEntry:
        old = self._entries[old_mid]
        new_entry.supersedes = list(dict.fromkeys(new_entry.supersedes + [old_mid]))
        self._append(new_entry)
        old.status = "superseded"
        old.superseded_by = new_entry.mid
        old.updated_at = now_iso()
        self._append(old)
        return new_entry

    def retire(self, mid: str) -> MemoryEntry:
        entry = self._entries[mid]
        entry.status = "retired"
        entry.updated_at = now_iso()
        self._append(entry)
        return entry

    def mark_applied(self, mids: list[str]) -> None:
        ts = now_iso()
        for mid in mids:
            if mid in self._entries:
                entry = self._entries[mid]
                entry.last_applied_at = ts
                self._append(entry)

    def quarantine(self, raw: str, stage: str, reason: str) -> None:
        self.quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with self.quarantine_path.open("a") as f:
            f.write(json.dumps({"at": now_iso(), "stage": stage, "reason": reason, "raw": raw},
                               ensure_ascii=False) + "\n")

    def seed_defaults(self, entries: list[MemoryEntry]) -> int:
        """Write factory-default fallback entries once (design §3.3 default profile).

        Idempotent: a store that already contains any source=="default" entry
        (whatever its status — a retired default must stay retired) is left
        untouched. Returns how many entries were written."""
        if any(e.source == "default" for e in self._entries.values()):
            return 0
        for entry in entries:
            entry.source = "default"
            self._append(entry)
        return len(entries)

    # --- read ---

    def get(self, mid: str) -> MemoryEntry | None:
        return self._entries.get(mid)

    def all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def active(self) -> list[MemoryEntry]:
        return [e for e in self._entries.values() if e.is_live()]

    def recall(self, query: str, k: int = 8) -> list[MemoryEntry]:
        """Read-path recall (design §3.3), zero LLM calls.

        Prototype scale is 10^1–10^2 entries, so this is keyword overlap +
        strength + recency over all live entries; an embedding index slots in
        here later without touching callers.
        """
        live = self.active()
        q = set(query.lower().split())

        def score(e: MemoryEntry) -> tuple:
            kw_hits = sum(1 for w in e.scope.keywords if w.lower() in q or any(w.lower() in t for t in q))
            # Learned entries outrank factory defaults at equal keyword relevance.
            return (kw_hits, e.source != "default", e.strength, e.updated_at)

        return sorted(live, key=score, reverse=True)[:k]
