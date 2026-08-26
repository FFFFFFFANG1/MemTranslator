"""Suite L: feed each case's events to a provider, grade ops against
expectations. Precision is sacred: one spurious extraction fails the case.

Dedup cases feed a structured candidate to the CASE consolidator
(`provider.reconcile`) instead of the archived GROUPS tidy merge path.
"""
import argparse

from memtranslator.schema import Requirement

from bench.suites.config import CASES
from bench.suites.judge import judge
from bench.suites.providers import PROVIDERS
from bench.suites.report import hash_cases, write_snapshot
from bench.suites.parallel import run_items
from bench.suites.retry import with_retry
from bench.suites.schema import load_extraction_cases


def _match(exp, op, existing, case, judge_flags) -> bool:
    """Does provider op satisfy expected op? kind/target mechanical,
    text semantics via judge. retire is fully mechanical (no text)."""
    if exp["kind"] == "deduplicate":
        want = {existing[i].id for i in exp["targets"]}
        if op["kind"] == "merge":
            if set(op.get("target_ids") or []) != want:
                return False
        elif op["kind"] == "reinforce":
            if op.get("target_id") not in want:
                return False
        else:
            return False
    elif op["kind"] != exp["kind"]:
        return False
    elif exp["kind"] == "merge":
        want = {existing[i].id for i in exp["targets"]}
        if set(op.get("target_ids") or []) != want:
            return False
    elif exp.get("targets") is not None:
        # Any-of: consolidator may reaffirm either near-duplicate in top-3.
        want = {existing[i].id for i in exp["targets"]}
        if op.get("target_id") not in want:
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
    if case.candidate is not None:
        ops = with_retry(
            lambda: provider.reconcile(case.candidate, existing),
            f"{case.id}/reconcile")
    elif case.events:
        ops = with_retry(lambda: provider.extract(case.events, existing),
                         f"{case.id}/extract")
    else:
        ops = with_retry(lambda: provider.consolidate(existing),
                         f"{case.id}/consolidate")
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
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fresh", action="store_true",
                    help="ignore any checkpoint and start over")
    args = ap.parse_args()
    provider = PROVIDERS[args.provider]()
    cases = load_extraction_cases(args.cases)
    results = run_items("L", cases,
                        lambda c: run_case(c, provider),
                        workers=args.workers, resume=not args.fresh,
                        run_key=hash_cases(args.cases))
    write_snapshot("L", args.cases, results, expected=len(cases))


if __name__ == "__main__":
    main()
