"""Build a judge-audit sheet (v2): sample judged criteria from a T snapshot
and emit one section per sample WITH the full context the judge saw — stored
requirements, original request, full polished text — so a human can replay
the verdict without opening anything else (the v1 sheet lacked context and
produced 'need more info' annotations; 2026-07-24 sign-off).

Criteria are rebuilt with the same rules as run_translate.run_case; verdicts
are recovered from the snapshot (criterion listed under judge failures → no,
otherwise yes; parse-flagged criteria are marked).

Usage:
    uv run python -m bench.runner.make_audit [--snapshot PATH] [--n 30]
        [--seed 20260724] [--out bench/gen/judge-audit-<stamp>.md]
"""
import argparse
import json
import random
from pathlib import Path

from bench.runner.config import CASES, RESULTS
from bench.runner.run_translate import AUTO_NO_INVENTION, AUTO_TASK_INTACT
from bench.runner.schema import load_translate_cases

# Pre-rewording phrasing (snapshots taken before 2026-07-24 store this text
# in their judge failures); map it onto the current criterion when recovering
# verdicts so old snapshots audit correctly.
AUTO_NO_INVENTION_V1 = ("The rewritten request adds no constraint that is "
                        "not grounded in the listed stored requirements.")


def criteria_for(case, result) -> list[str]:
    """Mirror run_case's judge-criteria construction."""
    if result["decision"] == "apply":
        crits = [f"The rewritten request explicitly carries this "
                 f"constraint: {case.requirements[i]}"
                 for i in case.must_apply]
        crits += [AUTO_NO_INVENTION, AUTO_TASK_INTACT]
        crits += [c.args["criterion"] for c in case.checks
                  if c.kind == "judge"]
        return crits
    if case.expect_decision == "any":
        return [c.args["criterion"] for c in case.checks if c.kind == "judge"]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None,
                    help="T snapshot path (default: latest T-*.json)")
    ap.add_argument("--cases", default=str(CASES / "translate/cases.jsonl"))
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20260724)
    ap.add_argument("--out", default=None, help="output .md (default stdout)")
    ap.add_argument("--must-include", nargs="*", default=[],
                    help="case ids to force into the sample")
    args = ap.parse_args()

    snap_path = (Path(args.snapshot) if args.snapshot
                 else sorted(RESULTS.glob("T-*.json"))[-1])
    snap = json.loads(snap_path.read_text())
    cases = {c.id: c for c in load_translate_cases(args.cases)}

    pool = []
    for r in snap["results"]:
        case = cases.get(r["id"])
        if case is None:            # cases file drifted from the snapshot
            continue
        judged_no = {f["why"] for f in r["failures"]
                     if f.get("layer") == "judge"}
        if AUTO_NO_INVENTION_V1 in judged_no:
            judged_no.add(AUTO_NO_INVENTION)
        for crit in criteria_for(case, r):
            pool.append({
                "case": case, "result": r, "criterion": crit,
                "verdict": "no" if crit in judged_no else "yes",
                "flagged": crit in r.get("judge_flags", []),
            })

    rng = random.Random(args.seed)
    forced = [p for p in pool if p["case"].id in set(args.must_include)]
    rest = [p for p in pool if p not in forced]
    sample = forced + rng.sample(rest, max(0, args.n - len(forced)))
    sample = sample[:args.n]

    lines = [
        f"# Judge 抽检表 v2（snapshot `{snap_path.name}`，judge "
        f"{snap['judge_model']}，{len(pool)} 条判定抽 {len(sample)}，"
        f"seed {args.seed}）",
        "",
        "标注口径：**一致** = 你作为人类判官会给出同一 verdict；填在每条的"
        "「人工：」行。一致率 ≥90% 则 judge 背书。",
        "",
    ]
    for i, s in enumerate(sample, 1):
        c, r = s["case"], s["result"]
        flag = "（parse-flagged）" if s["flagged"] else ""
        lines += [
            f"## {i}. `{c.id}` — judge: **{s['verdict']}**{flag}",
            "",
            f"**Criterion:** {s['criterion']}",
            "",
            "**Stored requirements:**",
            *[f"- {t}" for t in c.requirements],
            "",
            f"**Original request:** {c.input}",
            "",
            f"**Polished (decision={r['decision']}):** "
            f"{r['polished'] or '(noop — unchanged)'}",
            "",
            "人工：",
            "",
        ]
    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out} ({len(sample)} samples)")
    else:
        print(text)


if __name__ == "__main__":
    main()
