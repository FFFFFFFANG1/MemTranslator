"""Build pilot instances from PrefEval (plan Task 3; facts per
docs/prefeval-notes.md).

Schema per plan: {id, kind, topic, preference, request, content,
memory_store: [{mid, text, topic}], relevant_memory_id}.

Stricter than plan's "different topic" rule (prefeval-notes §对 pilot plan 的影响):
distractors and negative stores are drawn from different *super-categories*
(travel_hotel vs travel_restaurant are too close to count as unrelated).
Deterministic under config.SEED; output committed for reproducibility.
"""

from __future__ import annotations

import json
import random

from pilot.config import INSTANCES, K_DISTRACTORS, N_NEG, N_POS, PREFEVAL_DIR, SEED


def super_category(topic: str) -> str:
    return topic.split("_")[0]


# ---- LOADER: the only place allowed to depend on the PrefEval repo layout ----
def load_prefeval() -> list[dict]:
    """Returns [{"topic", "preference", "query"}, ...] (verified in Task 1)."""
    items = []
    for f in sorted(PREFEVAL_DIR.glob("*.json")):
        for row in json.loads(f.read_text()):
            items.append({"topic": f.stem,
                          "preference": row["preference"],
                          "query": row["question"]})
    if not items:
        raise FileNotFoundError(f"no PrefEval topic files under {PREFEVAL_DIR}")
    return items
# -----------------------------------------------------------------------------


def _distractors(rng: random.Random, items: list[dict], exclude_supercat: str,
                 k: int) -> list[dict]:
    pool = [it for it in items if super_category(it["topic"]) != exclude_supercat]
    return rng.sample(pool, k)


def build_instances(items: list[dict], n_pos: int = N_POS, n_neg: int = N_NEG,
                    k: int = K_DISTRACTORS, seed: int = SEED):
    rng = random.Random(seed)
    by_topic: dict[str, list[dict]] = {}
    for it in items:
        by_topic.setdefault(it["topic"], []).append(it)
    topics = sorted(by_topic)

    def stratified(n: int) -> list[tuple[str, dict]]:
        picked: list[tuple[str, dict]] = []
        used: dict[str, set[int]] = {t: set() for t in topics}
        i = 0
        while len(picked) < n:
            t = topics[i % len(topics)]
            avail = [j for j in range(len(by_topic[t])) if j not in used[t]]
            if avail:
                j = rng.choice(avail)
                used[t].add(j)
                picked.append((t, by_topic[t][j]))
            i += 1
        return picked

    positives = []
    for idx, (t, it) in enumerate(stratified(n_pos)):
        mems = [(t, it["preference"])] + [
            (d["topic"], d["preference"])
            for d in _distractors(rng, items, super_category(t), k)]
        rng.shuffle(mems)
        store = [{"mid": f"m{i+1}", "text": text, "topic": mt}
                 for i, (mt, text) in enumerate(mems)]
        rel = next(m["mid"] for m in store
                   if m["text"] == it["preference"] and m["topic"] == t)
        positives.append({
            "id": f"pos-{t}-{idx:04d}", "kind": "positive", "topic": t,
            "preference": it["preference"], "request": it["query"],
            "content": "", "memory_store": store, "relevant_memory_id": rel,
        })

    negatives = []
    for idx, (t, it) in enumerate(stratified(n_neg)):
        picks = _distractors(rng, items, super_category(t), k + 1)
        store = [{"mid": f"m{i+1}", "text": d["preference"], "topic": d["topic"]}
                 for i, d in enumerate(picks)]
        negatives.append({
            "id": f"neg-{t}-{idx:04d}", "kind": "negative", "topic": t,
            "preference": None, "request": it["query"],
            "content": "", "memory_store": store, "relevant_memory_id": None,
        })
    return positives, negatives


def main() -> None:
    items = load_prefeval()
    pos, neg = build_instances(items)
    INSTANCES.mkdir(parents=True, exist_ok=True)
    out = INSTANCES / "pilot.jsonl"
    with out.open("w") as f:
        for inst in pos + neg:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
    topics = {i["topic"] for i in pos + neg}
    print(f"{len(pos)} positive + {len(neg)} negative -> {out}")
    print(f"{len(topics)} topics covered")


if __name__ == "__main__":
    main()
