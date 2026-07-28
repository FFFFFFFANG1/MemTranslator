"""Aggregate the E1 fleet: latest snapshot per episode → suite score with an
episode-cluster bootstrap CI, plus the arm panel pooled across episodes.

The CI resamples EPISODES (the cluster unit), not probes: probes within an
episode share a persona, a store history and a generation seed, and treating
them as independent would shrink the interval by roughly sqrt(cluster size)
for free. 12 clusters is what we have; the interval is honest about that.

No gate here. Per spec §M6 the fleet produces reportable numbers and a CI —
thresholds are an owner decision (§M7), not a side effect of an aggregator.

    uv run python -m bench.runner.report_e1
"""
import json
import random

from bench.runner.config import RESULTS
from bench.runner.report import latest

EPISODES = [f"e-{i:02d}" for i in range(1, 13)]
BOOT = 2000


def main():
    rows = []
    for ep in EPISODES:
        snap = latest(f"E1-{ep}")
        if snap is None:
            print(f"{ep}: no snapshot")
            continue
        r = snap["results"][0]
        rows.append({"episode": ep, "score": r["score"],
                     "carry": r.get("carry"), "suppress": r.get("suppress"),
                     "state": r.get("state"), "arms": snap.get("arms", {}),
                     "peak_sut_active": snap.get("peak_sut_active"),
                     "consolidations": snap.get("consolidations", [])})
    if not rows:
        print("nothing to aggregate")
        return

    scores = [r["score"] for r in rows]
    mean = sum(scores) / len(scores)
    rng = random.Random(17)
    boots = []
    for _ in range(BOOT):
        sample = [rng.choice(scores) for _ in scores]
        boots.append(sum(sample) / len(sample))
    boots.sort()
    lo, hi = boots[int(0.025 * BOOT)], boots[int(0.975 * BOOT)]

    print(f"E1 fleet: {len(rows)} episodes")
    for r in rows:
        f = lambda x: "n/a" if x is None else f"{x:.2f}"
        print(f"  {r['episode']}  score {r['score']:.3f}  "
              f"carry {f(r['carry'])}  suppress {f(r['suppress'])}  "
              f"state {f(r['state'])}  peak {r['peak_sut_active']}")
    print(f"\nsuite score: {mean:.3f}   "
          f"95% CI [{lo:.3f}, {hi:.3f}]  half-width {((hi - lo) / 2):.3f}")

    arms: dict[str, dict] = {}
    for r in rows:
        for arm, s in r["arms"].items():
            a = arms.setdefault(arm, {"carry": [], "suppress": [],
                                      "chars": [], "ms": []})
            if s.get("carry") is not None:
                a["carry"].append(s["carry"])
            if s.get("suppress") is not None:
                a["suppress"].append(s["suppress"])
            a["chars"].append(s.get("mean_block_chars", 0))
            a["ms"].append(s.get("mean_latency_ms", 0))
    print(f"\n{'arm':<14} {'CARRY':>7} {'SUPPRESS':>9} {'chars':>7} {'ms':>6}")
    for arm, a in arms.items():
        m = lambda v: sum(v) / len(v) if v else None
        f = lambda x: "  n/a" if x is None else f"{x:.2f}"
        print(f"{arm:<14} {f(m(a['carry'])):>7} {f(m(a['suppress'])):>9} "
              f"{m(a['chars']):7.0f} {m(a['ms']):6.0f}")
    trig = [c["trigger"] for r in rows for c in r["consolidations"]]
    print(f"\nconsolidation triggers across the fleet: "
          f"{ {t: trig.count(t) for t in set(trig)} or 'none fired'}")
    print("note: null-generic is a corpus instrument, not a product "
          "baseline; full_context comparisons must cite chars/ms alongside "
          "scores")


if __name__ == "__main__":
    main()
