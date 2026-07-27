"""Why did writer-zh collapse to 0.444 (one repeat scored 0.000)?

The E snapshot records store_size per round but not store contents, and the
sizes are the tell: in the zero repeat the store grew 0 -> 3 -> 7 -> 11 while
the translator carried nothing. writer-zh has three gold rules, so a store of
eleven is eight entries of something else.

This replays writer-zh with the store dumped at every flush, so we can see
whether extraction is emitting near-duplicates of the same three rules
(store bloat) or something else. Note the E harness never calls
provider.consolidate() — there is no dedup path in this suite, so anything
extraction emits accumulates untouched.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from memtranslator.schema import Requirement          # noqa: E402
from memtranslator.translate import translate         # noqa: E402
from bench.runner.providers import PROVIDERS          # noqa: E402
from bench.runner.run_e2e import _apply_ops, _carries  # noqa: E402

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def main():
    persona = json.loads(
        Path("bench/cases/personas/writer-zh.json").read_text())
    provider = PROVIDERS["v1"]()

    print("GOLD REQUIREMENTS:")
    for i, t in enumerate(persona["requirements"]):
        print(f"  [{i}] {t}")

    for rep in range(REPEATS):
        print(f"\n{'='*74}\nREPEAT {rep}\n{'='*74}")
        store: list[Requirement] = []
        pending: list[dict] = []
        for rd in persona["rounds"]:
            active = [r for r in store if r.status == "active"]
            out = translate(rd["task"], active)
            polished = out["polished"] or rd["task"]
            misses = []
            for i in rd["applicable"]:
                ok, _ = _carries(persona["requirements"][i], polished)
                if not ok:
                    misses.append(i)
            print(f"  r{rd['n']:<2} active={len(active):<3} "
                  f"decision={out['decision']:<5} "
                  f"reason={out.get('reason', '-'):<26} "
                  f"miss={misses}")
            if misses:
                pending.append({"type": "edited_diff", "raw": rd["task"],
                                "polished": polished, "final": rd["final"]})
                if rd.get("natural_correction"):
                    pending.append({"type": "natural",
                                    "text": rd["natural_correction"]})
            if len(pending) >= 4:
                ops = provider.extract(pending, store)
                print(f"     FLUSH -> {len(ops)} ops: "
                      f"{[o['kind'] for o in ops]}")
                for o in ops:
                    if o.get("text"):
                        print(f"        {o['kind']:10s} "
                              f"bucket={o.get('bucket', '?'):18s} "
                              f"{o['text'][:70]}")
                _apply_ops(store, ops)
                pending = []
                print(f"     STORE now {len([r for r in store if r.status=='active'])} active:")
                for r in store:
                    if r.status == "active":
                        print(f"        - {r.text[:80]}")


if __name__ == "__main__":
    main()
