"""Suite L: feed each case's events to a provider, grade ops against
expectations. Precision is sacred: one spurious extraction fails the case."""
import argparse
import time

from memtranslator.schema import Requirement

from bench.runner.config import CASES
from bench.runner.judge import judge
from bench.runner.providers import PROVIDERS
from bench.runner.report import write_snapshot
from bench.runner.schema import load_extraction_cases


def run_case(case, provider) -> dict:
    existing = [Requirement(text=t) for t in case.existing]
    ops = provider.extract(case.events, existing)
    failures, judge_flags, used = [], [], set()

    for exp in case.expect_ops:
        exp_target = (existing[exp["target"]].id
                      if exp.get("target") is not None else None)
        matched = None
        for i, op in enumerate(ops):
            if i in used or op["kind"] != exp["kind"]:
                continue
            if exp_target is not None and op.get("target_id") != exp_target:
                continue
            ok, flag = judge(
                f"Extracted requirement text expresses this gist: "
                f"{exp['gist']}",
                {"extracted_text": op["text"], "events": case.events})
            if flag:
                judge_flags.append(exp["gist"])
            if ok:
                matched = i
                break
        if matched is None:
            failures.append({"why": f"expected op not produced: {exp}"})
        else:
            used.add(matched)

    for i, op in enumerate(ops):
        if i not in used:
            failures.append({"why": f"spurious op: {op}"})

    return {"id": case.id, "category": case.category, "pass": not failures,
            "ops": ops, "failures": failures, "judge_flags": judge_flags}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="null")
    ap.add_argument("--cases", default=str(CASES / "extraction/cases.jsonl"))
    args = ap.parse_args()
    provider = PROVIDERS[args.provider]()
    cases = load_extraction_cases(args.cases)
    results = []
    for i, case in enumerate(cases, 1):
        r = run_case(case, provider)
        results.append(r)
        print(f"[{i}/{len(cases)}] {case.id} "
              f"{'PASS' if r['pass'] else 'FAIL'}", flush=True)
        time.sleep(0.2)
    write_snapshot("L", args.cases, results)


if __name__ == "__main__":
    main()
