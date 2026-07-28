"""Field-level mutation, pure code. Mutation happens on the SKELETON, before
any sentence exists, so there is no "changed the number but the sentence kept
the original" residue — the anti-backbone property is structural, not
best-effort.

Numeric values move to non-round, non-source, non-familiar numbers: 80/100/
120/79/4/2 are burned into every backbone, and a familiar value measures the
model's priors, not its memory. Ordering mutations swap the pair. Skeletons
with neither (named-object-only) flip polarity."""
import random

# values a backbone already knows by heart; never land on these
_FAMILIAR = {1, 2, 3, 4, 5, 8, 10, 12, 15, 20, 24, 25, 30, 40, 50, 60, 72,
             79, 80, 100, 120, 140, 150, 200, 250, 280, 300, 450, 500, 1000}


def _mutate_number(orig: float, rng: random.Random) -> int:
    base = max(4, orig)
    for _ in range(64):
        factor = rng.choice((0.55, 0.65, 0.75, 1.25, 1.4, 1.6))
        cand = int(round(base * factor)) + rng.choice((-3, -1, 1, 2, 3))
        if cand > 0 and cand != orig and cand not in _FAMILIAR \
                and cand % 10 != 0:
            return cand
    return int(orig) + 7                     # deterministic fallback


def mutate(skeleton: dict, rng: random.Random) -> tuple[dict, str]:
    """Returns (mutated_skeleton, mutation_desc). Copies, never mutates in
    place — the unmutated skeleton stays around as the supersede predecessor
    material."""
    sk = {**skeleton,
          "threshold": dict(skeleton["threshold"])
          if skeleton.get("threshold") else None,
          "order": list(skeleton["order"]) if skeleton.get("order") else None}
    th = sk.get("threshold")
    if th and isinstance(th.get("value"), (int, float)):
        new = _mutate_number(th["value"], rng)
        desc = f"threshold {th['value']} -> {new}"
        th["value"] = new
        return sk, desc
    if sk.get("order") and len(sk["order"]) == 2:
        a, b = sk["order"]
        sk["order"] = [b, a]
        return sk, f"order swapped: {a}<->{b}"
    flip = {"require": "prohibit", "prefer": "avoid",
            "avoid": "prefer", "prohibit": "require"}
    old = sk.get("polarity", "require")
    sk["polarity"] = flip.get(old, "prohibit")
    return sk, f"polarity {old} -> {sk['polarity']}"
