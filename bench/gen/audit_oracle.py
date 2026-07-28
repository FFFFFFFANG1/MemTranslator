"""Bench self-check: run ONLY the oracle-should arm and adjudicate every miss.

The premise (owner ruling 2026-07-28): a perfect store handed exactly the
rules that apply, on a request squarely in their domain, should carry them.
When it does not, the FIRST suspect is the exam, not the product. So each
miss is put to an independent adjudicator that never sees the gold's verdict
and answers the applies_to question from scratch:

    adjudicator says "the rewrite did NOT have to add this"  → GOLD DEFECT
    adjudicator says "it did have to"                        → product miss

The bench is clean when the gold-defect share is near zero. Until then the
other arms are not worth running: every one of them inherits the same answer
key, so a contaminated key contaminates the whole panel at 5x the cost.

    uv run python -m bench.gen.audit_oracle            # sample across fleet
    uv run python -m bench.gen.audit_oracle --episodes e-01,e-03 --probes 8
"""
import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bench.runner.run_episodes as R
from bench.runner.judge import judge

EPISODES = Path(__file__).resolve().parents[1] / "cases" / "episodes"

ADJUDICATOR = (
    "A rewriter sits between a user and an assistant. It may only ADD "
    "constraints that a stored rule requires. Decide: given this exact "
    "request, was the rewriter OBLIGED to weave this stored rule into it? "
    "Answer no if the rule does not apply to this kind of work, if the "
    "request already states or satisfies it, if the rule is about what to "
    "say rather than how to deliver it (topics, opinions, values, safety, "
    "persona), if it is vacuous, or if it is garbled.")

# mechanical corpus smells, kept because they need no call and name the cause
_FALLBACK = lambda zh, c: zh and not re.search(r"[一-鿿]", c)
_MANGLED = re.compile(
    r"\d+\s+(items|options|spaces|characters|days|references)\b")


def _classify(req: str, clause: str, zh: bool) -> str:
    if _FALLBACK(zh, clause):
        return "gold: untranslated fallback"
    if _MANGLED.search(clause):
        return "gold: mangled threshold"
    ok, _flag = judge(ADJUDICATOR,
                      {"request": req, "stored_rule": clause})
    return "product: real miss" if ok else "gold: rule should not apply"


def audit_probe(job):
    epid, ep, r, zh = job
    by = {n["cid"]: n for n in ep["catalogue"]}
    out = R.arm_oracle_should([], ep, r, [])
    polished = out.get("polished") or ""
    rows = []
    for cid in r.get("should_fire", []):
        n = by.get(cid)
        if n is None or n.get("anchor_weak"):
            continue
        clause = n["clause"] or n["text"]
        carried = False
        if polished:
            carried, _flag = judge(
                f"The rewritten request explicitly carries this constraint: "
                f"{clause}", {"rewritten_request": polished})
        rows.append({
            "episode": epid, "seq": r["seq"], "cid": cid,
            "request": r["text"], "clause": clause,
            "noop": not polished, "carried": bool(carried),
            "verdict": ("carried" if carried
                        else _classify(r["text"], clause, zh))})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="",
                    help="comma list; default = every built episode")
    ap.add_argument("--probes", type=int, default=6,
                    help="probes sampled per episode")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    ids = ([e.strip() for e in args.episodes.split(",") if e.strip()]
           or sorted(p.stem for p in EPISODES.glob("e-*.json")))
    jobs = []
    for epid in ids:
        ep = json.loads((EPISODES / f"{epid}.json").read_text())
        zh = "zh" in ep["persona"].get("lang", "")
        probes = [r for r in ep["rounds"]
                  if r.get("probe") and r.get("should_fire")]
        step = max(1, len(probes) // args.probes)
        for r in probes[::step][:args.probes]:
            jobs.append((epid, ep, r, zh))
    print(f"auditing {len(jobs)} probes across {len(ids)} episodes "
          f"(oracle-should only)")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = [x for sub in ex.map(audit_probe, jobs) for x in sub]

    if not rows:
        print("no should_fire gold anywhere — the answer key is empty")
        return
    verdicts = Counter(r["verdict"] for r in rows)
    carried = verdicts["carried"]
    gold_bad = sum(v for k, v in verdicts.items() if k.startswith("gold"))
    prod_bad = verdicts["product: real miss"]
    n = len(rows)
    noop_probes = len({(r["episode"], r["seq"]) for r in rows if r["noop"]})
    all_probes = len({(r["episode"], r["seq"]) for r in rows})

    print(f"\nshould_fire decisions: {n}   probes: {all_probes}  "
          f"(noop on {noop_probes} = {noop_probes / all_probes:.0%})")
    print(f"  CARRIED              {carried:4d}  {carried / n:.3f}")
    for k, v in sorted(verdicts.items()):
        if k != "carried":
            print(f"  {k:<32s} {v:4d}  {v / n:.3f}")
    print(f"\n  gold-defect share of ALL decisions : {gold_bad / n:.3f}")
    if gold_bad + prod_bad:
        print(f"  gold-defect share of MISSES        : "
              f"{gold_bad / (gold_bad + prod_bad):.3f}")
    print(f"  oracle-should CARRY (as scored)     : {carried / n:.3f}")
    adj = carried + gold_bad
    print(f"  CARRY if gold defects were removed  : "
          f"{carried / max(1, n - gold_bad):.3f}  "
          f"(would leave {n - gold_bad} decisions)")

    print(f"\n--- worst offenders (up to {args.show}) ---")
    for r in [x for x in rows if x["verdict"].startswith("gold")][:args.show]:
        print(f"[{r['episode']} seq{r['seq']}] {r['verdict']}")
        print(f"  请求 : {r['request'][:82]}")
        print(f"  规则 : {r['clause'][:82]}")


if __name__ == "__main__":
    main()
