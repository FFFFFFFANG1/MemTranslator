"""Scale / safety instruments shared by the fused E1+perf lifecycle run.

Canary planting is optional on the same chained store: gold CARRY/SUPPRESS/
STATE score against ground-truth requirement ids, so a planted entry does not enter
those numerators; it can still dilute extraction, which is why the fused
runner exposes ``--canary`` / ``--no-canary``.
"""
from memtranslator.store import Store
from memtranslator.translate import translate

from bench.suites.retry import with_retry

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
    blob = " ".join(
        turn["user_input"] for turn in ep["user_turns"]).lower()
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


def sample_instrument(store: Store, canary: dict | None, probes: list[str],
                      epid: str) -> dict:
    """One size-bucket sample: canary carry (if planted) + probe noop/latency."""
    import time
    tasks = ([canary["probe"]] if canary else []) + probes
    outs = []
    for task in tasks:
        t0 = time.time()
        out = with_retry(lambda t=task: translate(t, store.active()),
                         f"lifecycle/{epid}/probe")
        outs.append({"decision": out["decision"],
                     "polished": out["polished"],
                     "ms": int((time.time() - t0) * 1000)})
    cst = canary_state(store, canary) if canary else {"alive": False}
    carried = False
    if canary and outs:
        carried = bool(outs[0]["polished"]) \
            and canary["anchor"] in outs[0]["polished"]
    probe_outs = outs[1:] if canary else outs
    return {
        "size": len(store.active()),
        "canary": cst,
        "canary_carried": carried,
        "noop_rate": (sum(1 for o in probe_outs if o["decision"] == "noop")
                      / max(1, len(probe_outs))),
        "mean_ms": sum(o["ms"] for o in outs) // max(1, len(outs)),
        "block_chars": sum(len(x.text) for x in store.active()),
    }


def size_bucket(size: int) -> str:
    for lo, hi in ((0, 6), (7, 12), (13, 20), (21, 28), (29, 99)):
        if lo <= size <= hi:
            return f"{lo}-{hi}"
    return "?"
