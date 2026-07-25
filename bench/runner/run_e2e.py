"""Suite E: scripted personas, zero-freedom user simulator. The store starts
empty; the only thing allowed to vary between runs is the system under test
(translate + the extraction provider).

Scoring protocol v2 (2026-07-25). The v1 protocol scored a round all-or-
nothing and a persona pass/fail at 0.8, so an 8-persona suite was an 8-sample
binomial sitting on a threshold cliff — run-to-run spread reached ±0.2 and a
single number carried almost no signal. Three changes, each defensible on its
own terms and none of which can flatter a particular system:

1. PARTIAL CREDIT — a round scores carried/applicable requirements instead of
   all-or-nothing, the standard fix for discarding within-round information
   (LoCoMo grades per question rather than per conversation for the same
   reason: it stops one error from erasing a whole unit).
2. CONTINUOUS SUITE SCORE — the suite averages persona rates instead of
   counting personas over a 0.8 threshold. The threshold survives as a
   reported diagnostic, not as the aggregate.
3. REPEATS — `--repeat k` averages k independent runs per persona and reports
   the spread, so variance is measured rather than ignored.

Plus a diagnostic MODE. `chained` (default, and the gate metric) lets errors
compound exactly as they would in real use. `repaired` resets the store to the
persona's gold rules after every flush — gold-prefix state injection — which
isolates "can it apply what it should know by now" from "did an early mistake
poison everything". The gate always reads `chained`: the diagnostic exists to
localize a failure, never to replace the harder number.
"""
import argparse
import json
import time
from pathlib import Path

from memtranslator.schema import Requirement
from memtranslator.translate import translate

from bench.runner.config import (CASES, E2E_PASS_THRESHOLD,
                                 E2E_PERSONA_COUNT, E2E_REPEATS,
                                 E2E_SECOND_HALF_FROM)
from bench.runner.judge import judge
from bench.runner.providers import PROVIDERS
from bench.runner.report import write_snapshot
from bench.runner.retry import with_retry

MODES = ("chained", "repaired")

_polish = translate            # seam for tests


def _carries(req_text: str, polished: str) -> tuple[bool, bool]:
    return judge(
        f"The rewritten request explicitly carries this constraint: {req_text}",
        {"rewritten_request": polished})


def _apply_ops(store: list[Requirement], ops: list[dict]) -> None:
    by_id = {r.id: r for r in store}
    for op in ops:
        if op["kind"] == "new":
            store.append(Requirement(text=op["text"]))
        elif op["kind"] == "reinforce" and op.get("target_id") in by_id:
            by_id[op["target_id"]].updated_at = time.time()
        elif op["kind"] == "contradict" and op.get("target_id") in by_id:
            by_id[op["target_id"]].status = "retired"
            store.append(Requirement(text=op["text"]))
        elif op["kind"] == "retire" and op.get("target_id") in by_id:
            by_id[op["target_id"]].status = "retired"


def _reset_to_gold(store: list[Requirement], persona: dict,
                   exercised: set[int]) -> None:
    """Diagnostic mode only: replace the store with the rules the persona has
    actually demonstrated so far, so the next rounds start from a known-good
    state and earlier mistakes cannot compound."""
    store[:] = [Requirement(text=persona["requirements"][i])
                for i in sorted(exercised)]


def run_persona(persona: dict, provider, flush_every: int = 4,
                mode: str = "chained") -> dict:
    store: list[Requirement] = []
    pending: list[dict] = []
    rounds_out: list[dict] = []
    exercised: set[int] = set()

    for rd in persona["rounds"]:
        out = _polish(rd["task"], [r for r in store if r.status == "active"])
        polished = out["polished"] or rd["task"]
        carried, misses = 0, []
        for i in rd["applicable"]:
            exercised.add(i)
            ok, _flag = _carries(persona["requirements"][i], polished)
            if ok:
                carried += 1
            else:
                misses.append(i)
        hit = not misses
        if not hit:
            pending.append({"type": "edited_diff", "raw": rd["task"],
                            "polished": polished, "final": rd["final"]})
            if rd.get("natural_correction"):
                pending.append({"type": "natural",
                                "text": rd["natural_correction"]})
        rounds_out.append({"n": rd["n"], "hit": hit, "misses": misses,
                           "carried": carried,
                           "applicable": len(rd["applicable"]),
                           "store_size": len(store)})
        if len(pending) >= flush_every:
            _apply_ops(store, provider.extract(pending, store))
            pending = []
            if mode == "repaired":
                _reset_to_gold(store, persona, exercised)
    if pending:
        _apply_ops(store, provider.extract(pending, store))

    second = [r for r in rounds_out if r["n"] >= E2E_SECOND_HALF_FROM]
    applicable = sum(r["applicable"] for r in second)
    carried = sum(r["carried"] for r in second)
    rate = carried / applicable if applicable else 0.0
    round_rate = (sum(r["hit"] for r in second) / len(second)
                  if second else 0.0)
    return {"id": persona["id"], "category": "persona", "mode": mode,
            "score": rate, "pass": rate >= E2E_PASS_THRESHOLD,
            "second_half_rate": rate,
            "second_half_round_rate": round_rate,
            "rounds": rounds_out}


def run_persona_repeats(persona: dict, provider, repeats: int,
                        mode: str = "chained") -> dict:
    runs = [run_persona(persona, provider, mode=mode) for _ in range(repeats)]
    rates = [r["second_half_rate"] for r in runs]
    mean = sum(rates) / len(rates)
    return {"id": persona["id"], "category": "persona", "mode": mode,
            "score": mean, "pass": mean >= E2E_PASS_THRESHOLD,
            "second_half_rate": mean, "repeats": len(runs), "rates": rates,
            "spread": max(rates) - min(rates), "runs": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="null")
    ap.add_argument("--repeat", type=int, default=E2E_REPEATS,
                    help="independent runs averaged per persona")
    ap.add_argument("--mode", choices=MODES, default="chained",
                    help="chained = gate metric; repaired = diagnostic")
    args = ap.parse_args()
    provider = PROVIDERS[args.provider]()
    paths = sorted((CASES / "personas").glob("*.json"))
    if len(paths) != E2E_PERSONA_COUNT:
        raise RuntimeError(
            f"expected {E2E_PERSONA_COUNT} personas, globbed {len(paths)} — "
            f"refusing to run a silently smaller suite")
    results = []
    for p in paths:
        persona = json.loads(Path(p).read_text())
        r = with_retry(
            lambda: run_persona_repeats(persona, provider, args.repeat,
                                        args.mode),
            persona["id"])
        results.append(r)
        print(f"{persona['id']}: {r['second_half_rate']:.2f} "
              f"(spread {r['spread']:.2f} over {r['repeats']} runs) "
              f"{'PASS' if r['pass'] else 'FAIL'}", flush=True)
    write_snapshot(f"E-{args.mode}" if args.mode != "chained" else "E",
                   str(CASES / "personas"), results)


if __name__ == "__main__":
    main()
