"""Suite E0: scripted personas, zero-freedom user simulator. The store starts
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

M0 rework (2026-07-28): the runner's private `_apply_ops` is gone. It had no
merge branch, never wrote `supersedes`, and built `Requirement(text=...)`
without key/scope/bucket/salience — so the suite was grading the product on a
store the product does not have. Each persona-run now drives a REAL
`memtranslator.store.Store` on a private path under RUN_DIR, ops apply through
the product's own `Store.apply_ops`, `translate` receives the `context` third
argument (before this, `_scope_ok` had never once executed on this suite), and
the harness drives consolidation the way a daemon would — `Pipeline.maybe_flush`
does not call it, so a bench that doesn't either is silently exempting the
consolidation path from ever being tested. Each consolidation records WHICH
trigger fired: CONSOLIDATE_ADDS resets the counter and structurally shadows
CONSOLIDATE_ACTIVE, and "the ACTIVE branch never fired" is a product finding
the snapshot should carry, not a guess.
"""
import argparse
import json
import uuid
from pathlib import Path

from memtranslator.config import CONSOLIDATE_ACTIVE, CONSOLIDATE_ADDS
from memtranslator.consolidate import should_consolidate
from memtranslator.store import Store
from memtranslator.translate import translate

from bench.suites.config import (CASES, E2E_PASS_THRESHOLD,
                                 E2E_PERSONA_COUNT, E2E_REPEATS,
                                 E2E_SECOND_HALF_FROM, RUN_DIR)
from bench.suites.judge import judge
from bench.suites.providers import PROVIDERS
from bench.suites.report import hash_cases, write_snapshot
from bench.suites.parallel import run_items
from bench.suites.retry import with_retry

MODES = ("chained", "repaired")

_polish = translate            # seam for tests


def _carries(req_text: str, polished: str) -> tuple[bool, bool]:
    return judge(
        f"The rewritten request explicitly carries this constraint: {req_text}",
        {"rewritten_request": polished})


def _fresh_store(persona_id: str) -> Store:
    d = RUN_DIR / "e2e-stores"
    d.mkdir(parents=True, exist_ok=True)
    return Store(d / f"{persona_id}-{uuid.uuid4().hex[:8]}.jsonl")


def _reset_to_gold(persona: dict, exercised: set[int]) -> Store:
    """Diagnostic mode only: a fresh store holding the rules the persona has
    actually demonstrated so far, so the next rounds start from a known-good
    state and earlier mistakes cannot compound."""
    store = _fresh_store(persona["id"] + "-gold")
    for i in sorted(exercised):
        store.add(persona["requirements"][i], source="manual")
    return store


def run_persona(persona: dict, provider, flush_every: int = 4,
                mode: str = "chained") -> dict:
    store = _fresh_store(persona["id"])
    pending: list[dict] = []
    rounds_out: list[dict] = []
    consolidations: list[dict] = []
    exercised: set[int] = set()
    adds_since = 0
    peak_active = 0

    def flush() -> None:
        nonlocal adds_since, pending, store
        pid = persona["id"]
        ops = with_retry(lambda: provider.extract(pending, store.active()),
                         f"{pid}/extract")
        store.apply_ops(ops)
        adds_since += sum(1 for o in ops
                          if o.get("kind") in ("new", "contradict"))
        pending = []
        if should_consolidate(store, adds_since):
            # record the trigger BEFORE consolidating: after apply_ops the
            # store has changed and the answer is gone
            trigger = ("active" if len(store.active()) > CONSOLIDATE_ACTIVE
                       else "adds")
            cops = with_retry(lambda: provider.consolidate(store.active()),
                              f"{pid}/consolidate")
            store.apply_ops(cops)
            consolidations.append({"trigger": trigger, "n_ops": len(cops)})
            adds_since = 0

    for rd in persona["rounds"]:
        context = rd.get("context") or persona.get("context")
        out = with_retry(
            lambda: _polish(rd["task"], store.active(), context=context),
            f"{persona['id']}/r{rd['n']}")
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
        n_active = len(store.active())
        peak_active = max(peak_active, n_active)
        rounds_out.append({"n": rd["n"], "hit": hit, "misses": misses,
                           "carried": carried,
                           "applicable": len(rd["applicable"]),
                           "store_active": n_active})
        if len(pending) >= flush_every:
            flush()
            if mode == "repaired":
                store = _reset_to_gold(persona, exercised)
    if pending:
        flush()

    second = [r for r in rounds_out if r["n"] >= E2E_SECOND_HALF_FROM]
    applicable = sum(r["applicable"] for r in second)
    carried = sum(r["carried"] for r in second)
    rate = carried / applicable if applicable else 0.0
    round_rate = (sum(r["hit"] for r in second) / len(second)
                  if second else 0.0)
    final = store.list()
    return {"id": persona["id"], "category": "persona", "mode": mode,
            "score": rate, "pass": rate >= E2E_PASS_THRESHOLD,
            "second_half_rate": rate,
            "second_half_round_rate": round_rate,
            "peak_active": peak_active,
            "store_final": {"active": sum(1 for r in final
                                          if r.status == "active"),
                            "retired": sum(1 for r in final
                                           if r.status == "retired")},
            "consolidations": consolidations,
            "rounds": rounds_out}


def run_persona_repeats(persona: dict, provider, repeats: int,
                        mode: str = "chained") -> dict:
    runs = [run_persona(persona, provider, mode=mode) for _ in range(repeats)]
    rates = [r["second_half_rate"] for r in runs]
    mean = sum(rates) / len(rates)
    return {"id": persona["id"], "category": "persona", "mode": mode,
            "score": mean, "pass": mean >= E2E_PASS_THRESHOLD,
            "second_half_rate": mean, "repeats": len(runs), "rates": rates,
            "spread": max(rates) - min(rates),
            "peak_active": max(r["peak_active"] for r in runs),
            "consolidation_triggers": sorted(
                {c["trigger"] for r in runs for c in r["consolidations"]}),
            "runs": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="null")
    ap.add_argument("--repeat", type=int, default=E2E_REPEATS,
                    help="independent runs averaged per persona")
    ap.add_argument("--mode", choices=MODES, default="chained",
                    help="chained = gate metric; repaired = diagnostic")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    provider = PROVIDERS[args.provider]()
    paths = sorted((CASES / "personas").glob("*.json"))
    if len(paths) != E2E_PERSONA_COUNT:
        raise RuntimeError(
            f"expected {E2E_PERSONA_COUNT} personas, globbed {len(paths)} — "
            f"refusing to run a silently smaller suite")
    # Rounds inside a persona are strictly ordered (the store evolves), but
    # the eight personas are independent — parallelise across them only.
    class _P:
        def __init__(self, path):
            self.data = json.loads(Path(path).read_text())
            self.id = self.data["id"]

    personas = [_P(p) for p in paths]
    suite = f"E-{args.mode}" if args.mode != "chained" else "E"
    results = run_items(
        suite,
        personas,
        lambda p: run_persona_repeats(p.data, provider, args.repeat, args.mode),
        workers=args.workers, resume=not args.fresh,
        run_key=hash_cases(str(CASES / "personas")))
    write_snapshot(suite, str(CASES / "personas"), results,
                   expected=len(personas))


if __name__ == "__main__":
    main()
