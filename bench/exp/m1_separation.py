"""M1 — the pre-registered separation experiment (Suite E go/no-go).

Before writing 480 constraints, find out whether a lifecycle suite can tell the
real system apart from a trivial baseline at all. Four arms differing ONLY in
which requirements reach the translator prompt; everything downstream — prompt,
token budget, preserves_request guard — is the product's own code, because the
arms are installed by swapping `translate.recall`, not by re-implementing it.

    real         the product's recall(): status + scope filter, key ranking, cap 32
    null-dump    no status filter, no scope filter, first 32 by strength
    recency-32   status filter only, newest 32, no scope filter, no ranking
    flat-dump    every active, scope-filtered, no cap

Detection is a substring test on a CONTRAST WORD, so the experiment stays zero
judge and exactly reproducible. The first version keyed on invented codes
(QX-4417) and measured CARRY 0.00 everywhere: the translator carries the rule
but normalises the code away ("邮件结尾另起一行写备案号 QX-4417" comes back as
"邮件结尾另起一行写备案号"). That is a finding about the plan, not a bug here —
the E-mech band was supposed to score `not_contains(distinctive)` with no judge
in the loop, and distinctive codes do not survive the rewrite. What does survive
is the rule's content, so each superseded/live pair is made semantically
OPPOSED (座机 vs 手机号) and the contrast word is the marker.

PRE-REGISTERED, written before the first run:

    PASS  dead-entry leakage >= 0.60   (a dead rule that IS injected gets
                                        carried at least 60% of the time, so
                                        must_not_carry traps discriminate)
      AND real vs recency-32 SUPPRESS gap >= 0.15

    FAIL  the suite cannot separate the system from a baseline that ignores
          lifecycle and scope. Then 480 constraints buy nothing: shrink the
          corpus and spend the budget on invalidation events, or fix the
          product first (scope into the prompt, recall ranking) before
          building the bench.

Cost ~300 haiku calls, roughly $0.6 and a few minutes at 8 workers.

    eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.zshrc)"
    uv run python -m bench.exp.m1_separation [PROBES_PER_CELL]
"""
import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from memtranslator import translate as tr_mod
from memtranslator.config import RECALL_CAP
from memtranslator.recall import _scope_ok
from memtranslator.schema import Requirement

from bench.runner.retry import with_retry

OUT = Path(__file__).resolve().parents[1] / "results"
DENSITIES = (8, 30, 52)          # dilution slope; 52 is the cp-06-like density
CP06 = 52


# --------------------------------------------------------------------------
# synthetic store
# --------------------------------------------------------------------------

@dataclass
class Facet:
    name: str
    task: str
    key: str
    live: str                    # contrast word that SHOULD reach the rewrite
    dead: str                    # word only the superseded rule uses: must NOT
    oos: str                     # word only the out-of-scope rule uses: must NOT
    oos_task: str
    live_text: str
    dead_text: str
    oos_text: str
    requests: list[str] = field(default_factory=list)


