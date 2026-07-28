"""SKELETONISE: source sentence → structured proposition. The one hop that
crosses the licence wall — everything downstream (mutation, utterance,
grading) sees only the skeleton, never the source string.

The skeleton doubles as the G1 grip gate: an atom that yields neither a
threshold, nor an order, nor a named object/against pair cannot produce a
mechanical criterion, and is DROPPED — that was a human filter in the old
spec, here it is admission control.

    uv run python -m bench.gen.skeletonise [BUDGET]
"""
import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.gen.flash import flash_json

HARVEST = Path(__file__).resolve().parent / "harvest"
OUT = HARVEST / "skeletons.jsonl"

SYSTEM = """You extract the PROPOSITION from a style/delivery rule, discarding all expression.
Output exactly one JSON object:
{"delivery": true|false,
 "skeleton": {
   "trigger": "<when this rule applies, e.g. 'when writing an email'>",
   "act": "<verb of the demand, e.g. 'limit', 'start with', 'avoid'>",
   "object": "<the named thing demanded/banned, short noun phrase>",
   "against": "<the contrasted/excluded thing, or null>",
   "threshold": {"kind": "count", "value": <number>, "unit": "<words|characters|columns|items|sentences>"} | null,
   "order": ["<first>", "<second>"] | null,
   "polarity": "require"|"prefer"|"avoid"|"prohibit",
   "subject": "you"
 }}

delivery=false when the rule is about WHAT content to produce (topics, facts,
opinions, specific quotes, safety/values) rather than HOW to deliver work
(format, length, structure, tone, ordering, language, method). Also
delivery=false for one-off task steps and rules bound to one specific document.
Fields must be faithful to the rule — never invent a threshold that is not in
the text. Answer with the JSON only."""


def skeletonise_one(item: dict) -> dict | None:
    got = flash_json(SYSTEM, f"Rule:\n{item['raw']}\n\nJSON:", max_tokens=400)
    if not isinstance(got, dict) or "skeleton" not in got:
        return None
    sk = got["skeleton"] or {}
    # G1 grip gate: no threshold, no order, no object/against → no mechanical
    # criterion can be derived → drop
    grip = bool(sk.get("threshold")) or bool(sk.get("order")) \
        or bool(sk.get("object"))
    if not got.get("delivery") or not grip:
        return None
    # `raw` stays in this gitignored file so the licence gate can compare the
    # generated utterance against the true source sentence at episode-build
    # time. It must NEVER be copied into a versioned artifact.
    return {"skeleton": sk, "raw": item["raw"],
            "provenance": {"source": item["source"],
                           "license": item["license"], "url": item["url"],
                           "use": "skeleton-derived"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("budget", nargs="?", type=int, default=800,
                    help="how many candidates to skeletonise")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    pool = []
    for p in sorted(HARVEST.glob("*.jsonl")):
        if p.name in ("skeletons.jsonl", "catalogue.jsonl"):
            continue                     # pipeline outputs, not sources
        for line in p.read_text().splitlines():
            if line.strip():
                it = json.loads(line)
                if not it.get("content"):        # PRISM content rows excluded
                    pool.append(it)

    # spread the budget across sources instead of draining the biggest one
    rng = random.Random(args.seed)
    by_source: dict[str, list] = {}
    for it in pool:
        by_source.setdefault(it["source"].split("/")[0], []).append(it)
    for v in by_source.values():
        rng.shuffle(v)
    picked, i = [], 0
    while len(picked) < min(args.budget, len(pool)):
        for v in by_source.values():
            if i < len(v):
                picked.append(v[i])
                if len(picked) >= args.budget:
                    break
        i += 1
        if i > max(len(v) for v in by_source.values()):
            break

    print(f"skeletonising {len(picked)} of {len(pool)} candidates")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(skeletonise_one, picked))
    kept = [r for r in results if r]
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                           for r in kept))
    print(f"kept {len(kept)}/{len(picked)} "
          f"(G1 grip gate + delivery filter dropped the rest) -> {OUT.name}")


if __name__ == "__main__":
    main()
