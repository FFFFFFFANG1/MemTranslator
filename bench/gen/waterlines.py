"""Fold bench/results/*.json into a committed water-line log.

`bench/results/` is gitignored (full snapshots carry every rewrite and every
judge verdict, and they grow fast), so every score this project has ever
measured lives on one machine only. That is fine until you switch machines,
at which point the whole comparison history is gone.

This keeps the part that has to survive: per-snapshot suite score plus the
per-case pass/score vector — enough to diff any two runs and to plot a water
line, small enough to commit. Re-run after a bench run; it rewrites the file
from whatever snapshots are present and is safe to run repeatedly.

    uv run python -m bench.gen.waterlines
"""
import json
import re
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"
OUT = Path(__file__).resolve().parents[1] / "waterlines.jsonl"
STAMP = re.compile(r"^(?P<suite>.+)-(?P<at>\d{8}-\d{6})\.json$")


def fold(path: Path) -> dict | None:
    m = STAMP.match(path.name)
    if not m:
        return None
    d = json.loads(path.read_text())
    results = d["results"] if isinstance(d, dict) else d
    cases = {}
    for r in results:
        # E carries a continuous score; T and L are binary
        cases[r["id"]] = (round(float(r["score"]), 4)
                          if r.get("score") is not None else bool(r["pass"]))
    row = {"suite": m["suite"], "at": m["at"], "cases": cases}
    if isinstance(d, dict):
        for k in ("score", "judge_model", "cases_path"):
            if k in d:
                row[k] = d[k]
    return row


def main() -> None:
    rows = [r for r in (fold(p) for p in sorted(RESULTS.glob("*.json"))) if r]
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False,
                                      sort_keys=True) + "\n" for r in rows))
    print(f"{len(rows)} snapshots -> {OUT} ({OUT.stat().st_size} bytes)")
    for r in rows[-6:]:
        print(f"  {r['suite']:12s} {r['at']}  {r.get('score', '?')}")


if __name__ == "__main__":
    main()
