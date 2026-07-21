"""Data structures per docs/memory-design.md §2.

Plain dataclasses + dict round-tripping; no pydantic so the core stays
dependency-free. Unknown keys in stored JSON are dropped on load, which is
the forward-compatibility we need at prototype stage.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

SCHEMA_VERSION = 1

SIGNALS = ("next_turn_feedback", "repeated_requirement", "explicit_instruction")
STATUSES = ("active", "superseded", "retired")
OPS = ("ADD", "REINFORCE", "SUPERSEDE", "DROP")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_mid() -> str:
    return f"m-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6]}"


def norm_ws(text: str) -> str:
    """Strip all whitespace so verbatim-quote checks survive reflowing.

    Deleting (not collapsing) whitespace keeps CJK text matchable when a
    quote gains a line break at a position where the original had no space.
    """
    return re.sub(r"\s+", "", text)


@dataclass
class Provenance:
    session_id: str
    turn: int
    signal: str
    quote: str
    at: str = field(default_factory=now_iso)


@dataclass
class Scope:
    condition: str
    task_type: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class MemoryEntry:
    requirement: str
    scope: Scope
    polarity: str = "do"
    mid: str = field(default_factory=new_mid)
    strength: int = 1
    status: str = "active"
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    provenance: list[Provenance] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    last_applied_at: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(
            requirement=d["requirement"],
            scope=Scope(**{k: d["scope"][k] for k in ("condition", "task_type", "keywords") if k in d["scope"]}),
            polarity=d.get("polarity", "do"),
            mid=d["mid"],
            strength=d.get("strength", 1),
            status=d.get("status", "active"),
            supersedes=d.get("supersedes", []),
            superseded_by=d.get("superseded_by"),
            provenance=[Provenance(**{k: p[k] for k in ("session_id", "turn", "signal", "quote", "at") if k in p})
                        for p in d.get("provenance", [])],
            created_at=d.get("created_at", now_iso()),
            updated_at=d.get("updated_at", now_iso()),
            last_applied_at=d.get("last_applied_at"),
            expires_at=d.get("expires_at"),
        )

    def is_live(self, at: str | None = None) -> bool:
        if self.status != "active":
            return False
        if self.expires_at is not None:
            return (at or now_iso()) < self.expires_at
        return True


@dataclass
class Candidate:
    """One extraction-call output item (write path Call 1)."""

    requirement: str
    scope_condition: str
    quote: str
    signal: str
    polarity: str = "do"
    task_type: str = ""
    keywords: list[str] = field(default_factory=list)
    turn: int = -1
    expires_hint: str | None = None

    def to_entry(self, session_id: str) -> MemoryEntry:
        return MemoryEntry(
            requirement=self.requirement,
            polarity=self.polarity,
            scope=Scope(condition=self.scope_condition, task_type=self.task_type, keywords=self.keywords),
            provenance=[Provenance(session_id=session_id, turn=self.turn, signal=self.signal, quote=self.quote)],
            expires_at=self.expires_hint,
        )


@dataclass
class ConsolidationOp:
    """One consolidation-call output item (write path Call 2)."""

    candidate_idx: int
    op: str
    target_mid: str | None = None
    merged_requirement: str | None = None
    reason: str | None = None
