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

# Kept for the archived GROUPS tidy parser (parse_ops) only; live A/B paths
# do not admit polarity.
POLARITIES = ("require", "prefer", "avoid", "prohibit")

# Seed work-kind slugs for write-time inventory and read-path markers.
# Product kinds are open: extractors may invent new English slugs when none
# of the known inventory fits. Admission accepts any non-empty normalised
# slug (plus WORK_KIND_ANY); this tuple is the seed, not a closed enum.
WORK_KINDS = ("email", "report", "postmortem", "code")
WORK_KIND_ANY = "any"
SCOPE_MODES = ("global", "scoped")


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
    evidence_id: str = ""               # legacy; unused by candidate-first A path
    # Legacy free key:value narrowness. New learned records use the short
    # natural-language ``applies_when`` field instead; this remains readable
    # so existing append-only stores do not require an in-place migration.
    scope: dict = field(default_factory=dict)
    # Short applicability condition, e.g. "when abbreviations appear".
    # Empty means work_kinds alone determine applicability.
    applies_when: str = ""
    # Explicit injection declaration. ``global`` is reserved for a rule that
    # every agent output must obey: broad work kind and no condition. Every
    # work-specific or conditional rule is ``scoped`` and goes through
    # retrieval. Empty remains accepted for legacy/manual constructors.
    scope_mode: str = ""
    # Open work-kind slugs this rule governs; [] = untagged legacy/scoped.
    kinds: list = field(default_factory=list)
    strength: int = 1
    # Route-B deletion evidence, deliberately separate from strength: an
    # accepted patch does not reinforce memory, while two direct removals do
    # retire it. Zero is neutral; each confirmed removal subtracts one.
    feedback_score: int = 0
    # Display-only extractor score 0-10. Never gates admission, retrieval,
    # or lifecycle; translator may surface it for the user.
    confidence: int = 0
    # Original user spans that produced / reinforced this entry. Filled by
    # mechanical resolution of extractor source ids; never shown to LLMs.
    sources: list = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: str | None = None    # reverse pointer, set when retired WITH an heir
    source: str = "manual"              # manual | learned
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.normalize_applicability()

    def normalize_applicability(self) -> None:
        """Normalise mutable applicability metadata after create or edit."""
        if not isinstance(self.applies_when, str):
            self.applies_when = ""
        else:
            self.applies_when = " ".join(self.applies_when.split())
        explicit_all = any(
            str(kind).strip().lower() in {"all", WORK_KIND_ANY}
            for kind in self.kinds)
        conditional = bool(self.scope or self.applies_when)
        if self.scope_mode not in SCOPE_MODES:
            # Always-on is opt-in. Missing metadata on manual and legacy
            # records must never silently promote them into the global lane.
            self.scope_mode = "scoped"
        elif self.scope_mode == "global" and (
                not explicit_all or conditional):
            self.scope_mode = "scoped"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "kind": self.kind,
            "bucket": self.bucket,
            "key": self.key,
            "evidence_id": self.evidence_id,
            "scope": self.scope,
            "applies_when": self.applies_when,
            "scope_mode": self.scope_mode,
            "kinds": self.kinds,
            "strength": self.strength,
            "feedback_score": self.feedback_score,
            "confidence": self.confidence,
            "sources": list(self.sources),
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Requirement":
        confidence = d.get("confidence")
        if not isinstance(confidence, int):
            # Legacy salience was 1-5; map into the 0-10 display scale.
            legacy = d.get("salience", 0)
            confidence = legacy * 2 if isinstance(legacy, int) else 0
        return cls(
            text=d["text"],
            id=d["id"],
            status=d.get("status", "active"),
            kind=d.get("kind", "requirement"),
            bucket=d.get("bucket", ""),
            key=d.get("key", ""),
            evidence_id=d.get("evidence_id", ""),
            scope=d.get("scope") or {},
            applies_when=d.get("applies_when") or "",
            scope_mode=d.get("scope_mode", ""),
            kinds=d.get("kinds") or [],
            strength=d.get("strength", 1),
            feedback_score=d.get("feedback_score", 0),
            confidence=max(0, min(10, confidence)),
            sources=[s for s in (d.get("sources") or [])
                     if isinstance(s, str) and s.strip()],
            supersedes=d.get("supersedes"),
            superseded_by=d.get("superseded_by"),
            source=d.get("source", "manual"),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
        )
