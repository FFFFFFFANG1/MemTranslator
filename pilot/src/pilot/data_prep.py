"""PrefEval -> pilot instances (pilot plan §1.3, facts per docs/prefeval-notes.md).

Positives (150): stratified over the 20 topics; each instance carries a
memory_store of 8 entries — the gold preference at a random position plus 7
distractors drawn from *different super-categories* (so a distractor can't
accidentally apply to the query).

Negatives (100): the query's preference is discarded; all 8 store entries come
from super-categories different from the query's (stricter than plan's
"different topic", per prefeval-notes: travel_hotel vs travel_restaurant are
too close to count as unrelated).

Deterministic under config.SEED; output committed to data/instances/ for
reproducibility.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import DATA_INSTANCES, MEMORY_STORE_SIZE, N_NEGATIVE, N_POSITIVE, PREFEVAL_DIR, SEED


def super_category(topic: str) -> str:
    return topic.split("_")[0]


@dataclass
class PrefItem:
    topic: str
    preference: str
    question: str
    explanation: str


@dataclass
class Instance:
    iid: str
    kind: str  # "positive" | "negative"
    query: str
    query_topic: str
    memory_store: list[dict]  # [{mid, text, topic}]
    gold_mid: str | None = None
    gold_preference: str | None = None
    gold_explanation: str | None = None
    meta: dict = field(default_factory=dict)


def load_prefeval(root: Path = PREFEVAL_DIR) -> dict[str, list[PrefItem]]:
    out: dict[str, list[PrefItem]] = {}
    for f in sorted(root.glob("*.json")):
        topic = f.stem
        rows = json.loads(f.read_text())
        out[topic] = [
            PrefItem(topic=topic, preference=r["preference"], question=r["question"],
                     explanation=r.get("explanation", ""))
            for r in rows
        ]
    if not out:
        raise FileNotFoundError(f"no PrefEval topic files under {root}")
    return out


def _pick_distractors(rng: random.Random, pool: list[PrefItem], exclude_supercat: str,
                      n: int) -> list[PrefItem]:
    cands = [p for p in pool if super_category(p.topic) != exclude_supercat]
    return rng.sample(cands, n)


def build_instances(data: dict[str, list[PrefItem]] | None = None,
                    n_pos: int = N_POSITIVE, n_neg: int = N_NEGATIVE,
                    store_size: int = MEMORY_STORE_SIZE,
                    seed: int = SEED) -> tuple[list[Instance], list[Instance]]:
    rng = random.Random(seed)
    data = data or load_prefeval()
    topics = sorted(data)
    flat = [p for items in data.values() for p in items]

    # --- positives: round-robin over topics until n_pos ---
    per_topic = {t: rng.sample(data[t], len(data[t])) for t in topics}
    positives: list[Instance] = []
    ti = 0
    while len(positives) < n_pos:
        topic = topics[ti % len(topics)]
        ti += 1
        if not per_topic[topic]:
            continue
        item = per_topic[topic].pop()
        distractors = _pick_distractors(rng, flat, super_category(topic), store_size - 1)
        entries = [{"mid": "", "text": d.preference, "topic": d.topic} for d in distractors]
        gold_pos = rng.randrange(store_size)
        entries.insert(gold_pos, {"mid": "", "text": item.preference, "topic": item.topic})
        for i, e in enumerate(entries):
            e["mid"] = f"m{i}"
        positives.append(Instance(
            iid=f"pos-{len(positives):04d}-{topic}",
            kind="positive",
            query=item.question,
            query_topic=topic,
            memory_store=entries,
            gold_mid=f"m{gold_pos}",
            gold_preference=item.preference,
            gold_explanation=item.explanation,
        ))

    # --- negatives: query from topic X, store entirely from other super-categories ---
    neg_sources = {t: rng.sample(data[t], len(data[t])) for t in topics}
    negatives: list[Instance] = []
    ti = 0
    while len(negatives) < n_neg:
        topic = topics[ti % len(topics)]
        ti += 1
        if not neg_sources[topic]:
            continue
        item = neg_sources[topic].pop()
        store_items = _pick_distractors(rng, flat, super_category(topic), store_size)
        entries = [{"mid": f"m{i}", "text": d.preference, "topic": d.topic}
                   for i, d in enumerate(store_items)]
        negatives.append(Instance(
            iid=f"neg-{len(negatives):04d}-{topic}",
            kind="negative",
            query=item.question,
            query_topic=topic,
            memory_store=entries,
        ))

    return positives, negatives


def write_jsonl(instances: list[Instance], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for inst in instances:
            f.write(json.dumps(asdict(inst), ensure_ascii=False) + "\n")


def main() -> None:
    pos, neg = build_instances()
    write_jsonl(pos, DATA_INSTANCES / "positives.jsonl")
    write_jsonl(neg, DATA_INSTANCES / "negatives.jsonl")
    print(f"wrote {len(pos)} positives, {len(neg)} negatives to {DATA_INSTANCES}")


if __name__ == "__main__":
    main()