FACETS = [
    Facet(
        name="email.signoff", task="email", key="email.format",
        live="手机号", dead="座机", oos="工单号", oos_task="report",
        live_text="邮件结尾只留名字和手机号",
        dead_text="邮件结尾写上部门全称和座机",
        oos_text="报告封面右下角写上工单号",
        requests=[
            "给供应商写封邮件催一下上个月的发票",
            "给房产中介写邮件确认下周看房时间",
            "写封邮件问一下培训报名还开不开放",
            "给客户写邮件说明这次延期的原因",
            "写邮件跟保险公司确认理赔材料收到没有",
            "给楼下咖啡店写邮件问能不能长期供豆",
            "写封邮件请对方把合同扫描件重发一份",
            "给会务组写邮件申请增加一个参会名额",
            "写邮件通知团队下周三例会改到周四",
            "给银行写邮件询问对公账户的手续费标准",
            "写封邮件跟供应商谈一下批量采购的折扣",
            "给物业写邮件报修一下电梯异响",
            "写邮件邀请外部讲师来做一次分享",
            "给编辑写邮件询问稿件排期",
            "写封邮件感谢对方上次提供的数据",
            "给招聘方写邮件确认面试的具体地址",
            "写邮件跟合作方同步一下项目进度",
            "给旅行社写邮件修改出行日期",
            "写封邮件请财务加急处理一笔报销",
            "给学校写邮件申请开一份在读证明",
        ],
    ),
    Facet(
        name="code.header", task="code-write", key="code.format",
        live="作者", dead="版权声明", oos="评审", oos_task="code-review",
        live_text="每个 Python 文件开头只写一行作者注释",
        dead_text="每个 Python 文件开头写完整的版权声明段落",
        oos_text="评审意见按严重程度排序",
        requests=[
            "写个脚本把 csv 里的重复行去掉",
            "写一个函数把嵌套字典拍平",
            "帮我写个脚本批量重命名文件夹里的图片",
            "写个小工具统计目录下各类型文件的数量",
            "写一段代码把 json 转成 markdown 表格",
            "写个脚本定时检查某个网页有没有更新",
            "帮我写个函数做指数退避重试",
            "写一段代码解析日志里的时间戳",
            "写个脚本把两个 csv 按某列合并",
            "帮我写个命令行工具生成随机密码",
            "写一段代码把图片批量压缩到指定大小",
            "写个脚本检测端口有没有被占用",
            "帮我写个函数做简单的 LRU 缓存",
            "写一段代码把文本按句子切分",
            "写个脚本把目录树导出成 markdown",
            "帮我写个工具比较两个 json 的差异",
            "写一段代码做分页读取数据库",
            "写个脚本把 markdown 里的链接都抽出来",
            "帮我写个函数校验邮箱格式",
            "写一段代码统计代码仓库的行数分布",
        ],
    ),
    Facet(
        name="doc.toc", task="report", key="report.format",
        live="一级", dead="三级", oos="收件人", oos_task="email",
        live_text="长文档开头只放一级目录",
        dead_text="长文档开头放到三级的详细目录",
        oos_text="邮件开头先点名收件人",
        requests=[
            "写一份季度服务器容量规划文档",
            "写一份新人入职的环境配置说明",
            "整理一份本月线上故障的复盘文档",
            "写一份数据备份策略的说明文档",
            "写一份团队代码规范文档",
            "整理一份第三方接口的对接说明",
            "写一份测试环境使用指南",
            "写一份季度预算说明文档",
            "整理一份常见问题排查手册",
            "写一份产品灰度发布流程文档",
            "写一份数据库迁移方案文档",
            "整理一份安全审计的自查清单文档",
            "写一份客户培训用的操作手册",
            "写一份年度技术选型评估文档",
            "整理一份监控告警配置说明",
            "写一份跨部门协作流程文档",
            "写一份实习生带教计划文档",
            "整理一份历史需求变更记录文档",
            "写一份容灾演练方案文档",
            "写一份开源合规检查说明文档",
        ],
    ),
]

# Filler dilutes the prompt; none of these may contain a contrast word, or the
# substring test would fire on the wrong rule.
FILLER = [
    ("meeting.format", "会议纪要按时间倒序排列"),
    ("research.format", "调研结论开头先给一句话结论"),
    ("tone.register", "对外沟通一律用敬语"),
    ("length.limit", "摘要控制在 200 字以内"),
    ("citation.style", "引用统一用 APA 格式"),
    ("explanation.depth", "解释技术概念时先给类比"),
    ("comment.language", "代码注释统一用英文"),
    ("language.output", "对外文档用简体中文"),
    ("style.voice", "说明文档用主动语态"),
    ("format.list", "步骤类内容用有序列表"),
]


def build_store(density: int, layout: str = "fresh") -> list[Requirement]:
    """Dead entries are always oldest — that is how supersession leaves them,
    and it is why a head-taking cap picks them up while a tail-taking cap does
    not. That asymmetry is what makes the dead-entry trap work.

    `layout` decides where the LIVE rule sits, and it decides whether ranking
    can show any value at all:

      fresh  live rules newest. recency-32 always keeps them, so a ranker has
             nothing to prove — the first M1 run used this and measured a
             +0.00 gap, which was partly rigged by the construction.
      aged   live rules oldest, buried under `density` newer fillers. Now the
             tail-taking cap drops them and only a ranker that understands the
             query can pull them back. This is where retrieval quality lives.
    """
    reqs: list[Requirement] = []
    t = time.time() - 86_400 * 90

    def add(text, key, status="active", scope=None, bump=3600.0):
        nonlocal t
        t += bump
        r = Requirement(text=text, key=key, scope=scope or {})
        r.created_at = t
        r.updated_at = t
        r.status = status
        reqs.append(r)
        return r

    for f in FACETS:                       # oldest: the superseded predecessors
        add(f.dead_text, f.key, status="retired")
    if layout == "aged":                   # live rules buried under the filler
        for f in FACETS:
            add(f.live_text, f.key)
    for i in range(max(0, density - 2 * len(FACETS))):
        key, text = FILLER[i % len(FILLER)]
        add(f"{text}-{i:02d}", key)
    for f in FACETS:
        add(f.oos_text, f.key, scope={"task": f.oos_task})
        if layout == "fresh":
            add(f.live_text, f.key)
    return reqs


