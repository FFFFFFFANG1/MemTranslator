"""Is t-long-004's flip a stable judgment or judge noise?

Replays the exact AUTO_NO_INVENTION criterion the T runner uses, N times
against the BEFORE (0.950 run) and AFTER (0.933 run) polished outputs, and
prints the judge's own stated reason each time. Pure Ark/DeepSeek channel —
costs nothing against the Anthropic balance and does not touch the running
E suite.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from bench.runner.judge import JUDGE_SYSTEM, _complete          # noqa: E402
from bench.runner.run_translate import AUTO_NO_INVENTION, AUTO_TASK_INTACT  # noqa: E402

N = 8
CASE_ID = "t-long-004"


def load(path):
    d = json.load(open(path))
    res = d["results"] if isinstance(d, dict) else d
    return {r["id"]: r for r in res}


def raw_judge(criterion, context):
    user = (f"CRITERION:\n{criterion}\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=1)}")
    s = _complete(JUDGE_SYSTEM, user).strip()
    a, b = s.find("{"), s.rfind("}")
    try:
        obj = json.loads(s[a:b + 1])
    except Exception:
        return None, s[:120]
    return obj.get("verdict"), obj.get("reason", "")


def main():
    case = next(json.loads(l) for l in open("bench/cases/translate/cases.jsonl")
                if json.loads(l)["id"] == CASE_ID)
    before = load("bench/results/T-20260726-225611.json")[CASE_ID]["polished"]
    after = load("bench/results/T-20260727-152607.json")[CASE_ID]["polished"]

    for crit_name, crit in (("NO_INVENTION", AUTO_NO_INVENTION),
                            ("TASK_INTACT", AUTO_TASK_INTACT)):
        print(f"\n{'='*72}\n{crit_name}\n{'='*72}")
        for tag, polished in (("BEFORE(0.950)", before), ("AFTER(0.933)", after)):
            ctx = {"stored_requirements": case["requirements"],
                   "original_request": case["input"],
                   "rewritten_request": polished}
            with ThreadPoolExecutor(max_workers=4) as ex:
                out = list(ex.map(lambda _: raw_judge(crit, ctx), range(N)))
            yes = sum(1 for v, _ in out if v == "yes")
            print(f"\n  {tag}: yes={yes}/{N}")
            seen = set()
            for v, r in out:
                key = (v, (r or "")[:90])
                if key in seen:
                    continue
                seen.add(key)
                print(f"    [{v}] {r}")


if __name__ == "__main__":
    main()
