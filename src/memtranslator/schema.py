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

# Which PART of the request a requirement rewrites (docs/2026-07-26-bucket-
# taxonomy.md). Listed in the order of the decision procedure — the first
# question that fires wins, which is how the taxonomy resolves the overlap
# that made 23% of real requirements ambiguous under parallel definitions.
#   task_goal          the request has no clear verb; the rule supplies it
#   reasoning_policy   the verb is clear; the rule supplies method / criteria
#   deliverables       the rule makes a piece of information mandatory
#   output_contract    same information, different rendering or ordering
#   communication_style register and audience
#   execution_policy   how the agent acts while working (tools, fidelity, channel)
# `domain_criteria` was proposed and DELETED: the entries it attracted were
# content preferences ("only schedule meetings on weekdays"), which anchor §3
# forbids storing and suite L actively penalises.
BUCKETS = ("task_goal", "reasoning_policy", "deliverables",
           "output_contract", "communication_style", "execution_policy")

# How binding the user meant it. Distinct from `strength`, which counts
# evidence — one is how hard the user insists, the other is how sure we are.
BINDINGS = ("hard", "soft", "default", "suggestion")

POLARITIES = ("require", "prefer", "avoid", "prohibit")


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
    bucket: str = ""                    # one of BUCKETS; "" = unclassified
    key: str = ""                       # facet key "facet.attribute"; "" = unclassified
    binding: str = ""                   # one of BINDINGS; "" = unstated
    polarity: str = ""                  # one of POLARITIES; "" = unstated
    evidence_id: str = ""               # shared by rules atomised from one utterance
    scope: dict = field(default_factory=dict)   # {app?, task?, lang?}; {} = global
    kinds: list = field(default_factory=list)   # work kinds governed (kinds.py); [] = untagged, always matches
    strength: int = 1
    salience: int = 3                   # extraction-layer score; manual entries keep 3
    supersedes: str | None = None
    superseded_by: str | None = None    # reverse pointer, set when retired WITH an heir
    source: str = "manual"              # manual | learned
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "kind": self.kind,
            "bucket": self.bucket,
            "key": self.key,
            "binding": self.binding,
            "polarity": self.polarity,
            "evidence_id": self.evidence_id,
            "scope": self.scope,
            "kinds": self.kinds,
            "strength": self.strength,
            "salience": self.salience,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
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
            bucket=d.get("bucket", ""),
            key=d.get("key", ""),
            binding=d.get("binding", ""),
            polarity=d.get("polarity", ""),
            evidence_id=d.get("evidence_id", ""),
            scope=d.get("scope") or {},
            kinds=d.get("kinds") or [],
            strength=d.get("strength", 1),
            salience=d.get("salience", 3),
            supersedes=d.get("supersedes"),
            superseded_by=d.get("superseded_by"),
            source=d.get("source", "manual"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )
