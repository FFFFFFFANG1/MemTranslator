"""M1 — the smoke-scale run of Suite E's control arms. NO go/no-go.

Originally this was the pre-registered gate that decided whether the 480-item
corpus was worth writing; it judged FAIL and paused M4/M5. The owner withdrew
that gate on 2026-07-28 — both causes of the FAIL turned out to be bench-side
(the `fresh` layout made the ranker unable to lose, and the threshold was
written on SUPPRESS while retrieval quality lives in CARRY). See the ruling box
at the top of `docs/2026-07-28-suite-e-lifecycle-spec.md`.

What it is now: the same arm panel that M6 ships, on a synthetic store instead
of real episodes. Cheap enough to re-run after any change to recall or to the
translator prompt, and to keep the instrument honest before the corpus exists.

    real           the product as shipped: status + scope filter, BM25, cap 32
    no_retire      `real` minus the one status predicate — has a store, has
                   extraction, has retrieval, simply never invalidates. This is
                   the control group for the headline claim ("a system that
                   never retires scores lower on the same cases").
    oracle-arm     only the gold-valid set, uncapped. Ceiling, and a BENCH
                   self-check: if it cannot score high, the case file is broken.
    full_context   no store at all — every prior user turn pasted in raw. The
                   only arm that can answer "is structured memory necessary".
    null-generic   no memory at all, a generic polish instruction. Measures the
                   prior floor: how much of the gold is guessable from the task.

`recency-32`, `null-dump` and `flat-dump` were deleted on 2026-07-28. Reasons
are recorded in the spec's §M6 arm table so they do not get revived: recency-32
only ever answered a product-internal ablation; null-dump was structurally
unable to carry a live rule (its CARRY 0.00 was a construction artifact, not a
finding) and its role passed to `no_retire`; flat-dump was an oracle wearing a
baseline's name, and `oracle-arm` absorbed it.

Detection is a substring test on a CONTRAST WORD, so the experiment stays zero
judge and exactly reproducible. The first version keyed on invented codes
(QX-4417) and measured CARRY 0.00 everywhere: the translator carries the rule
but normalises the code away ("邮件结尾另起一行写备案号 QX-4417" comes back as
"邮件结尾另起一行写备案号"). That is a finding about the plan, not a bug here —
the E-mech band was supposed to score `not_contains(distinctive)` with no judge
in the loop, and distinctive codes do not survive the rewrite. What does survive
is the rule's content, so each superseded/live pair is made semantically
OPPOSED (座机 vs 手机号) and the contrast word is the marker.

Read the two layouts as answering different questions, never as one number:
`fresh` is where the dead-entry trap bites (leakage 0.85; on `aged` it is 0.05,
because both halves of the pair reach the prompt and the model picks the newer
one on its own). `aged` is where retrieval can be measured at all.

Cost ~$0.6 and a few minutes at 8 workers, plus whatever `full_context` adds —
its prompt carries the whole transcript, which is the point of measuring
`mem_chars` alongside the score.

    eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.bashrc)"
    uv run python -m bench_corpus_base.exp.m1_separation [PROBES_PER_CELL]
"""
import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from memtranslator import llm, translate as tr_mod
from memtranslator.bm25 import BM25
from memtranslator.config import (GEN_TEMPERATURE,
                                  GLOBAL_RECALL_MAX_TOKENS, MODELS,
                                  PATCH_OUTPUT_TOKENS)
from memtranslator.recall import _scope_ok
from memtranslator.schema import Requirement

from bench.suites.retry import with_retry

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
# selector arms — differ ONLY in which requirements reach the prompt, and are
# installed by swapping `translate.recall` so that everything downstream stays
# the product's own code
# --------------------------------------------------------------------------

def select_real(reqs, query, context):
    from memtranslator.recall import recall
    return recall(reqs, query=query, context=context)


def select_no_retire(reqs, query, context):
    """`real` with the status predicate removed, and NOTHING else changed.

    Mirrors `recall()` line for line — scope filter, cap, BM25 ranking, the
    created_at re-sort — because `real - no_retire` is meant to isolate the
    lifecycle logic alone. If `recall()` changes, this changes with it; any
    other divergence silently turns the headline gap into a comparison of two
    different retrievers.
    """
    pool = [r for r in reqs
            if r.kind == "requirement" and _scope_ok(r.scope, context)]
    pool.sort(key=lambda r: r.created_at)
    from memtranslator.recall import (requirement_block_tokens,
                                      select_within_token_budget)
    if requirement_block_tokens(pool) <= GLOBAL_RECALL_MAX_TOKENS:
        return pool
    scores = BM25([f"{r.text} {r.key or ''}" for r in pool]).scores(query)
    order = sorted(range(len(pool)),
                   key=lambda i: (-scores[i], -pool[i].created_at))
    picked = select_within_token_budget(
        [pool[index] for index in order], GLOBAL_RECALL_MAX_TOKENS)
    picked.sort(key=lambda r: r.created_at)
    return picked


def select_oracle(reqs, query, context):
    """Everything still valid at this checkpoint, uncapped: the gold set the
    system would recall if retrieval were perfect.

    On this synthetic store that is `status == active` plus the scope filter —
    identical to the arm that used to be called `flat-dump`, which is precisely
    why flat-dump was redundant rather than a baseline (spec §4.2).
    """
    return [r for r in reqs
            if r.status == "active" and r.kind == "requirement"
            and _scope_ok(r.scope, context)]


# --------------------------------------------------------------------------
# pipeline arms — these do not select from the store at all, so they replace
# the whole call instead of swapping the selector
# --------------------------------------------------------------------------

GENERIC_POLISH_SYSTEM = """You are a request polisher sitting between a user and their AI agent.
Rewrite the user's request so the agent knows exactly what is expected: make the implicit delivery expectations explicit (format, length, structure, style, language).

Rules:
1. Never change the core task the user is asking for.
2. The rewrite only ADDS. Every word of the user's original request survives in it.
3. Keep the rewritten request natural, as if the user had typed it themselves, and in the language the user wrote in.
4. Your output is ALWAYS the user's REQUEST, addressed to the agent — never your answer to it.

Output strictly one JSON object, nothing else:
{"decision": "noop"}
or
{"decision": "apply", "hunks": [{"old": "<verbatim snippet>", "new": "<replacement>"}]}"""

FULL_CONTEXT_PREAMBLE = (
    "Below is this user's complete conversation history with you, oldest "
    "first. It is the only record of what they have asked for. Later turns "
    "override earlier ones when they conflict — a preference the user has "
    "since changed or withdrawn must NOT be applied.")


def build_transcript(reqs) -> list[str]:
    """Every requirement rendered as the user turn that introduced it, oldest
    first, dead ones included.

    There is no explicit withdrawal line here: in this store a dead entry is
    superseded by a LATER entry that contradicts it (座机 -> 手机号), so the
    only signal that the old one is gone is that a later turn says the
    opposite. Real episodes also contain explicit retractions ("那条不用了"),
    so this arm has it strictly harder here than it will on Suite E proper —
    worth remembering before reading a low `full_context` SUPPRESS as good news.
    """
    ordered = sorted([r for r in reqs if r.kind == "requirement"],
                     key=lambda r: r.created_at)
    return [r.text for r in ordered]


def _complete_with_block(text, system, block, header):
    """The product's translate() with the memory block swapped out.

    Output budget, temperature, JSON parsing and the preserves_request guard
    are all the product's own functions, so an arm that loses here loses on
    what it put in the prompt, not on plumbing. `style_block` is skipped: this
    store has no style_rule entries, so on the product path it contributes an
    empty string anyway.
    """
    user = f"{header}:\n{block}\n\nUser request:\n{text}\n\nJSON:"
    t0 = time.time()
    raw = llm.complete(MODELS["translator"], system, user,
                       max_tokens=PATCH_OUTPUT_TOKENS,
                       temperature=GEN_TEMPERATURE)
    latency_ms = int((time.time() - t0) * 1000)
    patch, parse_error = tr_mod.parse_patch(raw)
    if patch["decision"] == "apply":
        polished = tr_mod.apply_hunks(text, patch["hunks"])
        if polished is None:
            return {"decision": "noop", "polished": None, "applied_ids": [],
                    "parse_error": True, "latency_ms": latency_ms,
                    "reason": "patch_apply_failed"}
        if not tr_mod.preserves_request(text, polished):
            return {"decision": "noop", "polished": None, "applied_ids": [],
                    "parse_error": parse_error, "latency_ms": latency_ms,
                    "reason": "rewrite_dropped_user_text"}
        return {"decision": "apply", "polished": polished,
                "applied_ids": [], "parse_error": parse_error,
                "latency_ms": latency_ms}
    return {"decision": "noop", "polished": None, "applied_ids": [],
            "parse_error": parse_error, "latency_ms": latency_ms,
            "reason": "unparseable_output" if parse_error else "model_noop"}


def run_full_context(facet, request, reqs, context, *, fair):
    """No store: the raw transcript goes where the requirement block would.

    Two variants, and BOTH are reported (spec §M6). `strict` pastes the
    transcript into the product's own slot unchanged, so the comparison holds
    the prompt fixed. `fair` labels it as conversation history and says that
    later turns win — without that, a loss could just as easily be a prompt
    format artifact as an architecture result, and "you crippled the baseline"
    would be a fair objection.
    """
    turns = build_transcript(reqs)
    block = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(turns))
    if fair:
        block = f"{FULL_CONTEXT_PREAMBLE}\n\n{block}"
        header = "Conversation history"
    else:
        header = "Stored requirements"
    out = _complete_with_block(request, tr_mod.TRANSLATOR_SYSTEM,
                               block, header)
    return out, " ".join(turns), len(turns), block


def run_null_generic(facet, request, reqs, context):
    """No memory at all, and a prompt of OUR OWN writing.

    That last part is why this is a corpus instrument and not a product
    baseline: it must never be plotted against the other arms, or we would be
    entering our own prompt-writing as the control group. Its job is to price
    the prior — a constraint this arm carries is one a generic polisher guesses
    from the task alone, i.e. backbone-contaminated corpus that should be
    dropped. It doubles as the empirical check on the G2 counterfactual gate in
    the generation pipeline, which today is LLM-judged and never verified.
    """
    out = _complete_with_block(request, GENERIC_POLISH_SYSTEM, "(none)",
                               "Stored requirements")
    return out, "", 0, ""


def _selector_arm(select):
    def run(facet, request, reqs, context):
        original = tr_mod.recall
        try:
            tr_mod.recall = lambda requirements, *, query="", context=None: \
                select(requirements, query, context or {})
            out = tr_mod.translate(request, reqs, context=context)
        finally:
            tr_mod.recall = original
        injected = select(reqs, request, context)
        block = tr_mod._requirement_block(injected)
        return out, " ".join(r.text for r in injected), len(injected), block
    return run


ARMS = {
    "real": _selector_arm(select_real),
    "no_retire": _selector_arm(select_no_retire),
    "oracle-arm": _selector_arm(select_oracle),
    "full_context": lambda f, q, r, c: run_full_context(f, q, r, c, fair=False),
    "full_context-fair": lambda f, q, r, c: run_full_context(f, q, r, c,
                                                             fair=True),
    "null-generic": run_null_generic,
}

# --------------------------------------------------------------------------
# one probe
# --------------------------------------------------------------------------

