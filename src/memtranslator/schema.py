"""Requirement: the only thing we store (anchor §2.1 — requirement-only memory).

A requirement constrains HOW tasks are executed or delivered ("emails under
120 words", "code without explanations"), never WHAT to recommend. v0 was the
oracle condition (hand-entered); v1 adds the learned fields below — every new
field defaults so v0 records load unchanged (design 2026-07-24 §3).

kind "style_rule" entries live in the same store/state machine but constrain
how the REWRITE itself is phrased; they never join scope recall and are only
injected when assembling the translator prompt (signal proposal §2-B2).
"""
import time
import uuid
from dataclasses import dataclass, field

STATUSES = ("active", "retired")
KINDS = ("requirement", "style_rule")


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


@dataclass
class Requirement:
    text: str
    id: str = field(default_factory=_new_id)
    status: str = "active"
    kind: str = "requirement"
    key: str = ""                       # facet key "facet.attribute"; "" = unclassified
    scope: dict = field(default_factory=dict)   # {app?, task?, lang?}; {} = global
    strength: int = 1
    salience: int = 3                   # extraction-layer score; manual entries keep 3
    supersedes: str | None = None
    source: str = "manual"              # manual | learned
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "kind": self.kind,
            "key": self.key,
            "scope": self.scope,
            "strength": self.strength,
            "salience": self.salience,
            "supersedes": self.supersedes,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Requirement":
        return cls(
            text=d["text"],
            id=d["id"],
            status=d.get("status", "active"),
            kind=d.get("kind", "requirement"),
            key=d.get("key", ""),
            scope=d.get("scope") or {},
            strength=d.get("strength", 1),
            salience=d.get("salience", 3),
            supersedes=d.get("supersedes"),
            source=d.get("source", "manual"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )
