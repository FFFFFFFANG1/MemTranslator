"""Coordinate annotation: the ONLY thing the LLM decides about a constraint.
Everything relational (edges, validity, roles) is computed from these coords
by bench.graph — so an annotation error is a coords error, localized and
re-runnable, never a hand-written edge.

Self-consistency: 3 votes at temperature 0.6, majority per FIELD, per-field
confidence = agreement. Mechanical fields (value from a threshold/order
skeleton) are filled by code and not put to a vote — the LLM only answers
what code cannot.

The bucket question follows the ordered decision procedure of
docs/2026-07-26-bucket-taxonomy.md §1: first question that fires wins.
"""
import json
from collections import Counter

from bench.gen.flash import flash_json
from bench.graph.schema import (ANY, BUCKETS, ENUM_DOMAINS, KEY_REGISTRY,
                                SCOPE_VOCAB)

_KEYS = "\n".join(f"- {k}" for k in KEY_REGISTRY)
_SCOPE_LINES = "\n".join(
    f'- {d}: one of {list(vals)} or "ANY"' for d, vals in SCOPE_VOCAB.items())

SYSTEM = f"""You annotate one delivery-requirement proposition with coordinates.
Answer exactly one JSON object:
{{"bucket": "...", "key": "...", "binding": "hard"|"soft"|"default"|"suggestion",
 "scope": {{"app": "...", "task": "...", "code_lang": "...", "nat_lang": "..."}},
 "enum": {{"domain": "...", "val": "..."}} | null}}

bucket — apply these questions IN ORDER, first hit wins:
1. The request would have no clear task verb without this rule → "task_goal"
2. The rule supplies method/criteria for HOW to think or decide → "reasoning_policy"
3. The rule makes a piece of information MANDATORY in the deliverable → "deliverables"
4. Same information, different rendering/ordering/format → "output_contract"
5. Register and audience → "communication_style"
6. How the agent acts while working (tools, confirmation, fidelity, channel) → "execution_policy"

OWNER-CALIBRATED boundary between 3 and 4 (2026-07-28, binding): ask "does
complying ADD A SEPARABLE CONTENT BLOCK, or does it re-render/mark content
already present?" A demanded NEW block that would not otherwise exist
(explanatory comments, a table of contents, a summary section) → question 3
fires, "deliverables". A demanded marker or property ON information already
present (units attached to numbers, a footer flagging what the diff already
shows, capitalization, punctuation) → question 3 does NOT fire, fall through
to question 4, "output_contract".

key — pick the closest from this registry (never invent):
{_KEYS}

scope — every dimension EXPLICIT; "ANY" when the rule is not limited to that
dimension.
OWNER-CALIBRATED rule (2026-07-28, binding): a concrete value ONLY when the
rule itself STATES that qualifier ("python comments in English" →
code_lang=python; "numbers in reports need units" → task=report). No stated
qualifier → ANY on every dimension. NEVER infer a scope the user did not say.
A qualifier these dimensions cannot express (a specific recipient, a specific
document) stays in the rule TEXT at instance level and all dimensions stay
ANY — do not promote an instance to its class.
{_SCOPE_LINES}

enum — only when the demand is a choice from one of these closed domains,
else null: {json.dumps({k: list(v) for k, v in ENUM_DOMAINS.items()})}
"""


def _mechanical_value(sk: dict) -> dict | None:
    th = sk.get("threshold")
    if th and isinstance(th.get("value"), (int, float)):
        cmp_ = {"require": "max", "prefer": "max"}.get(
            sk.get("polarity", "require"), "max")
        act = str(sk.get("act") or "").lower()
        if any(w in act for w in ("least", "minimum", "min")):
            cmp_ = "min"
        elif "exact" in act:
            cmp_ = "exact"
        return {"type": "numeric", "num": float(th["value"]),
                "unit": th.get("unit") or "", "cmp": cmp_}
    order = sk.get("order")
    if order and len(order) == 2 and all(isinstance(x, str) and x
                                         for x in order):
        return {"type": "ordering", "before": order[0], "after": order[1]}
    return None


def _vote(sk: dict) -> dict | None:
    user = (f"Proposition:\n{json.dumps(sk, ensure_ascii=False)}\n\nJSON:")
    return flash_json(SYSTEM, user, max_tokens=400, temperature=0.6)


def annotate(sk: dict, votes: int = 3) -> dict:
    """skeleton → coords dict + per-field confidence. Invalid vocabulary in a
    vote invalidates that vote's field, not the whole annotation."""
    ballots = [v for v in (_vote(sk) for _ in range(votes))
               if isinstance(v, dict)]

    def majority(field, valid, default):
        vals = []
        for b in ballots:
            v = b.get(field)
            if field == "scope":
                continue
            if v in valid:
                vals.append(v)
        if not vals:
            return default, 0.0
        top, n = Counter(vals).most_common(1)[0]
        return top, n / max(1, len(ballots))

    bucket, c_bucket = majority("bucket", BUCKETS, "output_contract")
    key, c_key = majority("key", KEY_REGISTRY, "")
    binding, c_bind = majority("binding",
                               ("hard", "soft", "default", "suggestion"),
                               "hard")

    scope, c_scope = {}, []
    for d, vocab in SCOPE_VOCAB.items():
        vals = []
        for b in ballots:
            v = (b.get("scope") or {}).get(d)
            if v == ANY or v in vocab:
                vals.append(v)
        if vals:
            top, n = Counter(vals).most_common(1)[0]
            scope[d] = top
            c_scope.append(n / len(ballots))
        else:
            scope[d] = ANY
            c_scope.append(0.0)

    value = _mechanical_value(sk)
    if value is None:
        enums = []
        for b in ballots:
            e = b.get("enum")
            if isinstance(e, dict) and e.get("domain") in ENUM_DOMAINS \
                    and e.get("val") in ENUM_DOMAINS[e["domain"]]:
                enums.append((e["domain"], e["val"]))
        if enums:
            (dom, val), n = Counter(enums).most_common(1)[0]
            value = {"type": "enum", "domain": dom, "val": val}
        elif sk.get("object"):
            op = "exclude" if sk.get("polarity") in ("avoid", "prohibit") \
                else "include"
            value = {"type": "set", "op": op, "items": [sk["object"]]}
        else:
            value = {"type": "freeform"}

    return {"bucket": bucket, "key": key, "binding": binding,
            "polarity": sk.get("polarity", "require"),
            "value": value, "scope": scope,
            "conf": {"bucket": round(c_bucket, 2), "key": round(c_key, 2),
                     "binding": round(c_bind, 2),
                     "scope": round(sum(c_scope) / len(c_scope), 2)},
            "n_ballots": len(ballots)}