# --------------------------------------------------------------------------
# arms — each returns the list translate() will inject
# --------------------------------------------------------------------------

def arm_real(reqs, query, context):
    from memtranslator.recall import recall
    return recall(reqs, query=query, context=context)


def arm_null_dump(reqs, query, context):
    """Never retires, never checks scope, takes the head by strength. Strength
    is constant 1 on every record (nothing bumps it), so this degenerates to
    insertion order — which is exactly why it picks up the dead entries."""
    pool = [r for r in reqs if r.kind == "requirement"]
    pool.sort(key=lambda r: (-r.strength, r.created_at))
    return pool[:RECALL_CAP]


def arm_recency32(reqs, query, context):
    pool = [r for r in reqs
            if r.status == "active" and r.kind == "requirement"]
    pool.sort(key=lambda r: r.created_at)
    return pool[-RECALL_CAP:]


def arm_flat_dump(reqs, query, context):
    return [r for r in reqs
            if r.status == "active" and r.kind == "requirement"
            and _scope_ok(r.scope, context)]


ARMS = {"real": arm_real, "null-dump": arm_null_dump,
        "recency-32": arm_recency32, "flat-dump": arm_flat_dump}


# --------------------------------------------------------------------------
# one probe
# --------------------------------------------------------------------------

def probe(arm_name, facet, request, reqs):
    """Swap recall for this arm, run the product's own translate, and look for
    the distinctive codes in what came back."""
    selector = ARMS[arm_name]
    context = {"task": facet.task}
    original = tr_mod.recall
    try:
        tr_mod.recall = lambda requirements, *, query="", context=None: \
            selector(requirements, query, context or {})
        # the local Anthropic proxy flaps; without this a single dropped
        # connection kills the whole 240-probe run
        out = with_retry(lambda: tr_mod.translate(request, reqs,
                                                  context=context),
                         f"m1/{arm_name}/{facet.name}")
    finally:
        tr_mod.recall = original

    injected = {r.id: r.text for r in selector(reqs, request, context)}
    blob = " ".join(injected.values())
    polished = out["polished"] or ""
    return {
        "arm": arm_name, "facet": facet.name, "request": request,
        "decision": out["decision"], "reason": out.get("reason"),
        "n_injected": len(injected),
        "inj_live": facet.live in blob, "car_live": facet.live in polished,
        "inj_dead": facet.dead in blob, "car_dead": facet.dead in polished,
        "inj_oos": facet.oos in blob, "car_oos": facet.oos in polished,
    }


def rate(rows, num, den=None):
    hit = sum(1 for r in rows if r[num])
    pool = [r for r in rows if r[den]] if den else rows
    if den:
        hit = sum(1 for r in pool if r[num])
    return (hit / len(pool)) if pool else None, len(pool)


def summarise(rows):
    """CARRY and SUPPRESS as the suite would score them (marginal: a trap the
    arm never injected still counts as suppressed, because that is genuinely
    the arm getting it right), plus the conditional leakage rates that say
    whether the traps discriminate at all."""
    carry, _ = rate(rows, "car_live")
    dead_marg, _ = rate(rows, "car_dead")
    oos_marg, _ = rate(rows, "car_oos")
    suppress = 1 - (dead_marg + oos_marg) / 2
    dead_cond, n_dead = rate(rows, "car_dead", "inj_dead")
    oos_cond, n_oos = rate(rows, "car_oos", "inj_oos")
    return {
        "n": len(rows),
        "mean_injected": statistics.mean(r["n_injected"] for r in rows),
        "carry": carry, "suppress": suppress,
        "dead_leak_marginal": dead_marg, "oos_leak_marginal": oos_marg,
        "dead_leak_when_injected": dead_cond, "dead_injected_n": n_dead,
        "oos_leak_when_injected": oos_cond, "oos_injected_n": n_oos,
        "noop_rate": sum(1 for r in rows if r["decision"] == "noop") / len(rows),
    }


def by_facet(rows, arm):
    out = {}
    for f in FACETS:
        sub = [r for r in rows if r["arm"] == arm and r["facet"] == f.name]
        if sub:
            out[f.name] = {
                "carry": sum(r["car_live"] for r in sub) / len(sub),
                "live_injected": sum(r["inj_live"] for r in sub) / len(sub),
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="?", type=int, default=20,
                    help="probes per cell (facet x arm)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--layout", choices=("fresh", "aged"), default="fresh",
                    help="where the live rule sits in the store; see build_store")
    args = ap.parse_args()

    store = build_store(CP06, args.layout)
    active = [r for r in store if r.status == "active"]
    print(f"layout={args.layout}  store: {len(store)} entries, {len(active)} active, "
          f"{len(store)-len(active)} retired, RECALL_CAP={RECALL_CAP}")

    jobs = [(a, f, f.requests[i])
            for a in ARMS for f in FACETS for i in range(args.n)]
    print(f"separation: {len(jobs)} probes "
          f"({len(ARMS)} arms x {len(FACETS)} facets x {args.n})")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(lambda j: probe(j[0], j[1], j[2], store), jobs))

    print(f"\n{'arm':<12} {'inj':>5} {'CARRY':>7} {'SUPPRESS':>9} "
          f"{'dead↯':>7} {'oos↯':>7} {'dead↯|inj':>10} {'noop':>6}")
    per_arm = {}
    for a in ARMS:
        s = summarise([r for r in rows if r["arm"] == a])
        per_arm[a] = s
        d = s["dead_leak_when_injected"]
        print(f"{a:<12} {s['mean_injected']:5.1f} {s['carry']:7.2f} "
              f"{s['suppress']:9.2f} {s['dead_leak_marginal']:7.2f} "
              f"{s['oos_leak_marginal']:7.2f} "
              f"{('n/a' if d is None else f'{d:.2f}'):>10} "
              f"{s['noop_rate']:6.2f}")

    print("\nper-facet CARRY (live-rule injection rate in brackets) — this is "
          "where\nkey-lexicon coverage shows up: recall() can only rank a rule "
          "in if one of\nthe 14 roots in _KEY_LEXICON appears in the query")
    for arm in ("real", "recency-32"):
        bf = by_facet(rows, arm)
        cells = "  ".join(
            f"{k.split('.')[0]}: {v['carry']:.2f} [{v['live_injected']:.2f}]"
            for k, v in bf.items())
        print(f"  {arm:<11} {cells}")

    # dilution: the real arm at three densities
    print("\ndilution (real arm):")
    dil = {}
    for dens in DENSITIES:
        s2 = build_store(dens, args.layout)
        djobs = [(f, f.requests[i]) for f in FACETS for i in range(args.n)]
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            drows = list(ex.map(lambda j: probe("real", j[0], j[1], s2), djobs))
        d = summarise(drows)
        dil[dens] = d
        print(f"  density {dens:3d}  injected {d['mean_injected']:4.1f}  "
              f"CARRY {d['carry']:.2f}")

    dead_cond = per_arm["null-dump"]["dead_leak_when_injected"]
    gap = per_arm["real"]["suppress"] - per_arm["recency-32"]["suppress"]
    ok_dead = dead_cond is not None and dead_cond >= 0.60
    ok_gap = gap >= 0.15
    verdict = "PASS" if (ok_dead and ok_gap) else "FAIL"

    print(f"\n{'='*66}\nPRE-REGISTERED VERDICT: {verdict}")
    print(f"  dead-entry leakage when injected = "
          f"{'n/a' if dead_cond is None else f'{dead_cond:.2f}'} "
          f"(threshold >= 0.60) -> {'ok' if ok_dead else 'MISS'}")
    print(f"  real - recency-32 SUPPRESS gap   = {gap:+.2f} "
          f"(threshold >= 0.15) -> {'ok' if ok_gap else 'MISS'}")
    if verdict == "FAIL":
        print("\n  Do not write 480 constraints. Either shrink the corpus and"
              "\n  spend the budget on invalidation events and dead-entry"
              "\n  probes, or fix the product first (scope into the prompt,"
              "\n  recall ranking) and re-run this experiment.")

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"M1-{args.layout}-{stamp}.json"
    path.write_text(json.dumps(
        {"at": stamp, "probes_per_cell": args.n, "recall_cap": RECALL_CAP,
         "layout": args.layout,
         "per_facet": {a: by_facet(rows, a) for a in ARMS},
         "store": {"total": len(store), "active": len(active)},
         "per_arm": per_arm,
         "dilution": {str(k): v for k, v in dil.items()},
         "verdict": verdict, "dead_leak_when_injected": dead_cond,
         "suppress_gap": gap, "rows": rows},
        ensure_ascii=False, indent=1))
    print(f"\nsnapshot: {path}")


if __name__ == "__main__":
    main()
