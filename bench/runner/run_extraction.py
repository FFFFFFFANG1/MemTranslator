"""Suite L: feed each case's events to a provider, grade ops against
expectations. Precision is sacred: one spurious extraction fails the case."""
import argparse
import time

from memtranslator.schema import Requirement

from bench.runner.config import CASES
from bench.runner.judge import judge
from bench.runner.providers import PROVIDERS
from bench.runner.report import write_snapshot
from bench.runner.retry import with_retry
from bench.runner.schema import load_extraction_cases


def _match(exp, op, existing, case, judge_flags) -> bool:
    """Does provider op satisfy expected op? kind/target mechanical,
    text semantics via judge. retire is fully mechanical (no text)."""
    if op["kind"] != exp["kind"]:
        return False
    if exp["kind"] == "merge":
        want = {existing[i].id for i in exp["targets"]}
        if set(op.get("target_ids") or []) != want:
            return False
    elif exp.get("target") is not None:
        if op.get("target_id") != existing[exp["target"]].id:
            return False
    if exp["kind"] == "retire":
        return True
    # Narrow context on purpose (2026-07-24 fix): passing events/store here
    # turned the equivalence check into a "faithful to this one event?"
    # judgment and made verdicts flip on generalization wording — measured
    # [T,F,T] with full context vs [T,T,T] narrow on the same pair. The
    # criterion is text-vs-gist equivalence, nothing else.
    ok, flag = judge(
        f"The extracted requirement text states the same rule as this "
        f"gist: {exp['gist']}",
        {"extracted_text": op.get("text")})
    if flag:
        judge_flags.append(exp["gist"])
    return ok


def run_case(case, provider) -> dict:
    existing = [Requirement(text=t) for t in case.existing]
    # no events → this is a consolidation case: grade the store-tidying path
    if case.events:
        ops = provider.extract(case.events, existing)
    else:
        ops = provider.consolidate(existing)
    failures, judge_flags, used = [], [], set()

    for exp in case.expect_ops:
        matched = None
        for i, op in enumerate(ops):
            if i in used:
                continue
            if _match(exp, op, existing, case, judge_flags):
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
        r = with_retry(lambda: run_case(case, provider),
                       f"[{i}/{len(cases)}] {case.id}")
        results.append(r)
        print(f"[{i}/{len(cases)}] {case.id} "
              f"{'PASS' if r['pass'] else 'FAIL'}", flush=True)
        time.sleep(0.2)
    write_snapshot("L", args.cases, results)


if __name__ == "__main__":
    main()
