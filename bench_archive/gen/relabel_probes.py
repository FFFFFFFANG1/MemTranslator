"""Re-derive every probe's should_fire/must_not_fire with the current
applies_to prompts, WITHOUT regenerating any text.

Utterances, hooks, effects and scope are all untouched — the answer key is
the only thing recomputed. This exists because the applies_to criteria are
the calibration surface (two owner card-rounds have refined them) and a full
fleet rebuild spends ~40 minutes and thousands of calls regenerating text
that was never wrong.

    uv run python -m bench_archive.gen.relabel_probes
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench_archive.gen.build_episode import (ANY, _applies_to, _constraint,
                                     _value_from_dict, domain_fits_task)
from bench_archive.graph.derive import Effect, fold, scope_compatible

EPISODES = Path(__file__).resolve().parents[1] / "cases" / "episodes"


class _Node:
    """Duck-typed stand-in for the Constraint objects _applies_to expects."""

    def __init__(self, n):
        self.cid = n["cid"]
        self.clause = n["clause"]
        self.text = n["text"]
        self.distinctive = n["distinctive"]
        co = n["coords"]
        self.coords = type("C", (), {
            "scope": co["scope"], "binding": co["binding"],
            "key": co["key"]})()


def relabel(path: Path) -> dict:
    ep = json.loads(path.read_text())
    by_cid = {n["cid"]: _Node(n) for n in ep["catalogue"]}
    domains = {n["cid"]: (n.get("atom") or {}).get("domain", "")
               for n in ep["catalogue"]}
    effects = [Effect(seq=e["seq"], kind=e["kind"], cid=e.get("cid") or "",
                      target=e.get("target") or "",
                      targets=tuple(e.get("targets") or ()),
                      delta=e.get("delta") or 0) for e in ep["effects"]]
    changed = total = 0
    for r in ep["rounds"]:
        if not r.get("probe"):
            continue
        st = fold(effects, r["seq"])
        ctx = r["context"]
        bctx = {"app": ctx.get("app"), "task": ctx.get("task"),
                "code_lang": None, "nat_lang": None}
        ok = lambda cid: (
            cid in by_cid
            and scope_compatible(by_cid[cid].coords.scope, bctx)
            and domain_fits_task(domains.get(cid, ""),
                                 ctx.get("task") or ANY))
        alive = [c for c, g in st.items() if g.status == "active" and ok(c)]
        dead = [c for c, g in st.items() if g.status != "active" and ok(c)]
        applies = _applies_to(r["text"], alive + dead, by_cid)
        new_should = sorted(c for c in alive if c in applies)
        new_traps = sorted(c for c in dead if c in applies)
        total += 1
        if new_should != sorted(r.get("should_fire", [])) \
                or new_traps != sorted(r.get("must_not_fire", [])):
            changed += 1
        r["should_fire"], r["must_not_fire"] = new_should, new_traps
        r["may_fire"] = sorted(alive)
    path.write_text(json.dumps(ep, ensure_ascii=False, indent=1))
    return {"episode": ep["id"], "probes": total, "changed": changed,
            "should_fire": sum(len(r.get("should_fire", []))
                               for r in ep["rounds"] if r.get("probe"))}


def main():
    paths = sorted(EPISODES.glob("e-*.json"))
    with ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(relabel, paths):
            print(f"{res['episode']}: {res['changed']}/{res['probes']} "
                  f"probes changed, should_fire now {res['should_fire']}")


if __name__ == "__main__":
    main()
