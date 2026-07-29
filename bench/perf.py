"""Performance suite: the archive's realistic user turns, replayed through
the REAL write path, probing the read path at growing store sizes.

Canary design, second iteration. The first run planted one fixed email-cap
canary into every episode and its death conflated two different things: one
persona had genuinely stated its own email cap (legitimate supersession —
the canary was competing with real preferences), and two others had a
postmortem word-cap rule kill the email rule (cross-facet mistargeting).
The bench-side confound is fixed by CONSTRUCTION now: each episode's turns
are scanned mechanically and the canary is chosen from a pool so that its
facet vocabulary NEVER appears in that user's history. A canary this user
never talked about cannot be legitimately superseded — if it dies, the
write path killed a rule without any user signal, and the store file is the
minimal repro.

Measured per snapshot (labelled with the ACTUAL active count, not the
planned size — one flush can jump past a planned threshold):
- carry@alive: canary woven into its probe, conditioned on it being alive
- spurious kills: canary dead (by construction illegitimate), successor kept
- noop rate over the episode's own probe tasks
- latency and injected-block chars per translate call

    uv run python -m bench.perf --episodes e-01,e-03,e-05,e-09
"""
import argparse
import json
import time
import uuid
from pathlib import Path

from memtranslator.store import Store
from memtranslator.translate import translate

from bench_archive.runner.config import RUN_DIR
from bench_archive.runner.providers import V1Provider
from bench_archive.runner.retry import with_retry

ARCHIVE = Path(__file__).resolve().parents[1] / "bench_archive"
BENCH = Path(__file__).resolve().parent

# Facet-object vocabulary is what must be absent from the episode's turns.
# Attributes (length, order, format) deliberately excluded from the scan:
# the observed mistargeting travelled along shared ATTRIBUTES, and we want
# to keep exactly that pathway open to measurement while closing the
# same-facet pathway that made kills legitimate.
CANARIES = [
    {"text": "我让你写的邮件一律不超过78词",
     "probe": "帮我写封邮件给供应商，催一下上个月的发票",
     "anchor": "78",
     "vocab": ["邮件", "email", "mail ", "写信"]},
    {"text": "会议纪要一律按时间倒序排列",
     "probe": "帮我把今天站会的记录整理成会议纪要",
     "anchor": "倒序",
     "vocab": ["会议", "纪要", "meeting", "minutes", "standup", "站会"]},
    {"text": "引用文献一律用 APA 格式标注",
     "probe": "帮我把这篇综述末尾的参考文献整理一下",
     "anchor": "APA",
     "vocab": ["引用", "文献", "citation", "reference", "cite", "参考"]},
    {"text": "导出的文件一律用小写加连字符命名",
     "probe": "帮我给这批要导出的报表文件起一套名字",
     "anchor": "连字符",
     "vocab": ["文件名", "filename", "file name", "命名", "naming"]},
    {"text": "报销单里的金额一律保留两位小数",
     "probe": "帮我把这次出差的报销单整理一下，打车和住宿分开列",
     "anchor": "两位小数",
     "vocab": ["报销", "expense", "invoice", "发票", "reimburs"]},
    {"text": "翻译的时候一律保留原文里的英文术语不译",
     "probe": "帮我把这段产品介绍翻译成中文",
     "anchor": "术语",
     "vocab": ["翻译", "translat", "译文", "译成"]},
    {"text": "打包发我的压缩文件一律用 zip 格式",
     "probe": "帮我把这批日志文件打个包发我",
     "anchor": "zip",
     "vocab": ["压缩", "打包", "zip", "tar", "archive"]},
]


def pick_canary(ep: dict) -> dict | None:
    """First canary whose facet vocabulary never occurs in this user's
    history — collision-free by mechanical scan, not by hope."""
    blob = " ".join(r["text"] for r in ep["rounds"]).lower()
    for c in CANARIES:
        if not any(v.lower() in blob for v in c["vocab"]):
            return c
    return None


def canary_state(store: Store, canary: dict) -> dict:
    for r in store.list():
        if canary["anchor"] in r.text or r.text == canary["text"]:
            if r.status == "active":
                return {"alive": True}
            heirs = [h.text[:70] for h in store.list()
                     if h.supersedes == r.id]
            return {"alive": False, "successor": heirs[0] if heirs else None}
    return {"alive": False, "successor": "(gone entirely)"}


