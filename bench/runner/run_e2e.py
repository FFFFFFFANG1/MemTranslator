"""Suite E: scripted personas, zero-freedom user simulator. The store starts
empty; the only thing allowed to vary between runs is the system under test
(translate + the extraction provider)."""
import argparse
import json
import time
from pathlib import Path

from memtranslator.schema import Requirement
from memtranslator.translate import translate

from bench.runner.config import (CASES, E2E_PASS_THRESHOLD,
                                 E2E_PERSONA_COUNT, E2E_SECOND_HALF_FROM)
from bench.runner.judge import judge
from bench.runner.providers import PROVIDERS
from bench.runner.report import write_snapshot

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


def run_persona(persona: dict, provider, flush_every: int = 4) -> dict:
    store: list[Requirement] = []
    pending: list[dict] = []
    rounds_out = []
    for rd in persona["rounds"]:
        out = _polish(rd["task"], [r for r in store if r.status == "active"])
        polished = out["polished"] or rd["task"]
        misses = []
        for i in rd["applicable"]:
            ok, _flag = _carries(persona["requirements"][i], polished)
            if not ok:
                misses.append(i)
        hit = not misses
        if not hit:
            pending.append({"type": "edited_diff", "raw": rd["task"],
                            "polished": polished, "final": rd["final"]})
            if rd.get("natural_correction"):
                pending.append({"type": "natural",
                                "text": rd["natural_correction"]})
        rounds_out.append({"n": rd["n"], "hit": hit, "misses": misses,
                           "store_size": len(store)})
        if len(pending) >= flush_every:
            _apply_ops(store, provider.extract(pending, store))
            pending = []
    if pending:
        _apply_ops(store, provider.extract(pending, store))
    second = [r for r in rounds_out if r["n"] >= E2E_SECOND_HALF_FROM]
    rate = sum(r["hit"] for r in second) / len(second)
    return {"id": persona["id"], "category": "persona",
            "pass": rate >= E2E_PASS_THRESHOLD, "second_half_rate": rate,
            "rounds": rounds_out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="null")
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
        r = run_persona(persona, provider)
        results.append(r)
        print(f"{persona['id']}: second-half rate "
              f"{r['second_half_rate']:.2f} "
              f"{'PASS' if r['pass'] else 'FAIL'}", flush=True)
    write_snapshot("E", str(CASES / "personas"), results)


if __name__ == "__main__":
    main()
