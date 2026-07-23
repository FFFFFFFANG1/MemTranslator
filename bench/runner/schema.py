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
                                 # {"type": "edited_diff", "raw":, "polished":, "final":}
    expect_ops: list[dict]       # {"kind": "new|reinforce|contradict",
                                 #  "target": int|None (index into existing),
                                 #  "gist": "..."}; [] means must-not-extract


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


def load_extraction_cases(path: Path) -> list[ExtractionCase]:
    cases = []
    for d in _rows(path):
        for op in d["expect_ops"]:
            if op["kind"] not in ("new", "reinforce", "contradict"):
                raise ValueError(f"{d['id']}: bad op kind {op['kind']}")
        cases.append(ExtractionCase(
            id=d["id"], category=d["category"], source=d["source"],
            existing=list(d["existing"]), events=list(d["events"]),
            expect_ops=list(d["expect_ops"])))
    return _check_unique_ids(cases)