def probe(arm_name, facet, request, reqs):
    """Run one arm on one request and look for the contrast words in the
    rewrite. `mem_chars` is recorded on every arm because score alone would
    lose the argument we actually win: an arm that ties `real` while spending
    an order of magnitude more context has not tied it (spec §M6)."""
    context = {"task": facet.task}
    # the local Anthropic proxy flaps; without this a single dropped
    # connection kills the whole run
    out, blob, n_injected, block = with_retry(
        lambda: ARMS[arm_name](facet, request, reqs, context),
        f"m1/{arm_name}/{facet.name}")

    polished = out["polished"] or ""
    return {
        "arm": arm_name, "facet": facet.name, "request": request,
        "decision": out["decision"], "reason": out.get("reason"),
        "n_injected": n_injected,
        "mem_chars": len(block),
        "est_mem_tokens": tr_mod._estimate_tokens(block) if block else 0,
        "latency_ms": out.get("latency_ms", 0),
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
    the arm getting it right), plus the conditional rates.

    `carry_when_injected` is the column the first two runs did not have, and
    the reason the CARRY weight is still undecided. Marginal CARRY mixes two
    different failures — the selector never put the rule in the prompt, and the
    model had it and did not use it — so a drop across densities cannot be
    attributed. The aged run hinted the second one barely happens
    (per-facet CARRY tracked the injection rate almost exactly: 1.00[1.00],
    0.35[0.35], 0.00[0.00]). If that holds, CARRY is a retrieval metric wearing
    an application metric's name, and the injection rate — deterministic, zero
    LLM, zero variance — is the honest way to measure it.
    """
    carry, _ = rate(rows, "car_live")
    dead_marg, _ = rate(rows, "car_dead")
    oos_marg, _ = rate(rows, "car_oos")
    suppress = 1 - (dead_marg + oos_marg) / 2
    carry_cond, n_live = rate(rows, "car_live", "inj_live")
    dead_cond, n_dead = rate(rows, "car_dead", "inj_dead")
    oos_cond, n_oos = rate(rows, "car_oos", "inj_oos")
    return {
        "n": len(rows),
        "mean_injected": statistics.mean(r["n_injected"] for r in rows),
        "mean_mem_chars": statistics.mean(r["mem_chars"] for r in rows),
        "mean_est_mem_tokens": statistics.mean(
            r["est_mem_tokens"] for r in rows),
        "mean_latency_ms": statistics.mean(r["latency_ms"] for r in rows),
        "carry": carry, "suppress": suppress,
        "live_injection_rate": rate(rows, "inj_live")[0],
        "carry_when_injected": carry_cond, "live_injected_n": n_live,
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
          f"{len(store)-len(active)} retired, "
          f"GLOBAL_RECALL_MAX_TOKENS={GLOBAL_RECALL_MAX_TOKENS}")

    jobs = [(a, f, f.requests[i])
            for a in ARMS for f in FACETS for i in range(args.n)]
    print(f"separation: {len(jobs)} probes "
          f"({len(ARMS)} arms x {len(FACETS)} facets x {args.n})")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(lambda j: probe(j[0], j[1], j[2], store), jobs))

    def fmt(x, w=7):
        return f"{'n/a':>{w}}" if x is None else f"{x:{w}.2f}"

    print(f"\n{'arm':<18} {'inj':>5} {'CARRY':>7} {'C|inj':>7} {'SUPPRESS':>9} "
          f"{'dead↯':>7} {'oos↯':>7} {'dead↯|inj':>10} {'noop':>6} "
          f"{'memtok':>7} {'ms':>6}")
    per_arm = {}
    for a in ARMS:
        s = summarise([r for r in rows if r["arm"] == a])
        per_arm[a] = s
        print(f"{a:<18} {s['mean_injected']:5.1f} {fmt(s['carry'])} "
              f"{fmt(s['carry_when_injected'])} {fmt(s['suppress'], 9)} "
              f"{fmt(s['dead_leak_marginal'])} {fmt(s['oos_leak_marginal'])} "
              f"{fmt(s['dead_leak_when_injected'], 10)} "
              f"{s['noop_rate']:6.2f} {s['mean_est_mem_tokens']:7.0f} "
              f"{s['mean_latency_ms']:6.0f}")

    print("\nper-facet CARRY (live-rule injection rate in brackets). The two "
          "columns\ntracking each other means the score is made by retrieval, "
          "not by whether\nthe model applies what it was given — read the "
          "C|inj column above with it.")
    for arm in ("real", "no_retire", "oracle-arm"):
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

    # Arm-to-arm relations only. There is no verdict here any more, and no
    # threshold that references the product's absolute score: an instrument is
    # validated by whether it separates arms that are known to differ, not by
    # whether the system under test scores well on it. How far the product sits
    # from each baseline is a line in the report, never a gate on the build.
    def gap(a, b, metric):
        x, y = per_arm.get(a, {}).get(metric), per_arm.get(b, {}).get(metric)
        return None if x is None or y is None else x - y

    relations = {
        # the headline claim: a system that never invalidates scores lower
        "lifecycle_value_suppress": gap("real", "no_retire", "suppress"),
        # does structured memory beat pasting the transcript, and at what cost
        "vs_full_context_suppress": gap("real", "full_context", "suppress"),
        "vs_full_context_fair_suppress": gap("real", "full_context-fair",
                                             "suppress"),
        "vs_full_context_carry": gap("real", "full_context", "carry"),
        # DO NOT quote this ratio as the cost argument. This store's transcript
        # is nothing but rule sentences, while a real episode also carries 32
        # plain requests, 8 distractors and every agent turn — so the ratio
        # here understates the real one by a wide and unknown margin. It is a
        # plumbing check that the column exists, not a measurement.
        "mem_token_ratio_full_context": (
            per_arm["full_context"]["mean_est_mem_tokens"]
            / max(1.0, per_arm["real"]["mean_est_mem_tokens"])),
        # how much the product loses to perfect retrieval
        "retrieval_loss_carry": gap("oracle-arm", "real", "carry"),
        # does the trap discriminate at all (read on the fresh layout)
        "dead_leak_when_injected": per_arm["no_retire"][
            "dead_leak_when_injected"],
        # prior floor: gold this arm carries is gold guessable from the task
        "prior_floor_carry": per_arm["null-generic"]["carry"],
    }

    print(f"\n{'='*66}\nARM RELATIONS (no verdict — M1 has no go/no-go)")
    for k, v in relations.items():
        print(f"  {k:<32} {'n/a' if v is None else f'{v:+.2f}'}")
    print("\n  Read `prior_floor_carry` as a corpus signal, not a product one:"
          "\n  null-generic runs a prompt we wrote ourselves, so it prices how"
          "\n  much of the gold a generic polisher guesses from the task alone."
          "\n  Constraints it carries are backbone-contaminated and should be"
          "\n  dropped from the corpus.")

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"M1-{args.layout}-{stamp}.json"
    path.write_text(json.dumps(
        {"at": stamp, "probes_per_cell": args.n,
         "global_recall_max_tokens": GLOBAL_RECALL_MAX_TOKENS,
         "layout": args.layout,
         "per_facet": {a: by_facet(rows, a) for a in ARMS},
         "store": {"total": len(store), "active": len(active)},
         "per_arm": per_arm,
         "dilution": {str(k): v for k, v in dil.items()},
         "relations": relations, "rows": rows},
        ensure_ascii=False, indent=1))
    print(f"\nsnapshot: {path}")


if __name__ == "__main__":
    main()
