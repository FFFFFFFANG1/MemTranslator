"""Aggregate per-category → suite (macro) → overall, decide the gate, and
persist a reproducible snapshot per run."""
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

from bench.runner.config import (GATE_OVERALL, GATE_PER_SUITE, JUDGE_MODEL,
                                 RESULTS, WEIGHTS)


def category_rates(results: list[dict]) -> dict[str, float]:
    buckets = defaultdict(list)
    for r in results:
        buckets[r["category"]].append(r["pass"])
    return {c: sum(v) / len(v) for c, v in sorted(buckets.items())}


def suite_score(results: list[dict]) -> float:
    rates = category_rates(results)
    return sum(rates.values()) / len(rates) if rates else 0.0


def write_snapshot(suite: str, cases_path: str, results: list[dict]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    case_hash = hashlib.sha256(
        Path(cases_path).read_bytes()).hexdigest()[:12]
    snap = {"suite": suite, "at": stamp, "judge_model": JUDGE_MODEL,
            "cases_file": str(cases_path), "cases_hash": case_hash,
            "score": suite_score(results),
            "category_rates": category_rates(results),
            "judge_parse_flags": sum(len(r.get("judge_flags", []))
                                     for r in results),
            "results": results}
    out = RESULTS / f"{suite}-{stamp}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"\n{suite} suite score: {snap['score']:.3f}")
    for c, v in snap["category_rates"].items():
        print(f"  {c:20s} {v:.2f}")
    print(f"snapshot: {out}")
    return out


def latest(suite: str) -> dict | None:
    snaps = sorted(RESULTS.glob(f"{suite}-*.json"))
    return json.loads(snaps[-1].read_text()) if snaps else None


def main():
    scores, missing = {}, []
    for s in ("T", "L", "E"):
        snap = latest(s)
        if snap is None:
            missing.append(s)
        else:
            scores[s] = snap["score"]
            print(f"{s}: {snap['score']:.3f}  ({snap['at']}, "
                  f"judge={snap['judge_model']})")
    if missing:
        print(f"missing suites: {missing} — overall not computable yet")
        return
    overall = sum(WEIGHTS[s] * scores[s] for s in scores)
    gate = overall >= GATE_OVERALL and all(v >= GATE_PER_SUITE
                                           for v in scores.values())
    print(f"\noverall = {overall:.3f}   "
          f"gate(≥{GATE_OVERALL:.2f} & each≥{GATE_PER_SUITE:.2f}): "
          f"{'PASS — first release is good enough' if gate else 'FAIL'}")


if __name__ == "__main__":
    main()
