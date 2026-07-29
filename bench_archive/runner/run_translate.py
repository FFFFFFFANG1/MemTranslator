"""Suite T: run each case through the real translate() read path, grade in
three layers (decision → mechanical → judge). One result dict per case."""
import argparse
import json
import time

from memtranslator.schema import Requirement
from memtranslator.translate import translate

from bench_archive.runner.checkers import run_check
from bench_archive.runner.config import CASES
from bench_archive.runner.judge import judge
from bench_archive.runner.report import hash_cases, write_snapshot
from bench_archive.runner.parallel import run_items
from bench_archive.runner.retry import with_retry
from bench_archive.runner.schema import load_translate_cases

# v3 wording (owner ruling 2026-07-29): grounding is ternary. Verbatim carry
# and entailed specialization both pass — the read path is ALLOWED to expand a
# stored rule into task-specific specifics, provided satisfying the expansion
# necessarily satisfies the rule. Only ungrounded additions fail. Scores are
# not comparable with v2 snapshots (METRIC_VERSION bumped alongside).
AUTO_NO_INVENTION = (
    "Compare the rewritten request against the original request and list "
    "every constraint the rewrite ADDED (length, format, tone, language, "
    "method, audience...). Classify each added constraint: (a) stated in a "
    "stored requirement, (b) a SPECIALIZATION of a stored requirement — any "
    "output satisfying the added constraint would necessarily also satisfy "
    "that requirement, or (c) backed by no stored requirement. Verdict yes "
    "if every added constraint is (a) or (b); verdict no if at least one is "
    "(c), and name it in the reason.")
AUTO_TASK_INTACT = ("The core task of the original request is unchanged in "
                    "the rewritten request.")


def run_case(case) -> dict:
    reqs = [Requirement(text=t) for t in case.requirements]
    out = with_retry(lambda: translate(case.input, reqs), f"{case.id}/translate")
    polished = out["polished"] or case.input
    failures, judge_flags = [], []

    # 1. decision layer (mechanical)
    decision_ok = (case.expect_decision == "any"
                   or out["decision"] == case.expect_decision)
    if decision_ok and case.expect_decision == "apply":
        need = {reqs[i].id for i in case.must_apply}
        if not need <= set(out["applied_ids"]):
            decision_ok = False
            failures.append({"layer": "decision",
                             "why": f"applied_ids missed {need}"})
    if not decision_ok and not failures:
        failures.append({"layer": "decision",
                         "why": f"expected {case.expect_decision}, "
                                f"got {out['decision']}"})

    # 2 + 3 only matter when something was rewritten
    if out["decision"] == "apply":
        for c in case.checks:
            if c.kind != "mech":
                continue
            ok, why = run_check(c.name, c.args, polished=polished,
                                case_input=case.input)
            if not ok:
                failures.append({"layer": "mech", "check": c.name, "why": why})
        ctx = {"stored_requirements": case.requirements,
               "original_request": case.input, "rewritten_request": polished}
        criteria = [f"The rewritten request explicitly carries this "
                    f"constraint: {case.requirements[i]}"
                    for i in case.must_apply]
        criteria += [AUTO_NO_INVENTION, AUTO_TASK_INTACT]
        criteria += [c.args["criterion"] for c in case.checks
                     if c.kind == "judge"]
        for crit in criteria:
            ok, flag = judge(crit, ctx)
            if flag:
                judge_flags.append(crit)
            if not ok:
                failures.append({"layer": "judge", "why": crit})
    elif case.expect_decision == "any":
        # noop side of an exception case: only judge checks that make sense
        ctx = {"stored_requirements": case.requirements,
               "original_request": case.input, "rewritten_request": polished}
        for c in case.checks:
            if c.kind == "judge":
                ok, flag = judge(c.args["criterion"], ctx)
                if flag:
                    judge_flags.append(c.args["criterion"])
                if not ok:
                    failures.append({"layer": "judge",
                                     "why": c.args["criterion"]})

    return {"id": case.id, "category": case.category, "pass": not failures,
            "decision_ok": decision_ok, "decision": out["decision"],
            "polished": out["polished"], "failures": failures,
            "judge_flags": judge_flags, "latency_ms": out["latency_ms"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(CASES / "translate/cases.jsonl"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fresh", action="store_true",
                    help="ignore any checkpoint and start over")
    args = ap.parse_args()
    cases = load_translate_cases(args.cases)
    results = run_items("T", cases, run_case,
                        workers=args.workers, resume=not args.fresh,
                        run_key=hash_cases(args.cases))
    write_snapshot("T", args.cases, results, expected=len(cases))


if __name__ == "__main__":
    main()