def probe_at(store: Store, canary: dict, probes: list[str],
             epid: str) -> dict:
    outs = []
    for task in [canary["probe"]] + probes:
        t0 = time.time()
        out = with_retry(lambda: translate(task, store.active()),
                         f"perf/{epid}/probe")
        outs.append({"decision": out["decision"],
                     "polished": out["polished"],
                     "ms": int((time.time() - t0) * 1000)})
    cst = canary_state(store, canary)
    carried = bool(outs[0]["polished"]) \
        and canary["anchor"] in outs[0]["polished"]
    return {"size": len(store.active()),
            "canary": cst,
            "canary_carried": carried,
            "noop_rate": sum(1 for o in outs[1:]
                             if o["decision"] == "noop")
            / max(1, len(outs) - 1),
            "mean_ms": sum(o["ms"] for o in outs) // len(outs),
            "block_chars": sum(len(x.text) for x in store.active())}


def replay_episode(epid: str, sizes: list[int], flush_every: int = 4) -> dict:
    ep = json.loads((ARCHIVE / "cases" / "episodes" / f"{epid}.json")
                    .read_text())
    canary = pick_canary(ep)
    if canary is None:
        return {"episode": epid, "skipped": "no collision-free canary"}
    probes = [r["text"] for r in ep["rounds"] if r.get("probe")][:4]
    d = RUN_DIR / "perf-stores"
    d.mkdir(parents=True, exist_ok=True)
    store = Store(d / f"{epid}-{uuid.uuid4().hex[:8]}.jsonl")
    store.add(canary["text"], source="manual")      # planted first = oldest
    provider = V1Provider()

    pending, rows, taken = [], [], set()
    for r in ep["rounds"]:
        pending.append({"type": "natural", "text": r["text"]})
        if len(pending) >= flush_every:
            ops = with_retry(lambda: provider.extract(pending,
                                                      store.active()),
                             f"perf/{epid}/extract")
            store.apply_ops(ops)
            pending = []
            n = len(store.active())
            due = [s for s in sizes if s <= n and s not in taken]
            if due:
                taken.update(due)
                rows.append(probe_at(store, canary, probes, epid))
        if taken >= set(sizes):
            break
    n = len(store.active())
    if not rows or rows[-1]["size"] != n:
        rows.append(probe_at(store, canary, probes, epid))
    return {"episode": epid, "canary": canary["text"], "rows": rows,
            "final_active": n,
            "final_retired": sum(1 for x in store.list()
                                 if x.status == "retired")}


def bucket(size: int) -> str:
    for lo, hi in ((0, 6), (7, 12), (13, 20), (21, 28), (29, 99)):
        if lo <= size <= hi:
            return f"{lo}-{hi}"
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="e-01,e-03,e-05,e-09")
    ap.add_argument("--sizes", default="4,8,16,24,32")
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]
    eps = [e.strip() for e in args.episodes.split(",")]

    results = [replay_episode(e, sizes) for e in eps]

    print(f"\n{'bucket':>7} {'carry@alive':>12} {'kills':>6} {'noop%':>6} "
          f"{'ms':>6} {'chars':>7}")
    by_b: dict[str, list] = {}
    for r in results:
        for row in r.get("rows", []):
            by_b.setdefault(bucket(row["size"]), []).append(row)
    for b in sorted(by_b, key=lambda x: int(x.split("-")[0])):
        rows = by_b[b]
        alive = [x for x in rows if x["canary"]["alive"]]
        carried = sum(1 for x in alive if x["canary_carried"])
        kills = sum(1 for x in rows if not x["canary"]["alive"])
        print(f"{b:>7} {carried}/{len(alive):>2}@alive {kills:>6} "
              f"{100 * sum(x['noop_rate'] for x in rows) / len(rows):>5.0f} "
              f"{sum(x['mean_ms'] for x in rows) // len(rows):>6} "
              f"{sum(x['block_chars'] for x in rows) // len(rows):>7}")
    for r in results:
        for row in r.get("rows", []):
            if not row["canary"]["alive"]:
                print(f"  KILL in {r['episode']} at size {row['size']}: "
                      f"canary superseded by: {row['canary']['successor']}")
    out = BENCH / "perf_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
