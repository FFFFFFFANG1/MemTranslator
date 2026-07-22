"""Requirement: the only thing we store (anchor §2.1 — requirement-only memory).

A requirement constrains HOW tasks are executed or delivered ("emails under
120 words", "code without explanations"), never WHAT to recommend. v0 is the
oracle condition: requirements are entered by hand; extraction is v1.
"""
import time
import uuid
from dataclasses import dataclass, field

STATUSES = ("active", "retired")


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


@dataclass
class Requirement:
    text: str
    id: str = field(default_factory=_new_id)
    status: str = "active"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Requirement":
        return cls(
            text=d["text"],
            id=d["id"],
            status=d.get("status", "active"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )
