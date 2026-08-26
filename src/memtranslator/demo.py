"""Curated, deterministic memory records for the local product demo."""
from __future__ import annotations

import time

from memtranslator.schema import Requirement
from memtranslator.store import Store


DEMO_REQUIREMENTS = (
    {"id": "demo-rule-01",
     "text": "Keep the final answer concise and lead with the outcome.",
     "kinds": ["any"], "scope_mode": "global", "bucket": "communication_style",
     "key": "style.conciseness", "confidence": 9, "strength": 4},
    {"id": "demo-rule-02",
     "text": "Keep client emails under 120 words and end with one clear next step.",
     "kinds": ["email"], "applies_when": "when writing to an external client",
     "bucket": "output_contract", "key": "length.maximum", "confidence": 9},
    {"id": "demo-rule-03",
     "text": "Start weekly reports with a three-bullet executive summary.",
     "kinds": ["report"], "scope": {"audience": "leadership"},
     "bucket": "output_contract", "key": "structure.opening", "confidence": 8},
    {"id": "demo-rule-04",
     "text": "Include focused tests for changed behavior, including one failure case.",
     "kinds": ["code"], "applies_when": "when implementing production changes",
     "bucket": "execution_policy", "key": "verification.tests", "confidence": 9},
    {"id": "demo-rule-05", "text": "Cite primary sources next to factual claims.",
     "kinds": ["research", "report"], "applies_when": "when external facts are used",
     "bucket": "deliverables", "key": "evidence.citations", "confidence": 8},
    {"id": "demo-rule-06",
     "text": "List decisions, owners, and deadlines as separate action items.",
     "kinds": ["meeting-summary"], "scope": {"team": "project"},
     "bucket": "deliverables", "key": "actions.required", "confidence": 8},
    {"id": "demo-rule-07",
     "text": "Use one message per slide and keep supporting detail in speaker notes.",
     "kinds": ["presentation"], "applies_when": "when presenting to executives",
     "bucket": "output_contract", "key": "slides.density", "confidence": 7},
    {"id": "demo-rule-08",
     "text": "State assumptions before conclusions and call out material limitations.",
     "kinds": ["data-analysis"], "scope": {"decision_impact": "high"},
     "bucket": "reasoning_policy", "key": "analysis.assumptions", "confidence": 9},
    {"id": "demo-rule-09", "text": "Use a playful, high-energy tone in product copy.",
     "kinds": ["product-copy"], "applies_when": "for launch campaigns",
     "bucket": "communication_style", "key": "tone.product",
     "status": "retired", "superseded_by": "demo-rule-10", "strength": -1,
     "confidence": 5},
    {"id": "demo-rule-10",
     "text": "Use a calm, direct tone in product copy and avoid hype.",
     "kinds": ["product-copy"], "applies_when": "for launch campaigns",
     "bucket": "communication_style", "key": "tone.product",
     "supersedes": "demo-rule-09", "strength": 3, "confidence": 9},
)


def seed_demo_requirements(store: Store) -> dict[str, int]:
    """Insert the ten demo records once, preserving user edits thereafter."""
    now = time.time()
    added = 0
    for offset, spec in enumerate(DEMO_REQUIREMENTS):
        values = dict(spec)
        values.setdefault("scope_mode", "scoped")
        values.setdefault("scope", {})
        values.setdefault("source", "manual")
        values.setdefault("created_at", now + offset / 1000)
        values.setdefault("updated_at", now + offset / 1000)
        if store.insert_if_absent(Requirement(**values)):
            added += 1
    return {"added": added, "total": len(DEMO_REQUIREMENTS)}
