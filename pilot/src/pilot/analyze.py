"""Aggregate pilot results -> docs/pilot-results.md with all §1.5 metrics
(plan Task 11). Adherence excludes not_applicable and judge_parse_error cells
(counts shown via per-cell n). Baseline arms appear automatically when the
run included them."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict

from pilot.config import ARMS, BASELINE_ARMS, DOWNSTREAM_TIERS, PILOT_ROOT, RESULTS, SEED

DOCS = PILOT_ROOT.parent / "docs"


def bootstrap_ci(flags, n_boot=2000, seed=SEED):
    rng = random.Random(seed)
    if not flags:
        return float("nan"), float("nan"), float("nan")
    means = sorted(sum(rng.choices(flags, k=len(flags))) / len(flags)
                   for _ in range(n_boot))
    return (sum(flags) / len(flags),
            means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1])


def paired_delta_ci(a, b, n_boot=2000, seed=SEED):
    """a, b: same-length 0/1 lists over the same instances."""
    rng = random.Random(seed)
    idx = list(range(len(a)))

    def one_boot() -> float:
        s = rng.choices(idx, k=len(idx))
        return (sum(a[i] for i in s) - sum(b[i] for i in s)) / len(idx)

    deltas = sorted(one_boot() for _ in range(n_boot))
    delta = sum(a) / len(a) - sum(b) / len(b)
    return delta, deltas[int(0.025 * n_boot)], deltas[int(0.975 * n_boot) - 1]


def collect(rows):
    """-> {(tier, arm): {"adh": {id: 0/1}, "far": {id: 0/1}}}, translator stats"""
    cells = defaultdict(lambda: {"adh": {}, "far": {}, "in_tok": []})
    tr = {"pos_apply": 0, "pos_total": 0, "neg_noop": 0, "neg_total": 0,
          "parse_err": 0, "preserve_bad_task": 0, "preserve_overreach": 0}
    for r in rows:
        d = r["translator"]["patch"]["decision"]
        tr["parse_err"] += r["translator"]["parse_error"]
        if r["kind"] == "positive":
            tr["pos_total"] += 1
            tr["pos_apply"] += (d == "apply")
            p = r.get("preservation", {})
            tr["preserve_bad_task"] += (p.get("same_core_task") is False)
            tr["preserve_overreach"] += (p.get("added_beyond_memories") is True)
        else:
            tr["neg_total"] += 1
            tr["neg_noop"] += (d == "noop")
        for key, cell in r["arms"].items():
            tier, arm = key.split("/")
            cells[(tier, arm)]["in_tok"].append(cell["input_tokens"])
            if "adherence" in cell:
                a = cell["adherence"]
                if not a.get("judge_parse_error") and a["verdict"] in (
                        "followed", "violated"):
                    cells[(tier, arm)]["adh"][r["id"]] = int(
                        a["verdict"] == "followed")
            if "far" in cell:
                fa = cell["far"]
                if not fa.get("judge_parse_error"):
                    cells[(tier, arm)]["far"][r["id"]] = int(
                        bool(fa["steered"]))
    return cells, tr


def fmt_pct(triple):
    m, lo, hi = triple
    return f"{m:.1%} [{lo:.1%}, {hi:.1%}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="pilot-full")
    args = ap.parse_args()
    rows = [json.loads(l)
            for l in (RESULTS / f"{args.run_id}.jsonl").open()]
    cells, tr = collect(rows)
    arms = [a for a in ARMS + BASELINE_ARMS
            if any((t, a) in cells for t in DOWNSTREAM_TIERS)]

    lines = [f"# Pilot results — run `{args.run_id}`", "",
             f"n = {len(rows)} instances "
             f"({tr['pos_total']} positive, {tr['neg_total']} negative)", ""]
    lines += ["## Adherence (positive set)", "",
              "| tier | arm | n | adherence [95% CI] |", "|---|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        for arm in arms:
            adh = cells[(tier, arm)]["adh"]
            lines.append(f"| {tier} | {arm} | {len(adh)} | "
                         f"{fmt_pct(bootstrap_ci(list(adh.values())))} |")
    lines += ["", "## Paired deltas: A3 vs injection arms", "",
              "| tier | comparison | delta [95% CI] |", "|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        a3 = cells[(tier, "A3_translator")]["adh"]
        for other in [a for a in arms if a not in ("A0_none", "A3_translator")]:
            o = cells[(tier, other)]["adh"]
            common = sorted(set(a3) & set(o))
            if common:
                d = paired_delta_ci([a3[i] for i in common],
                                    [o[i] for i in common])
                lines.append(f"| {tier} | A3 − {other} | "
                             f"{d[0]:+.1%} [{d[1]:+.1%}, {d[2]:+.1%}] |")
    lines += ["", "## False application rate (negative set)", "",
              "| tier | arm | n | FAR [95% CI] |", "|---|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        for arm in arms:
            far = cells[(tier, arm)]["far"]
            lines.append(f"| {tier} | {arm} | {len(far)} | "
                         f"{fmt_pct(bootstrap_ci(list(far.values())))} |")
    lines += ["", "## Translator behavior", "",
              f"- P(apply | positive) = {tr['pos_apply']}/{tr['pos_total']}"
              f" = {tr['pos_apply']/max(tr['pos_total'],1):.1%}",
              f"- P(noop | negative) = {tr['neg_noop']}/{tr['neg_total']}"
              f" = {tr['neg_noop']/max(tr['neg_total'],1):.1%}  ← 判据 G3",
              f"- parse errors: {tr['parse_err']}",
              f"- preservation: core-task changed {tr['preserve_bad_task']},"
              f" over-reach beyond memories {tr['preserve_overreach']}"
              f" (of {tr['pos_total']} positives)"]
    lines += ["", "## Downstream input tokens (mean per instance)", "",
              "| tier | arm | mean input tokens |", "|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        for arm in arms:
            toks = cells[(tier, arm)]["in_tok"]
            mean = sum(toks) / len(toks) if toks else float("nan")
            lines.append(f"| {tier} | {arm} | {mean:.0f} |")

    out = DOCS / ("pilot-results.md" if args.run_id == "pilot-full"
                  else f"pilot-results-{args.run_id}.md")
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
