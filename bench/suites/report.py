"""Aggregate results → suite score, decide the gate, persist a reproducible
snapshot per run.

M0 rework, six changes and why each exists:

- `suite_score` returns {headline: min(micro, macro), micro, macro, gap}. A
  macro-only mean lets many small strata hide one collapsed big stratum and
  vice versa; min() means neither view can flatter the number, and `gap` shows
  when they disagree enough to investigate.
- `strata_rates(results, by=...)` replaces the category-only breakdown: on
  suite E every category was "persona", so the old table printed the suite
  score twice while the interesting strata (mode, episode) were invisible.
- Repeat-collapse flags: a persona whose repeats read [0.17, 0.75, 0.67] is
  not a persona with mean 0.53, it is a persona that collapses one run in
  three. The mean hides exactly the failure this suite exists to find.
- Snapshot hash uses rglob + relative paths: episodes will live in
  subdirectories, and the old `glob("*.json")` would silently hash an empty
  set — an empty cases_hash looks valid and matches nothing.
- `metric_version` + refusal to aggregate mismatched snapshots: min(micro,
  macro) is not comparable with the old macro mean, and a gate quietly mixing
  the two would manufacture a trend out of a definition change.
- `expected`/completed counts: a run that lost shards used to score as if the
  lost shards never existed. Incomplete snapshots are marked and the gate
  skips them.
"""
import hashlib
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from bench.suites.config import JUDGE_MODEL, METRIC_VERSION, RESULTS

# A repeat set collapses when the spread is large AND the floor is far below
# the ceiling — [0.17, 0.75, 0.67] flags, [0.60, 0.75, 0.67] does not.
COLLAPSE_SPREAD = 0.4
COLLAPSE_FLOOR_RATIO = 0.5


def _values(r: dict) -> list[float]:
    """Every independent measurement a result carries: per-repeat rates when
    present, else the single score, else the binary pass."""
    if r.get("rates"):
        return [float(v) for v in r["rates"]]
    if r.get("score") is not None:
        return [float(r["score"])]
    return [float(r["pass"])]


def strata_rates(results: list[dict], by: str = "category") -> dict[str, float]:
    """Mean per stratum. `by` is any key results carry (category, mode,
    episode, ...); results missing the key fall into "(none)"."""
    buckets = defaultdict(list)
    for r in results:
        buckets[str(r.get(by) or "(none)")].append(
            float(r["score"]) if r.get("score") is not None
            else float(r["pass"]))
    return {c: sum(v) / len(v) for c, v in sorted(buckets.items())}


def category_rates(results: list[dict]) -> dict[str, float]:
    return strata_rates(results, by="category")


def suite_score(results: list[dict]) -> dict:
    """{headline, micro, macro, gap}. macro weights strata equally; micro
    weights every measurement equally; headline takes the worse of the two."""
    if not results:
        return {"headline": 0.0, "micro": 0.0, "macro": 0.0, "gap": 0.0}
    macro_rates = strata_rates(results, by="category")
    macro = sum(macro_rates.values()) / len(macro_rates)
    all_values = [v for r in results for v in _values(r)]
    micro = sum(all_values) / len(all_values)
    return {"headline": min(micro, macro), "micro": micro, "macro": macro,
            "gap": abs(micro - macro)}


def collapse_flags(results: list[dict]) -> list[dict]:
    flags = []
    for r in results:
        rates = r.get("rates")
        if not rates or len(rates) < 2:
            continue
        spread = max(rates) - min(rates)
        if spread >= COLLAPSE_SPREAD and \
                min(rates) <= COLLAPSE_FLOOR_RATIO * max(rates):
            flags.append({"id": r["id"], "rates": rates,
                          "spread": round(spread, 3)})
    return flags


def hash_cases(cases_path: str) -> str:
    """Content hash of the case set. Directories hash every nested json with
    its relative path folded in, so a file moving between subdirectories (or a
    subdirectory being silently invisible) changes the hash instead of
    vanishing from it."""
    p = Path(cases_path)
    h = hashlib.sha256()
    if p.is_dir():
        for f in sorted(p.rglob("*.json*")):
            if f.is_file():
                h.update(str(f.relative_to(p)).encode())
                h.update(f.read_bytes())
    else:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def write_snapshot(suite: str, cases_path: str, results: list[dict],
                   expected: int | None = None, extra: dict | None = None) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    score = suite_score(results)
    flags = collapse_flags(results)
    complete = expected is None or len(results) == expected
    snap = {"suite": suite, "at": stamp, "metric_version": METRIC_VERSION,
            "judge_model": JUDGE_MODEL,
            "cases_file": str(cases_path), "cases_hash": hash_cases(cases_path),
            "score": score["headline"], "score_detail": score,
            "expected_shards": expected, "completed_shards": len(results),
            "complete": complete,
            "category_rates": strata_rates(results, "category"),
            "strata": {by: strata_rates(results, by)
                       for by in ("mode", "episode")
                       if any(r.get(by) for r in results)},
            "collapse_flags": flags,
            "judge_parse_flags": sum(len(r.get("judge_flags", []))
                                     for r in results),
            **(extra or {}),
            "results": results}
    out = RESULTS / f"{suite}-{stamp}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"\n{suite} suite score: {score['headline']:.3f} "
          f"(micro {score['micro']:.3f} / macro {score['macro']:.3f})")
    for c, v in snap["category_rates"].items():
        print(f"  {c:20s} {v:.2f}")
    if not complete:
        print(f"  !! INCOMPLETE: {len(results)}/{expected} shards — "
              f"the gate will not read this snapshot")
    for f in flags:
        print(f"  !! repeat collapse: {f['id']} rates={f['rates']}")
    print(f"snapshot: {out}")
    return out


_STAMP = re.compile(r"^(?P<suite>.+)-\d{8}-\d{6}$")


def latest(suite: str) -> dict | None:
    """Newest snapshot for exactly this suite.

    The suffix must be matched exactly, not globbed: diagnostic runs write
    sibling names like `E-repaired-<stamp>.json`, and a `E-*.json` glob sorts
    those AFTER `E-<stamp>.json` — which silently fed the easier diagnostic
    score to the gate. The gate reads the chained suite or nothing."""
    snaps = [p for p in RESULTS.glob(f"{suite}-*.json")
             if (m := _STAMP.match(p.stem)) and m.group("suite") == suite]
    return json.loads(max(snaps).read_text()) if snaps else None


def main():
    """Scoreboard, not a gate. Owner ruling 2026-07-28: no weighted overall,
    no PASS/FAIL verdict — every suite reports its own numbers and decisions
    read the parts. (A weighted single number let a toy suite top a gate once;
    the parts cannot be averaged past each other again.)"""
    for s in ("T", "L", "E"):
        snap = latest(s)
        if snap is None:
            print(f"{s:3s}: (no snapshot)")
            continue
        stale = ""
        if snap.get("metric_version") != METRIC_VERSION:
            stale = f"  [metric_version {snap.get('metric_version')} — stale]"
        if not snap.get("complete", True):
            stale += (f"  [INCOMPLETE {snap.get('completed_shards')}/"
                      f"{snap.get('expected_shards')}]")
        print(f"{s:3s}: {snap['score']:.3f}  ({snap['at']}, "
              f"judge={snap['judge_model']}){stale}")
    print("E1 : run `python -m bench.suites.report_e1` for the lifecycle "
          "fleet (reported per band: CARRY / SUPPRESS / STATE)")


if __name__ == "__main__":
    main()
