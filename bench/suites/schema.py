"""Bench case schemas + JSONL loaders. Cases live in git; loaders validate
hard so a malformed case fails the run, never silently skews the score."""
from dataclasses import dataclass, field
from pathlib import Path
import json

EXPECT_DECISIONS = ("apply", "noop", "any")


@dataclass(frozen=True)
class Check:
    kind: str          # "mech" | "judge"
    name: str          # mech: registry key; judge: short label
    args: dict = field(default_factory=dict, hash=False, compare=True)

    def __post_init__(self):
        if self.kind not in ("mech", "judge"):
            raise ValueError(f"unknown check kind: {self.kind}")


@dataclass
class TranslateCase:
    id: str
    category: str
    source: str                  # handwritten | generated | prefeval
    requirements: list[str]
    input: str
    expect_decision: str         # apply | noop | any
    must_apply: list[int]        # indices into requirements
    checks: list[Check]


@dataclass
class ExtractionCase:
    id: str
    category: str
    source: str
    existing: list[str]          # requirement texts already in the store
    events: list[dict]           # {"type": "natural", "text": ...} or
                                 # {"type": "edited_diff", "raw":, "polished":,
                                 #  "final":, "applied": [index into existing]}
    expect_ops: list[dict]       # {"kind": "new|reinforce|contradict|deduplicate",
                                 #  "target": int|None (index into existing),
                                 #  "targets": [int, ...] for reinforce any-of,
                                 #  "gist": "..."}; [] means must-not-extract
    # Optional CASE-consolidator fixture. When set, the harness feeds this
    # candidate (+ retrieved store memories) to reconcile(), not extract().
    candidate: dict | None = None


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]


def _check_unique_ids(cases):
    seen = set()
    for c in cases:
        if c.id in seen:
            raise ValueError(f"duplicate case id: {c.id}")
        seen.add(c.id)
    return cases


def load_translate_cases(path: Path) -> list[TranslateCase]:
    cases = []
    for d in _rows(path):
        if d["expect_decision"] not in EXPECT_DECISIONS:
            raise ValueError(
                f"{d['id']}: bad expect_decision {d['expect_decision']}")
        if any(i >= len(d["requirements"]) for i in d["must_apply"]):
            raise ValueError(f"{d['id']}: must_apply index out of range")
        cases.append(TranslateCase(
            id=d["id"], category=d["category"], source=d["source"],
            requirements=list(d["requirements"]), input=d["input"],
            expect_decision=d["expect_decision"],
            must_apply=list(d["must_apply"]),
            checks=[Check(**c) for c in d["checks"]]))
    return _check_unique_ids(cases)


# "update" is route B's only constructive op: it edits the attributed entry
# in place rather than minting an heir, so it is a distinct expectation from
# route A's "contradict".
OP_KINDS = ("new", "reinforce", "contradict", "retire", "merge", "update",
            "deduplicate")


def load_extraction_cases(path: Path) -> list[ExtractionCase]:
    cases = []
    for d in _rows(path):
        for op in d["expect_ops"]:
            if op["kind"] not in OP_KINDS:
                raise ValueError(f"{d['id']}: bad op kind {op['kind']}")
            if op["kind"] in ("retire", "update") and op.get("target") is None \
                    and not op.get("targets"):
                raise ValueError(f"{d['id']}: {op['kind']} op needs a target")
            if op["kind"] == "reinforce" and op.get("target") is None \
                    and not op.get("targets"):
                raise ValueError(f"{d['id']}: reinforce op needs target(s)")
            if op["kind"] in ("merge", "deduplicate") \
                    and len(op.get("targets") or []) < 2:
                raise ValueError(
                    f"{d['id']}: {op['kind']} op needs ≥2 targets")
            for i in op.get("targets") or []:
                if not isinstance(i, int) or not (0 <= i < len(d["existing"])):
                    raise ValueError(
                        f"{d['id']}: expect target index out of range: {i!r}")
        for e in d["events"]:
            # a route-B case claims which stored entries the rewrite wove in;
            # an out-of-range index would silently grade the route against a
            # constraint the store never held
            for i in e.get("applied") or []:
                if not isinstance(i, int) or not (0 <= i < len(d["existing"])):
                    raise ValueError(f"{d['id']}: applied index out of range: {i!r}")
        candidate = d.get("candidate")
        if candidate is not None and not isinstance(candidate, dict):
            raise ValueError(f"{d['id']}: candidate must be an object")
        if not d["events"] and candidate is None and d.get("expect_ops"):
            # Store-tidy merge used to live here; live product cases without
            # events must name a consolidator candidate instead.
            if d["category"] == "dedup":
                raise ValueError(
                    f"{d['id']}: dedup cases need a consolidator candidate")
        cases.append(ExtractionCase(
            id=d["id"], category=d["category"], source=d["source"],
            existing=list(d["existing"]), events=list(d["events"]),
            expect_ops=list(d["expect_ops"]),
            candidate=candidate))
    return _check_unique_ids(cases)
