# Bench Plan：第一版验收基准（v1-acceptance bench）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建一个小规模、语义透明的 bench，作为"第一版面向用户效果"的验收标尺：**总分 ≥ 80% ⇔ 第一版够好，可以面向用户**。本分支只做 bench（数据 + harness + 报告），不改产品代码（`src/` 只读）。

**Architecture:** 三个 suite 对着第一版对用户的三个可感知承诺——**T**（translate：热键改写靠谱）、**L**（learn：从纠正与编辑 diff 里学对 requirement）、**E**（end-to-end：多轮交互后越来越少需要纠正）。T 直接调 `memtranslator.translate`（v0 已有，立即可跑出真实分）；L/E 通过 `ExtractionProvider` 接口对接尚未实现的 v1 管线（bench 先行，v1 落地后接入拿真分）。判分机械 checker 优先，软约束用逐判据二值 LLM judge。

**Tech Stack:** 现有 uv 项目扩展；顶层 `bench/` 包（不进 wheel）；judge 复用 `memtranslator.llm.complete`；零新依赖。

---

## 0. 设计契约（80% 的语义怎么落进数据与分数）

北极星是 anchor §8：小规模、自建/零散收集 delivery case、不刷榜。80% 这个数字要有意义，必须同时钉死三件事：

**(a) 分数的每一分都对应用户可感知的行为。**

| Suite | 用户承诺 | 权重 | 现在能跑吗 |
|---|---|---|---|
| **T** translate | 「⌘E 该改的改对、不该改的不动、不毁我的话」 | 0.4 | ✅ v0 oracle 即真实分 |
| **L** learn | 「我纠正过的事它学得进去，且不乱学」 | 0.3 | harness 就绪，等 v1 接入 |
| **E** e2e | 「用两周后，重复纠正明显变少」 | 0.3 | harness 就绪，等 v1 接入 |

T 权重最高：它是每一次热键的直接体感，且过度应用（乱改用户的话）是第一版最伤信任的失败模式。

**(b) 难度校准在"日常真实会发生"，不收 adversarial 长尾。** 每个 case 进库前过一条审核判据：*"这个 case 若 fail，真实用户会恼火吗？"* 答不上来的 case 不进库。80% gate 的前提是 case 分布贴近日常使用，否则数字与"用户觉得够好"脱钩。

**(c) 聚合方式防偏科刷分。** suite 内先按 category 算 pass 率再取 macro 平均（category 等权），suite 间按上表加权。防止 noop 类 case 全对撑分数。

```
suite_score = mean(category_pass_rate)          # category 等权 macro
overall     = 0.4·T + 0.3·L + 0.3·E
gate        = overall ≥ 0.80  且  每个 suite ≥ 0.70     # 拍板点 1
```

**边界与产品一致：** T/E 判"约束是否被正确**编入请求文本**"，不判下游产出是否满足约束——下游 agent 不是我们的产品面（anchor §2.2，下游只执行）。机械 strength 规则（accepted +1 / reverted −1）是确定性代码，归产品单测，不占 bench。

**规模（anchor §8「小」）：** T 60 case（6 类 × 10）、L 36 case（6 类 × 6）、E 8 persona × 16 轮。全量一跑估 <$10（§9 成本表）。

---

## 1. 目录与运行方式

```
bench/
  README.md                 # bench 契约：gate 定义、当前水位、怎么跑（Task 0 建，Task 10 定稿）
  cases/
    translate/cases.jsonl   # Suite T
    extraction/cases.jsonl  # Suite L
    personas/*.json         # Suite E，一个 persona 一个文件
  gen/
    prompts.md              # case 扩展生成 prompt 全文 + 人工审核 checklist
  runner/
    __init__.py
    config.py               # judge 模型、路径、阈值
    schema.py               # case dataclass + JSONL loader
    checkers.py             # 机械判据 registry
    judge.py                # 二值 LLM judge
    providers.py            # ExtractionProvider 协议 + Null / Reference 实现
    run_translate.py        # Suite T
    run_extraction.py       # Suite L
    run_e2e.py              # Suite E
    report.py               # 聚合 + gate 判定 + results/ 快照
  results/                  # gitignored，每次 run 落 JSON 快照
conftest.py                 # 根级空文件：pytest 把根目录进 sys.path，tests/ 能 import bench
tests/test_bench_*.py       # harness 单测，FakeLLM/monkeypatch 惯例与项目一致
```

运行（都从项目根，`python -m` 使 cwd 进 sys.path，故 bench 无需安装）：

```bash
source ~/.zshrc                                   # ANTHROPIC_API_KEY
uv run python -m bench.runner.run_translate       # Suite T → results/
uv run python -m bench.runner.run_extraction --provider null|reference
uv run python -m bench.runner.run_e2e --provider null|reference
uv run python -m bench.runner.report              # 读最新 results，出总分与 gate
```

复现性：case 落盘进 git；LLM 全部 temperature 0（judge 与 translator 均走 `llm.complete`，anthropic SDK 默认 temperature=1.0，judge call 需显式传——见 Task 3 对 `complete` 的包装）；每次 run 的 results 快照带 model id + case 文件 hash + 时间戳。

---

## 2. 评分协议

**每 case 三层判据，全过才 pass（二值，无部分分）：**

1. **decision 层（机械）**：`decision` 与期望一致；apply 时 `applied_ids` ⊇ 期望命中集。期望值 `any` 表示 apply/noop 皆可（例外类 case，见 §4 category 4），此层自动过。
2. **faithfulness 层（机械）**：case 声明的关键词保留（`contains_all`）、语言保持（`same_language`）等。
3. **constraint 层（judge，逐判据一 call，二值）**：apply case 由 runner 自动生成三类判据——每条期望命中的 requirement 生成「polished 请求显式携带了该约束」；固定一条「未发明清单外的新约束」；固定一条「核心任务未被改变」。case 可另带专属 judge 判据。

**judge 纪律：** 强模型（拍板点 2，默认 `claude-opus-4-8`），temperature 0，一判据一 call（窄题化），输出 `{"verdict": "yes"|"no", "reason": ...}`；parse 失败按 fail 计入并打 flag，报告晒 parse 失败率。judge 可信度由 Task 9 的人工抽检背书（30 条一致率 ≥90%，否则改 prompt 重跑）。

**L suite 判定：** provider 输出 ops 与期望 ops 对齐——kind 机械比对；文本用 judge 判语义等价（「提取条目 R 是否表达了 gist G」）；期望为空的 case（noise-reject）出任何 op 即 fail。pass = 期望全命中 + 零违规误提。

**E suite 判定：** 每轮对 persona 的 applicable requirement 逐条 judge polished 是否携带；persona 分数 = 后半程（9–16 轮）携带率；persona pass ⇔ 后半程携带率 ≥ 0.8。

---

## Task 0: 分支骨架 + bench 契约文档

**Files:**
- Create: `bench/README.md`、`bench/runner/__init__.py`（空）、`bench/__init__.py`（空）、`conftest.py`（根级，空）
- Modify: `.gitignore`

- [ ] **Step 1: 建目录与空包**

```bash
cd "/Users/siriux/Library/Mobile Documents/com~apple~CloudDocs/Documents/Codes/Projects/MemTranslator"
mkdir -p bench/cases/translate bench/cases/extraction bench/cases/personas bench/gen bench/runner bench/results
touch bench/__init__.py bench/runner/__init__.py conftest.py
```

- [ ] **Step 2: `.gitignore` 追加一行**

```
bench/results/
```

- [ ] **Step 3: 写 `bench/README.md`**

```markdown
# MemTranslator Bench — v1 acceptance

**The contract: overall ≥ 80% ⇔ the first user-facing release is good enough.**
Scores are weighted macro averages over three suites (T 0.4 / L 0.3 / E 0.3),
each category equally weighted inside its suite; gate additionally requires
every suite ≥ 70%. Cases are calibrated to everyday usage — if a case failing
would not annoy a real user, it does not belong here (anchor §8: small,
hand-curated, no leaderboard chasing).

| Suite | promise to the user | runnable today |
|---|---|---|
| T translate | polish applies the right constraints, never touches unrelated input | yes (v0 oracle) |
| L learn     | corrections and edit diffs become requirements; noise never does    | via ExtractionProvider (v1) |
| E e2e       | repeated corrections drop off after real use                        | via ExtractionProvider (v1) |

## Run

    source ~/.zshrc
    uv run python -m bench.runner.run_translate
    uv run python -m bench.runner.run_extraction --provider reference
    uv run python -m bench.runner.run_e2e --provider reference
    uv run python -m bench.runner.report

## Current water line

(filled by Task 5 / Task 9 runs)
```

- [ ] **Step 4: Commit**

```bash
git add bench .gitignore conftest.py
git commit -m "[bench] Scaffold bench package and score contract"
```

---

## Task 1: case schema + loader

**Files:**
- Create: `bench/runner/schema.py`
- Test: `tests/test_bench_schema.py`

- [ ] **Step 1: 失败测试**

```python
# tests/test_bench_schema.py
import json

from bench.runner.schema import Check, TranslateCase, load_translate_cases


def test_load_translate_cases(tmp_path):
    p = tmp_path / "cases.jsonl"
    p.write_text(json.dumps({
        "id": "t-x-001", "category": "apply-single", "source": "handwritten",
        "requirements": ["Emails must stay under 120 words."],
        "input": "帮我给房东写封邮件",
        "expect_decision": "apply", "must_apply": [0],
        "checks": [{"kind": "mech", "name": "contains_all",
                    "args": {"keywords": ["房东"]}}],
    }, ensure_ascii=False) + "\n")
    cases = load_translate_cases(p)
    assert len(cases) == 1
    c = cases[0]
    assert isinstance(c, TranslateCase) and c.must_apply == [0]
    assert c.checks[0] == Check(kind="mech", name="contains_all",
                                args={"keywords": ["房东"]})


def test_expect_decision_validated(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"id": "b", "category": "c", "source": "s", '
                 '"requirements": [], "input": "x", '
                 '"expect_decision": "maybe", "must_apply": [], "checks": []}')
    try:
        load_translate_cases(p)
        raise AssertionError("should reject unknown expect_decision")
    except ValueError:
        pass


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "dup.jsonl"
    row = ('{"id": "same", "category": "c", "source": "s", "requirements": [],'
           ' "input": "x", "expect_decision": "noop", "must_apply": [],'
           ' "checks": []}\n')
    p.write_text(row + row)
    try:
        load_translate_cases(p)
        raise AssertionError("should reject duplicate ids")
    except ValueError:
        pass
```

- [ ] **Step 2: 确认失败**

```bash
/opt/homebrew/bin/uv run pytest tests/test_bench_schema.py -q
```
Expected: FAIL（ModuleNotFoundError: bench.runner.schema）。

- [ ] **Step 3: 写 `bench/runner/schema.py`**

```python
"""Bench case schemas + JSONL loaders. Cases live in git; loaders validate
hard so a malformed case fails the run, never silently skews the score."""
from dataclasses import dataclass, field
from pathlib import Path
import json

EXPECT_DECISIONS = ("apply", "noop", "any")


@dataclass(frozen=True)
class Check:
    kind: str          # "mech" | "judge"
    name: str          # mech: registry key; judge: short label
    args: dict = field(default_factory=dict, hash=False, compare=True)

    def __post_init__(self):
        if self.kind not in ("mech", "judge"):
            raise ValueError(f"unknown check kind: {self.kind}")


@dataclass
class TranslateCase:
    id: str
    category: str
    source: str                  # handwritten | generated | prefeval
    requirements: list[str]
    input: str
    expect_decision: str         # apply | noop | any
    must_apply: list[int]        # indices into requirements
    checks: list[Check]


@dataclass
class ExtractionCase:
    id: str
    category: str
    source: str
    existing: list[str]          # requirement texts already in the store
    events: list[dict]           # {"type": "natural", "text": ...} or
                                 # {"type": "edited_diff", "raw":, "polished":, "final":}
    expect_ops: list[dict]       # {"kind": "new|reinforce|contradict",
                                 #  "target": int|None (index into existing),
                                 #  "gist": "..."}; [] means must-not-extract


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]


def _check_unique_ids(cases):
    seen = set()
    for c in cases:
        if c.id in seen:
            raise ValueError(f"duplicate case id: {c.id}")
        seen.add(c.id)
    return cases


def load_translate_cases(path: Path) -> list[TranslateCase]:
    cases = []
    for d in _rows(path):
        if d["expect_decision"] not in EXPECT_DECISIONS:
            raise ValueError(
                f"{d['id']}: bad expect_decision {d['expect_decision']}")
        if any(i >= len(d["requirements"]) for i in d["must_apply"]):
            raise ValueError(f"{d['id']}: must_apply index out of range")
        cases.append(TranslateCase(
            id=d["id"], category=d["category"], source=d["source"],
            requirements=list(d["requirements"]), input=d["input"],
            expect_decision=d["expect_decision"],
            must_apply=list(d["must_apply"]),
            checks=[Check(**c) for c in d["checks"]]))
    return _check_unique_ids(cases)


def load_extraction_cases(path: Path) -> list[ExtractionCase]:
    cases = []
    for d in _rows(path):
        for op in d["expect_ops"]:
            if op["kind"] not in ("new", "reinforce", "contradict"):
                raise ValueError(f"{d['id']}: bad op kind {op['kind']}")
        cases.append(ExtractionCase(
            id=d["id"], category=d["category"], source=d["source"],
            existing=list(d["existing"]), events=list(d["events"]),
            expect_ops=list(d["expect_ops"])))
    return _check_unique_ids(cases)
```

- [ ] **Step 4: 测试通过 + Commit**

```bash
/opt/homebrew/bin/uv run pytest tests/test_bench_schema.py -q
git add bench/runner/schema.py tests/test_bench_schema.py
git commit -m "[bench] Add case schemas with hard-validating JSONL loaders"
```

---

## Task 2: 机械 checkers

**Files:**
- Create: `bench/runner/checkers.py`
- Test: `tests/test_bench_checkers.py`

- [ ] **Step 1: 失败测试**

```python
# tests/test_bench_checkers.py
from bench.runner.checkers import run_check


def test_contains_all():
    ok, why = run_check("contains_all", {"keywords": ["房东", "暖气"]},
                        polished="给房东写封邮件催修暖气", case_input="x")
    assert ok
    bad, why = run_check("contains_all", {"keywords": ["水管"]},
                         polished="给房东写封邮件催修暖气", case_input="x")
    assert not bad and "水管" in why


def test_not_contains():
    ok, _ = run_check("not_contains", {"banned": ["120"]},
                      polished="写封求职信", case_input="x")
    assert ok
    bad, _ = run_check("not_contains", {"banned": ["120"]},
                       polished="写封不超过120词的求职信", case_input="x")
    assert not bad


def test_same_language_zh_en():
    ok, _ = run_check("same_language", {}, polished="给房东写封不超过120词的邮件",
                      case_input="帮我给房东写封邮件")
    assert ok
    bad, _ = run_check("same_language", {},
                       polished="Draft an email to my landlord",
                       case_input="帮我给房东写封邮件")
    assert not bad


def test_unknown_checker_raises():
    try:
        run_check("nope", {}, polished="x", case_input="y")
        raise AssertionError("should raise")
    except KeyError:
        pass
```

- [ ] **Step 2: 确认失败，随后写 `bench/runner/checkers.py`**

```python
"""Mechanical checks — deterministic, zero-LLM. Each returns (ok, why)."""
import re

_CJK = re.compile(r"[一-鿿]")


def _lang(s: str) -> str:
    """zh if CJK chars form a meaningful share of the text, else en.
    Coarse on purpose: the bench only asserts zh-in → zh-out and en-in →
    en-out; mixed borderline inputs should not use this checker."""
    cjk = len(_CJK.findall(s))
    return "zh" if cjk >= max(4, 0.1 * len(s)) else "en"


def contains_all(args, polished, case_input):
    missing = [k for k in args["keywords"] if k not in polished]
    return (not missing, f"missing keywords: {missing}" if missing else "ok")


def not_contains(args, polished, case_input):
    hit = [b for b in args["banned"] if b in polished]
    return (not hit, f"banned substrings present: {hit}" if hit else "ok")


def same_language(args, polished, case_input):
    want, got = _lang(case_input), _lang(polished)
    return (want == got, f"input lang {want}, polished lang {got}")


_REGISTRY = {
    "contains_all": contains_all,
    "not_contains": not_contains,
    "same_language": same_language,
}


def run_check(name: str, args: dict, *, polished: str,
              case_input: str) -> tuple[bool, str]:
    return _REGISTRY[name](args, polished, case_input)
```

- [ ] **Step 3: 测试通过 + Commit**

```bash
/opt/homebrew/bin/uv run pytest tests/test_bench_checkers.py -q
git add bench/runner/checkers.py tests/test_bench_checkers.py
git commit -m "[bench] Add deterministic checker registry"
```

---

## Task 3: 二值 LLM judge

**Files:**
- Create: `bench/runner/config.py`、`bench/runner/judge.py`
- Test: `tests/test_bench_judge.py`

- [ ] **Step 1: 写 `bench/runner/config.py`**

```python
"""Bench-side config. The judge is NOT a product path, so anchor §5's
flash-only rule does not apply — use a strong model for grading."""
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
CASES = BENCH_ROOT / "cases"
RESULTS = BENCH_ROOT / "results"

JUDGE_MODEL = "claude-opus-4-8"      # 拍板点 2
JUDGE_MAX_TOKENS = 300
E2E_SECOND_HALF_FROM = 9             # rounds 9..16 count toward the score
E2E_PASS_THRESHOLD = 0.8
GATE_OVERALL = 0.80
GATE_PER_SUITE = 0.70                # 拍板点 1
WEIGHTS = {"T": 0.4, "L": 0.3, "E": 0.3}
```

- [ ] **Step 2: 失败测试**

```python
# tests/test_bench_judge.py
import bench.runner.judge as judge_mod
from bench.runner.judge import judge


def test_yes_verdict(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: '{"verdict": "yes", "reason": "ok"}')
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is True and flag is False


def test_no_verdict(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: '{"verdict": "no", "reason": "missing"}')
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is False and flag is False


def test_garbage_fails_closed(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete", lambda *a, **k: "hmm, maybe?")
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is False and flag is True
```

- [ ] **Step 3: 写 `bench/runner/judge.py`**

```python
"""One criterion, one call, one binary verdict. Fail-closed: anything that
does not parse to a clean yes counts as no and raises a parse flag, which the
report surfaces — a noisy judge must be visible, never silently generous.

temperature=0 for reproducibility; memtranslator.llm.complete does not expose
it, so we make the SDK call here (same client, same LLMUnavailable surface)."""
import json

import anthropic

from bench.runner.config import JUDGE_MAX_TOKENS, JUDGE_MODEL

JUDGE_SYSTEM = """You are a strict binary judge for a rewrite-quality benchmark.
You get a CRITERION and a CONTEXT (JSON). Decide whether the criterion holds.
Judge only what the criterion asks; do not reward extra qualities.
Answer with exactly one JSON object, nothing else:
{"verdict": "yes"|"no", "reason": "<one short sentence>"}"""

_client: anthropic.Anthropic | None = None


def _complete(system: str, user: str) -> str:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    resp = _client.messages.create(
        model=JUDGE_MODEL, max_tokens=JUDGE_MAX_TOKENS, temperature=0,
        system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in resp.content if b.type == "text")


def judge(criterion: str, context: dict) -> tuple[bool, bool]:
    """Returns (ok, parse_flag)."""
    user = (f"CRITERION:\n{criterion}\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=1)}")
    raw = _complete(JUDGE_SYSTEM, user)
    s = raw.strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return False, True
    try:
        obj = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return False, True
    v = obj.get("verdict")
    if v not in ("yes", "no"):
        return False, True
    return v == "yes", False
```

- [ ] **Step 4: 测试通过 + Commit**

```bash
/opt/homebrew/bin/uv run pytest tests/test_bench_judge.py -q
git add bench/runner/config.py bench/runner/judge.py tests/test_bench_judge.py
git commit -m "[bench] Add fail-closed binary judge with bench config"
```

---

## Task 4: Suite T seed cases（手写 12 + 扩展生成材料）

**Files:**
- Create: `bench/cases/translate/cases.jsonl`（先落 12 条手写 seed）
- Create: `bench/gen/prompts.md`

**六个 category 与构造要点**（每类目标 10 条；seed 每类 2 条如下，余下 8 条/类由 Step 2 的生成 prompt 扩展 + 人工审核）：

| category | 用户行为面 | 变化维度（生成时覆盖） |
|---|---|---|
| apply-single | 单条命中，正确编入 | 任务域（邮件/代码/文档/调研）、req 语言 zh/en、约束类型（长度/格式/语气/方法） |
| apply-multi | 2–3 条同时命中全编入 | 命中 2 vs 3 条、干扰条目在库、约束正交性 |
| scope-noop | 库非空但与输入无关 → 必须不动 | 库大小 1–5 条、输入域与库域的距离由远及近 |
| exception | req 自带例外，输入落在例外里 | 例外显式度、`expect_decision: any` + not_contains/judge 封锁误注入 |
| preserve-long | 长输入含粘贴材料，改写不毁材料 | 材料形态（流水账/代码块/URL/引用）、材料长度 |
| language-mixed | req 与 input 语言不同，输出跟 input | zh-req/en-input 与反向、混排输入 |

- [ ] **Step 1: 写 `bench/cases/translate/cases.jsonl`（12 条 seed 全文）**

```jsonl
{"id": "t-single-001", "category": "apply-single", "source": "handwritten", "requirements": ["Emails I ask you to draft must stay under 120 words."], "input": "帮我给房东写封邮件，催他修一下暖气", "expect_decision": "apply", "must_apply": [0], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["房东", "暖气"]}}, {"kind": "mech", "name": "same_language", "args": {}}]}
{"id": "t-single-002", "category": "apply-single", "source": "handwritten", "requirements": ["代码类回答只给代码，不要解释。"], "input": "write a python function that dedupes a list while keeping order", "expect_decision": "apply", "must_apply": [0], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["python"]}}, {"kind": "mech", "name": "same_language", "args": {}}]}
{"id": "t-multi-001", "category": "apply-multi", "source": "handwritten", "requirements": ["Emails I ask you to draft must stay under 120 words.", "All my emails should keep a firm, professional tone."], "input": "帮我写封邮件给租客，让他这周内补交上个月的房租", "expect_decision": "apply", "must_apply": [0, 1], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["租客", "房租"]}}]}
{"id": "t-multi-002", "category": "apply-multi", "source": "handwritten", "requirements": ["代码类回答只给代码，不要解释。", "Python 代码一律带 type hints。", "周报要用 bullet points。"], "input": "写个解析 jsonl 文件的小函数", "expect_decision": "apply", "must_apply": [0, 1], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["jsonl"]}}]}
{"id": "t-noop-001", "category": "scope-noop", "source": "handwritten", "requirements": ["Emails I ask you to draft must stay under 120 words."], "input": "这个 traceback 是什么意思，帮我看看哪里错了", "expect_decision": "noop", "must_apply": [], "checks": []}
{"id": "t-noop-002", "category": "scope-noop", "source": "handwritten", "requirements": ["周报要用 bullet points。", "代码类回答只给代码，不要解释。"], "input": "推荐几本入门 Rust 的书", "expect_decision": "noop", "must_apply": [], "checks": []}
{"id": "t-exc-001", "category": "exception", "source": "handwritten", "requirements": ["Emails under 120 words — except formal job application letters, which can run longer."], "input": "帮我写封正式的求职信，申请 Anthropic 的 research engineer 岗位", "expect_decision": "any", "must_apply": [], "checks": [{"kind": "mech", "name": "not_contains", "args": {"banned": ["120"]}}, {"kind": "judge", "name": "no-length-cap", "args": {"criterion": "The rewritten request (or unchanged request) does NOT impose any word/length cap on the job application letter."}}]}
{"id": "t-exc-002", "category": "exception", "source": "handwritten", "requirements": ["回复我一律用中文，但代码注释保持英文。"], "input": "给下面这个函数补上注释：def retry(fn, n): ...", "expect_decision": "any", "must_apply": [], "checks": [{"kind": "judge", "name": "comment-lang-not-flipped", "args": {"criterion": "The request does not ask for Chinese code comments; if comment language is mentioned at all, comments are to be in English."}}]}
{"id": "t-long-001", "category": "preserve-long", "source": "handwritten", "requirements": ["周报要用 bullet points，别写大段落。"], "input": "把下面的记录整理成周报：周一和 Leo 对了 pilot 的评测口径，把 judge prompt 改成了逐判据二值；周二在跑数据管线，卡在 events join 的时间窗上，后来把窗口放宽到十五分钟解决；周三写了 signals 的单元测试，顺手修了 store 的一个边界 bug；周四开始搭菜单栏 app 的 spike，Accessibility 权限流程比想象的麻烦；周五把闭环 demo 跑通了，还差 Cursor 的 hook 没接。", "expect_decision": "apply", "must_apply": [0], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["pilot", "时间窗", "Accessibility", "Cursor"]}}, {"kind": "judge", "name": "material-intact", "args": {"criterion": "Every workday item from the original notes (Mon–Fri) survives in the rewritten request; nothing is dropped, summarized away, or altered in meaning."}}]}
{"id": "t-long-002", "category": "preserve-long", "source": "handwritten", "requirements": ["All my emails should keep a firm, professional tone."], "input": "帮我把这封邮件发给物业前润色一下，里面的链接别动：你好，上周提交的维修申请（工单号 #4821，详情见 https://prop.example.com/ticket/4821 ）到现在没人跟进，水管还在漏。请这周三之前安排师傅上门，否则我会向住建部门投诉。", "expect_decision": "apply", "must_apply": [0], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["https://prop.example.com/ticket/4821", "#4821", "周三"]}}]}
{"id": "t-lang-001", "category": "language-mixed", "source": "handwritten", "requirements": ["Emails I ask you to draft must stay under 120 words."], "input": "帮我用英文给教授写封邮件，约下周 office hour 聊 thesis 选题", "expect_decision": "apply", "must_apply": [0], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["office hour", "thesis"]}}, {"kind": "mech", "name": "same_language", "args": {}}]}
{"id": "t-lang-002", "category": "language-mixed", "source": "handwritten", "requirements": ["代码类回答只给代码，不要解释。"], "input": "implement quicksort in rust, in-place", "expect_decision": "apply", "must_apply": [0], "checks": [{"kind": "mech", "name": "contains_all", "args": {"keywords": ["quicksort", "rust"]}}, {"kind": "mech", "name": "same_language", "args": {}}]}
```

（`t-lang-001` 有意保留：input 是中文、要求产出英文邮件——polished 请求本身应仍是中文；`same_language` 判请求语言而非产物语言，这正是该 category 要钉住的行为。）

- [ ] **Step 2: 写 `bench/gen/prompts.md`（扩展生成 prompt + 审核 checklist 全文）**

````markdown
# Case 扩展生成（每 category 补至 10 条）

用强模型（opus 档）按下述 prompt 逐 category 生成，temperature 默认；生成后
**逐条人工审核**，过 checklist 才进 cases.jsonl，source 标 "generated"。

## 生成 prompt（替换 {CATEGORY_SPEC} 为计划 Task 4 表格中该行的"用户行为面 + 变化维度"，附上该类 2 条 seed 作为格式样例）

You are creating benchmark cases for a "translator" that rewrites a user's
raw request by weaving in that user's stored delivery requirements
(rules about HOW tasks should be executed/delivered — length, format, tone,
method, workflow). It must never invent constraints, never change the core
task, and must leave unrelated requests untouched.

Category to generate: {CATEGORY_SPEC}

Rules for every case:
- The scenario must be an everyday situation for a developer / grad student /
  knowledge worker. If failing this case would not annoy a real user, discard it.
- Requirements must be delivery preferences (how the task is done), NEVER
  content preferences (what to recommend / personal facts like allergies).
- Vary across the dimensions listed in the category spec; do not produce
  near-duplicates of the seeds or of each other.
- Keywords in contains_all must be verbatim substrings of the input that any
  correct rewrite must keep (entities, URLs, ticket numbers, tech terms).
- Output one JSON object per line (JSONL), exactly matching the seed schema,
  ids as {prefix}-{003..010}.

Produce 8 cases.

## 人工审核 checklist（逐条过，任一不过则改或弃）

1. 日常性：这个 case 若 fail，真实用户会恼火吗？（不是 adversarial 智力题）
2. requirement 是 delivery 类，不是 content preference / 个人事实。
3. 期望行为无歧义：一个合格人类改写者会同意 expect_decision 与 must_apply。
4. contains_all 关键词确实是"任何正确改写都必须保留"的实体，无误伤。
5. judge 判据（如有）单义、可二值判定。
6. 与已有 case 不近重复（域、约束、句式至少一处明显不同）。
````

- [ ] **Step 3: loader 冒烟 + Commit**

```bash
/opt/homebrew/bin/uv run python -c "
from bench.runner.schema import load_translate_cases
cs = load_translate_cases('bench/cases/translate/cases.jsonl')
print(len(cs), 'cases,', len({c.category for c in cs}), 'categories')"
```
Expected: `12 cases, 6 categories`。

```bash
git add bench/cases/translate/cases.jsonl bench/gen/prompts.md
git commit -m "[bench] Add 12 handwritten Suite T seeds and the expansion protocol"
```

- [ ] **Step 4:（执行生成）按 prompts.md 逐 category 生成 8 条、人工审核、追加进 cases.jsonl（source=generated），loader 冒烟到 60 条**

- [ ] **Step 5: Commit**

```bash
git add bench/cases/translate/cases.jsonl
git commit -m "[bench] Expand Suite T to 60 reviewed cases across 6 categories"
```

---

## Task 5: Suite T runner + report + 首次真实跑分

**Files:**
- Create: `bench/runner/run_translate.py`、`bench/runner/report.py`
- Test: `tests/test_bench_run_translate.py`

- [ ] **Step 1: 失败测试（FakeLLM：monkeypatch `memtranslator.llm.complete` 与 bench judge）**

```python
# tests/test_bench_run_translate.py
import json

import memtranslator.llm as llm
import bench.runner.run_translate as rt
from bench.runner.schema import Check, TranslateCase


def _case(**kw):
    base = dict(id="t-1", category="apply-single", source="handwritten",
                requirements=["Emails under 120 words."],
                input="帮我给房东写封邮件", expect_decision="apply",
                must_apply=[0], checks=[])
    base.update(kw)
    return TranslateCase(**base)


def _fake_translate_apply(monkeypatch):
    def fake(model, system, user, max_tokens=1024):
        rid = user.split("[", 1)[1].split("]", 1)[0]
        return json.dumps({"decision": "apply", "applied_ids": [rid],
                           "polished": "给房东写封不超过120词的邮件"})
    monkeypatch.setattr(llm, "complete", fake)


def test_apply_case_passes_with_yes_judge(monkeypatch):
    _fake_translate_apply(monkeypatch)
    monkeypatch.setattr(rt, "judge", lambda crit, ctx: (True, False))
    r = rt.run_case(_case())
    assert r["pass"] is True and r["decision_ok"] and not r["judge_flags"]


def test_apply_case_fails_when_judge_says_no(monkeypatch):
    _fake_translate_apply(monkeypatch)
    monkeypatch.setattr(rt, "judge", lambda crit, ctx: (False, False))
    assert rt.run_case(_case())["pass"] is False


def test_noop_case_needs_no_judge(monkeypatch):
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: '{"decision": "noop"}')
    monkeypatch.setattr(rt, "judge",
                        lambda *a: (_ for _ in ()).throw(AssertionError))
    r = rt.run_case(_case(expect_decision="noop", must_apply=[]))
    assert r["pass"] is True


def test_mech_check_failure_short_circuits(monkeypatch):
    _fake_translate_apply(monkeypatch)
    monkeypatch.setattr(rt, "judge", lambda crit, ctx: (True, False))
    c = _case(checks=[Check(kind="mech", name="contains_all",
                            args={"keywords": ["水管"]})])
    r = rt.run_case(c)
    assert r["pass"] is False and "水管" in json.dumps(r["failures"],
                                                      ensure_ascii=False)


def test_wrong_decision_fails(monkeypatch):
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: '{"decision": "noop"}')
    r = rt.run_case(_case())          # expected apply, got noop
    assert r["pass"] is False and r["decision_ok"] is False
```

- [ ] **Step 2: 确认失败，写 `bench/runner/run_translate.py`**

```python
"""Suite T: run each case through the real translate() read path, grade in
three layers (decision → mechanical → judge). One result dict per case."""
import argparse
import json
import time

from memtranslator.schema import Requirement
from memtranslator.translate import translate

from bench.runner.checkers import run_check
from bench.runner.config import CASES
from bench.runner.judge import judge
from bench.runner.report import write_snapshot
from bench.runner.schema import load_translate_cases

AUTO_NO_INVENTION = ("The rewritten request adds no constraint that is not "
                     "grounded in the listed stored requirements.")
AUTO_TASK_INTACT = ("The core task of the original request is unchanged in "
                    "the rewritten request.")


def run_case(case) -> dict:
    reqs = [Requirement(text=t) for t in case.requirements]
    out = translate(case.input, reqs)
    polished = out["polished"] or case.input
    failures, judge_flags = [], []

    # 1. decision layer (mechanical)
    decision_ok = (case.expect_decision == "any"
                   or out["decision"] == case.expect_decision)
    if decision_ok and case.expect_decision == "apply":
        need = {reqs[i].id for i in case.must_apply}
        if not need <= set(out["applied_ids"]):
            decision_ok = False
            failures.append({"layer": "decision",
                             "why": f"applied_ids missed {need}"})
    if not decision_ok and not failures:
        failures.append({"layer": "decision",
                         "why": f"expected {case.expect_decision}, "
                                f"got {out['decision']}"})

    # 2 + 3 only matter when something was rewritten
    if out["decision"] == "apply":
        for c in case.checks:
            if c.kind != "mech":
                continue
            ok, why = run_check(c.name, c.args, polished=polished,
                                case_input=case.input)
            if not ok:
                failures.append({"layer": "mech", "check": c.name, "why": why})
        ctx = {"stored_requirements": case.requirements,
               "original_request": case.input, "rewritten_request": polished}
        criteria = [f"The rewritten request explicitly carries this "
                    f"constraint: {case.requirements[i]}"
                    for i in case.must_apply]
        criteria += [AUTO_NO_INVENTION, AUTO_TASK_INTACT]
        criteria += [c.args["criterion"] for c in case.checks
                     if c.kind == "judge"]
        for crit in criteria:
            ok, flag = judge(crit, ctx)
            if flag:
                judge_flags.append(crit)
            if not ok:
                failures.append({"layer": "judge", "why": crit})
    elif case.expect_decision == "any":
        # noop side of an exception case: only judge checks that make sense
        ctx = {"stored_requirements": case.requirements,
               "original_request": case.input, "rewritten_request": polished}
        for c in case.checks:
            if c.kind == "judge":
                ok, flag = judge(c.args["criterion"], ctx)
                if flag:
                    judge_flags.append(c.args["criterion"])
                if not ok:
                    failures.append({"layer": "judge",
                                     "why": c.args["criterion"]})

    return {"id": case.id, "category": case.category, "pass": not failures,
            "decision_ok": decision_ok, "decision": out["decision"],
            "polished": out["polished"], "failures": failures,
            "judge_flags": judge_flags, "latency_ms": out["latency_ms"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(CASES / "translate/cases.jsonl"))
    args = ap.parse_args()
    cases = load_translate_cases(args.cases)
    results = []
    for i, case in enumerate(cases, 1):
        r = run_case(case)
        results.append(r)
        print(f"[{i}/{len(cases)}] {case.id} "
              f"{'PASS' if r['pass'] else 'FAIL'}")
        time.sleep(0.2)          # 简单限速，别打爆并发额度
    write_snapshot("T", args.cases, results)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 写 `bench/runner/report.py`**

```python
"""Aggregate per-category → suite (macro) → overall, decide the gate, and
persist a reproducible snapshot per run."""
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

from bench.runner.config import (GATE_OVERALL, GATE_PER_SUITE, JUDGE_MODEL,
                                 RESULTS, WEIGHTS)


def category_rates(results: list[dict]) -> dict[str, float]:
    buckets = defaultdict(list)
    for r in results:
        buckets[r["category"]].append(r["pass"])
    return {c: sum(v) / len(v) for c, v in sorted(buckets.items())}


def suite_score(results: list[dict]) -> float:
    rates = category_rates(results)
    return sum(rates.values()) / len(rates) if rates else 0.0


def write_snapshot(suite: str, cases_path: str, results: list[dict]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    case_hash = hashlib.sha256(
        Path(cases_path).read_bytes()).hexdigest()[:12]
    snap = {"suite": suite, "at": stamp, "judge_model": JUDGE_MODEL,
            "cases_file": str(cases_path), "cases_hash": case_hash,
            "score": suite_score(results),
            "category_rates": category_rates(results),
            "judge_parse_flags": sum(len(r.get("judge_flags", []))
                                     for r in results),
            "results": results}
    out = RESULTS / f"{suite}-{stamp}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"\n{suite} suite score: {snap['score']:.3f}")
    for c, v in snap["category_rates"].items():
        print(f"  {c:20s} {v:.2f}")
    print(f"snapshot: {out}")
    return out


def latest(suite: str) -> dict | None:
    snaps = sorted(RESULTS.glob(f"{suite}-*.json"))
    return json.loads(snaps[-1].read_text()) if snaps else None


def main():
    scores, missing = {}, []
    for s in ("T", "L", "E"):
        snap = latest(s)
        if snap is None:
            missing.append(s)
        else:
            scores[s] = snap["score"]
            print(f"{s}: {snap['score']:.3f}  ({snap['at']}, "
                  f"judge={snap['judge_model']})")
    if missing:
        print(f"missing suites: {missing} — overall not computable yet")
        return
    overall = sum(WEIGHTS[s] * scores[s] for s in scores)
    gate = overall >= GATE_OVERALL and all(v >= GATE_PER_SUITE
                                           for v in scores.values())
    print(f"\noverall = {overall:.3f}   "
          f"gate(≥{GATE_OVERALL:.2f} & each≥{GATE_PER_SUITE:.2f}): "
          f"{'PASS — first release is good enough' if gate else 'FAIL'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: harness 测试全绿**

```bash
/opt/homebrew/bin/uv run pytest tests/test_bench_run_translate.py -q
/opt/homebrew/bin/uv run pytest -q        # 全仓库仍绿
```

- [ ] **Step 5: 首次真实跑分（v0 oracle 的 T 水位）**

```bash
source ~/.zshrc
uv run python -m bench.runner.run_translate
```
Expected: 60 行 PASS/FAIL + suite 分数 + snapshot 路径。把分数与 per-category 表填进 `bench/README.md` 的 Current water line（注明日期、translator/judge model id）。若 key/网络不可用：记 blocked 于 README，不阻塞后续 task。

- [ ] **Step 6: Commit**

```bash
git add bench/runner/run_translate.py bench/runner/report.py tests/test_bench_run_translate.py bench/README.md
git commit -m "[bench] Add Suite T runner and report, record the v0 water line"
```

---

## Task 6: PrefEval 零散借用（T 补例 + L 负例源）

anchor §3/§8：PrefEval 大部分是 content preference，只挑贴近 delivery 的极少数；同时它的 content 条目正好当 Suite L 的 noise-reject 负例素材。

**Files:**
- Modify: `bench/cases/translate/cases.jsonl`（追加 ≤10 条，source=prefeval）
- Create: `bench/gen/prefeval-notes.md`（筛选记录：看了哪些、选了哪些、为何）

- [ ] **Step 1: 拉数据（repo: amazon-science/PrefEval，License 执行时核对并记进 notes）**

```bash
cd "$(mktemp -d)" && git clone --depth 1 https://github.com/amazon-science/PrefEval.git && ls PrefEval/benchmark_dataset
```

- [ ] **Step 2: 人工筛选。** 判据即 Task 4 审核 checklist 第 2 条的正反两用：(a) 明确「how the task is done」的条目 → 改写成 T case（保留原句意，场景本地化，`source: "prefeval"`，notes 里记原条目 id）；(b) 典型 content preference 条目（饮食/娱乐/购物偏好）→ 摘 6–8 条原文进 notes，供 Task 7 的 noise-reject case 直接取材。目标 (a) ≤10 条——**若合格条目不足 10，宁缺毋滥**，T 缺口用 Task 4 生成流程补足到 60。
- [ ] **Step 3: loader 冒烟（60 条、id 无重复）+ Commit**

```bash
git add bench/cases/translate/cases.jsonl bench/gen/prefeval-notes.md
git commit -m "[bench] Fold a hand-picked PrefEval sliver into Suite T and the noise pool"
```

---

## Task 7: Suite L——extraction cases + provider 接口 + runner

**Files:**
- Create: `bench/runner/providers.py`、`bench/runner/run_extraction.py`
- Create: `bench/cases/extraction/cases.jsonl`（6 类 seed 如下，扩展到 36 走 Task 4 同款生成+审核流程，prompts.md 追加一节）
- Test: `tests/test_bench_extraction.py`

**六个 category**（期望语义见 §2 评分协议）：

| category | events 形态 | expect_ops |
|---|---|---|
| natural-explicit | 立规句「以后都…」 | 1 × new |
| natural-correction | 上轮语境 + 纠正句 | 1 × new |
| diff-new-constraint | (raw, polished, final)，final 新增约束（路 B 的 b3） | 1 × new |
| noise-reject-content | content preference（含 PrefEval 摘句） | []（提取即 fail） |
| noise-reject-task | 一次性任务指令（「这次写长点”） | []（提取即 fail） |
| relation | 纠正与库中既有条目同 facet | 1 × reinforce 或 contradict（带 target） |

- [ ] **Step 1: 写 6 条 seed（`bench/cases/extraction/cases.jsonl` 全文）**

```jsonl
{"id": "l-exp-001", "category": "natural-explicit", "source": "handwritten", "existing": [], "events": [{"type": "natural", "text": "以后我让你写周报，一律用 bullet points，别给我写大段落"}], "expect_ops": [{"kind": "new", "target": null, "gist": "weekly reports must use bullet points, not long paragraphs"}]}
{"id": "l-corr-001", "category": "natural-correction", "source": "handwritten", "existing": [], "events": [{"type": "natural", "text": "帮我总结一下这篇论文的方法部分"}, {"type": "natural", "text": "不是让你夸它，我要的是批判性分析，指出方法的弱点"}], "expect_ops": [{"kind": "new", "target": null, "gist": "paper analysis should be critical (point out weaknesses), not praise or plain summary"}]}
{"id": "l-diff-001", "category": "diff-new-constraint", "source": "handwritten", "existing": ["Emails I ask you to draft must stay under 120 words."], "events": [{"type": "edited_diff", "raw": "给房东写封邮件催修暖气", "polished": "给房东写封不超过120词的邮件，催他尽快修暖气", "final": "给房东写封不超过120词的英文邮件，催他尽快修暖气，语气强硬一点"}], "expect_ops": [{"kind": "new", "target": null, "gist": "emails to the landlord in English, with a firm tone"}]}
{"id": "l-noisec-001", "category": "noise-reject-content", "source": "handwritten", "existing": [], "events": [{"type": "natural", "text": "对了我不吃麸质，帮我找餐厅的时候注意一下"}], "expect_ops": []}
{"id": "l-noiset-001", "category": "noise-reject-task", "source": "handwritten", "existing": ["周报要用 bullet points。"], "events": [{"type": "natural", "text": "这次的周报例外写详细点，季度 review 要用"}], "expect_ops": []}
{"id": "l-rel-001", "category": "relation", "source": "handwritten", "existing": ["代码类回答只给代码，不要解释。"], "events": [{"type": "natural", "text": "又来了，说了多少次代码别带解释，直接给代码"}], "expect_ops": [{"kind": "reinforce", "target": 0, "gist": "code answers without explanations"}]}
```

（`l-noiset-001` 是 relation 的镜像陷阱：带「例外/这次」限定词的一次性指令，最容易被误提为规则——这是 noise 类里最贴日常的失败模式。）

- [ ] **Step 2: 失败测试**

```python
# tests/test_bench_extraction.py
import bench.runner.run_extraction as rx
from bench.runner.providers import NullProvider
from bench.runner.schema import ExtractionCase


def _case(**kw):
    base = dict(id="l-1", category="natural-explicit", source="handwritten",
                existing=[], events=[{"type": "natural", "text": "以后周报都用 bullet"}],
                expect_ops=[{"kind": "new", "target": None,
                             "gist": "weekly reports in bullets"}])
    base.update(kw)
    return ExtractionCase(**base)


def test_null_provider_fails_extraction_case(monkeypatch):
    r = rx.run_case(_case(), NullProvider())
    assert r["pass"] is False


def test_null_provider_passes_noise_case():
    r = rx.run_case(_case(category="noise-reject-content", expect_ops=[]),
                    NullProvider())
    assert r["pass"] is True


class _OneShot:
    def __init__(self, ops): self.ops = ops
    def extract(self, events, existing): return self.ops


def test_matching_op_passes(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    ops = [{"kind": "new", "target_id": None, "text": "周报用 bullet points"}]
    assert rx.run_case(_case(), _OneShot(ops))["pass"] is True


def test_spurious_op_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    ops = [{"kind": "new", "target_id": None, "text": "周报用 bullet points"},
           {"kind": "new", "target_id": None, "text": "用户不吃麸质"}]
    r = rx.run_case(_case(), _OneShot(ops))
    assert r["pass"] is False


def test_wrong_kind_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="relation",
              existing=["代码只给代码，不解释。"],
              expect_ops=[{"kind": "reinforce", "target": 0,
                           "gist": "code without explanations"}])
    ops = [{"kind": "new", "target_id": None, "text": "代码不要解释"}]
    assert rx.run_case(c, _OneShot(ops))["pass"] is False
```

- [ ] **Step 3: 写 `bench/runner/providers.py`**

```python
"""ExtractionProvider: the seam between this bench and the v1 pipeline.

The bench ships two stand-ins — NullProvider (floor) and ReferenceProvider
(a deliberately naive single-call baseline for harness smoke + a number to
beat). NEITHER is the v1 implementation; when the real pipeline lands in
src/, wrap it behind this protocol and pass --provider v1."""
import json
from typing import Protocol

from memtranslator import llm
from memtranslator.config import MODELS
from memtranslator.schema import Requirement

# op: {"kind": "new"|"reinforce"|"contradict", "target_id": str|None, "text": str}


class ExtractionProvider(Protocol):
    def extract(self, events: list[dict],
                existing: list[Requirement]) -> list[dict]: ...


class NullProvider:
    def extract(self, events, existing):
        return []


REFERENCE_SYSTEM = """You maintain a store of a user's delivery requirements —
rules about HOW tasks should be executed and delivered (length, format, tone,
method, workflow). From the events below, extract requirement operations.
Only extract durable "how the task is done" rules the user actually expressed.
Never extract: content preferences (what to recommend, personal facts),
one-off instructions scoped to a single task ("this time", "例外", "这次"),
or task content itself.
Existing requirements are listed with ids; if an event restates one, emit
reinforce with its id; if it durably overrides one, emit contradict with its
id and the corrected text. Otherwise emit new.
Output strictly a JSON array (possibly empty):
[{"kind": "new"|"reinforce"|"contradict", "target_id": <id or null>, "text": "..."}]"""


class ReferenceProvider:
    def extract(self, events, existing):
        idx = "\n".join(f"- [{r.id}] {r.text}" for r in existing) or "(none)"
        evs = json.dumps(events, ensure_ascii=False, indent=1)
        raw = llm.complete(MODELS["translator"], REFERENCE_SYSTEM,
                           f"Existing requirements:\n{idx}\n\nEvents:\n{evs}\n\nJSON:")
        s = raw.strip()
        start, end = s.find("["), s.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            ops = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            return []
        return [o for o in ops if isinstance(o, dict)
                and o.get("kind") in ("new", "reinforce", "contradict")
                and isinstance(o.get("text"), str)]


PROVIDERS = {"null": NullProvider, "reference": ReferenceProvider}
```

- [ ] **Step 4: 写 `bench/runner/run_extraction.py`**

```python
"""Suite L: feed each case's events to a provider, grade ops against
expectations. Precision is sacred: one spurious extraction fails the case."""
import argparse
import time

from memtranslator.schema import Requirement

from bench.runner.config import CASES
from bench.runner.judge import judge
from bench.runner.providers import PROVIDERS
from bench.runner.report import write_snapshot
from bench.runner.schema import load_extraction_cases


def run_case(case, provider) -> dict:
    existing = [Requirement(text=t) for t in case.existing]
    ops = provider.extract(case.events, existing)
    failures, judge_flags, used = [], [], set()

    for exp in case.expect_ops:
        exp_target = (existing[exp["target"]].id
                      if exp.get("target") is not None else None)
        matched = None
        for i, op in enumerate(ops):
            if i in used or op["kind"] != exp["kind"]:
                continue
            if exp_target is not None and op.get("target_id") != exp_target:
                continue
            ok, flag = judge(
                f"Extracted requirement text expresses this gist: "
                f"{exp['gist']}",
                {"extracted_text": op["text"], "events": case.events})
            if flag:
                judge_flags.append(exp["gist"])
            if ok:
                matched = i
                break
        if matched is None:
            failures.append({"why": f"expected op not produced: {exp}"})
        else:
            used.add(matched)

    for i, op in enumerate(ops):
        if i not in used:
            failures.append({"why": f"spurious op: {op}"})

    return {"id": case.id, "category": case.category, "pass": not failures,
            "ops": ops, "failures": failures, "judge_flags": judge_flags}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="null")
    ap.add_argument("--cases", default=str(CASES / "extraction/cases.jsonl"))
    args = ap.parse_args()
    provider = PROVIDERS[args.provider]()
    cases = load_extraction_cases(args.cases)
    results = []
    for i, case in enumerate(cases, 1):
        r = run_case(case, provider)
        results.append(r)
        print(f"[{i}/{len(cases)}] {case.id} "
              f"{'PASS' if r['pass'] else 'FAIL'}")
        time.sleep(0.2)
    write_snapshot("L", args.cases, results)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 测试全绿；`prompts.md` 追加 L 扩展一节（同款生成+审核，category 表即 Task 7 表）；扩展到 36 条；NullProvider 冒烟跑一遍（期望：noise 两类 pass、其余 fail——顺带验证 macro 平均确实把「全不提取」压到 ~0.33，防呆生效）**

```bash
/opt/homebrew/bin/uv run pytest tests/test_bench_extraction.py -q
uv run python -m bench.runner.run_extraction --provider null
```

- [ ] **Step 6: Commit**

```bash
git add bench/runner/providers.py bench/runner/run_extraction.py tests/test_bench_extraction.py bench/cases/extraction/cases.jsonl bench/gen/prompts.md
git commit -m "[bench] Add Suite L cases, provider seam, and extraction runner"
```

---

## Task 8: Suite E——persona 脚本 + e2e runner

**设计：** persona = 隐含 requirement 集 + 16 轮写死的任务脚本。库从空开始。每轮：task → `translate()`（用当前库）→ 逐条 judge applicable requirement 是否被编入 polished →
- 全携带 → 记 accepted（该轮得分 1）
- 有缺失 → 该轮得分 0，并把脚本里**预写好的 final**（用户手改后的正确版）作为 `edited_diff` 事件、加上预写的 natural 纠正句（部分轮），推进 provider 学习——攒 4 轮 flush 一次 `provider.extract`，产出 ops 按 kind 落到轮内存库（new→append；reinforce→touch；contradict→retire+append）
分数 = 后半程（9–16 轮）中 applicable 判据的携带率；persona pass ⇔ ≥0.8。模拟器零自由度：任务、final、纠正句全部写死在 persona 文件里，run 间唯一变量是被测系统。

**Files:**
- Create: `bench/cases/personas/dev-zh.json`（全文样例）+ 其余 7 个（Step 3 规格表）
- Create: `bench/runner/run_e2e.py`
- Test: `tests/test_bench_e2e.py`

- [ ] **Step 1: 写 `bench/cases/personas/dev-zh.json`（样例全文；其余 persona 同 schema）**

```json
{
  "id": "dev-zh",
  "requirements": [
    "代码类回答只给代码，不要解释",
    "commit message 用英文，一两句话，不要 bullet",
    "调研类问题先给结论再给依据"
  ],
  "rounds": [
    {"n": 1, "task": "写个 python 函数，把嵌套 dict 拍平成点分隔的 key",
     "applicable": [0],
     "final": "写个 python 函数，把嵌套 dict 拍平成点分隔的 key。只给代码，不要解释。",
     "natural_correction": "说过了，代码直接给，别解释"},
    {"n": 2, "task": "帮我写这次改动的 commit message，改的是把重试逻辑抽成了装饰器",
     "applicable": [1],
     "final": "帮我写这次改动的 commit message，改的是把重试逻辑抽成了装饰器。英文，一两句话，别用 bullet。",
     "natural_correction": "commit message 要英文的，一两句就行，不要列点"},
    {"n": 3, "task": "uv 和 poetry 现在选哪个比较好",
     "applicable": [2],
     "final": "uv 和 poetry 现在选哪个比较好？先给结论，再给依据。",
     "natural_correction": null},
    {"n": 4, "task": "给这个列表去重但保持顺序，写个函数",
     "applicable": [0],
     "final": "给这个列表去重但保持顺序，写个函数。只要代码不要解释。",
     "natural_correction": null},
    {"n": 5, "task": "今天修了三个 flaky test，帮我写 commit message",
     "applicable": [1],
     "final": "今天修了三个 flaky test，帮我写 commit message。英文，一两句话。",
     "natural_correction": null},
    {"n": 6, "task": "帮我看看 asyncio.TaskGroup 和 gather 该用哪个",
     "applicable": [2],
     "final": "帮我看看 asyncio.TaskGroup 和 gather 该用哪个，先说结论。",
     "natural_correction": null},
    {"n": 7, "task": "写个装饰器，函数抛异常时自动重试三次",
     "applicable": [0],
     "final": "写个装饰器，函数抛异常时自动重试三次。只给代码。",
     "natural_correction": null},
    {"n": 8, "task": "把 config 从环境变量迁到了 pyproject，写下 commit message",
     "applicable": [1],
     "final": "把 config 从环境变量迁到了 pyproject，写下 commit message。英文一两句。",
     "natural_correction": null},
    {"n": 9, "task": "实现一个带 TTL 的内存缓存类",
     "applicable": [0],
     "final": "实现一个带 TTL 的内存缓存类。只给代码，不要解释。",
     "natural_correction": null},
    {"n": 10, "task": "sqlite 的 WAL 模式适不适合我们这种单机多进程读多写少的场景",
     "applicable": [2],
     "final": "sqlite 的 WAL 模式适不适合我们这种单机多进程读多写少的场景？结论先行。",
     "natural_correction": null},
    {"n": 11, "task": "补了 events join 的边界测试，写 commit message",
     "applicable": [1],
     "final": "补了 events join 的边界测试，写 commit message，英文一两句。",
     "natural_correction": null},
    {"n": 12, "task": "写个函数解析 jsonl，坏行跳过并计数",
     "applicable": [0],
     "final": "写个函数解析 jsonl，坏行跳过并计数。只给代码。",
     "natural_correction": null},
    {"n": 13, "task": "fastapi 的 BackgroundTasks 和自己起线程有什么取舍",
     "applicable": [2],
     "final": "fastapi 的 BackgroundTasks 和自己起线程有什么取舍？先给结论。",
     "natural_correction": null},
    {"n": 14, "task": "把热键从 ⌘E 改成了 ⌥⌘E，写 commit message",
     "applicable": [1],
     "final": "把热键从 ⌘E 改成了 ⌥⌘E，写 commit message，英文一两句。",
     "natural_correction": null},
    {"n": 15, "task": "写个小脚本统计 events.jsonl 里各 kind 的数量",
     "applicable": [0],
     "final": "写个小脚本统计 events.jsonl 里各 kind 的数量。只给代码不要解释。",
     "natural_correction": null},
    {"n": 16, "task": "本地 embedding 模型选 bge-m3 还是 e5-small，帮我定一个",
     "applicable": [2],
     "final": "本地 embedding 模型选 bge-m3 还是 e5-small，帮我定一个，结论先行。",
     "natural_correction": null}
  ]
}
```

- [ ] **Step 2: 失败测试**

```python
# tests/test_bench_e2e.py
import bench.runner.run_e2e as re2e
from bench.runner.providers import NullProvider


class _LearnsRound4:
    """Fake provider: extracts everything it has seen on the first flush."""
    def extract(self, events, existing):
        have = {r.text for r in existing}
        out = []
        for e in events:
            if e["type"] == "natural" and e["text"] not in have:
                out.append({"kind": "new", "target_id": None, "text": e["text"]})
        return out


def _persona():
    rounds = [{"n": i, "task": f"task {i}", "applicable": [0],
               "final": f"task {i} + constraint",
               "natural_correction": "以后都要X" if i == 1 else None}
              for i in range(1, 17)]
    return {"id": "p", "requirements": ["都要X"], "rounds": rounds}


def test_null_provider_scores_zero(monkeypatch):
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    r = re2e.run_persona(_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 0.0 and r["pass"] is False


def test_perfect_carry_scores_one(monkeypatch):
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (True, False))
    monkeypatch.setattr(re2e, "_polish", lambda text, reqs: {
        "decision": "apply", "polished": text + " polished",
        "applied_ids": [], "parse_error": False, "latency_ms": 0})
    r = re2e.run_persona(_persona(), NullProvider(), flush_every=4)
    assert r["second_half_rate"] == 1.0 and r["pass"] is True


def test_learning_provider_updates_store(monkeypatch):
    seen_sizes = []
    def fake_polish(text, reqs):
        seen_sizes.append(len(reqs))
        return {"decision": "noop", "polished": None, "applied_ids": [],
                "parse_error": False, "latency_ms": 0}
    monkeypatch.setattr(re2e, "_polish", fake_polish)
    monkeypatch.setattr(re2e, "_carries", lambda req, polished: (False, False))
    re2e.run_persona(_persona(), _LearnsRound4(), flush_every=4)
    assert seen_sizes[0] == 0 and seen_sizes[-1] >= 1   # store grew mid-run
```

- [ ] **Step 3: 写 `bench/runner/run_e2e.py`**

```python
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
                                 E2E_SECOND_HALF_FROM)
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
    results = []
    for p in sorted((CASES / "personas").glob("*.json")):
        persona = json.loads(Path(p).read_text())
        r = run_persona(persona, provider)
        results.append(r)
        print(f"{persona['id']}: second-half rate "
              f"{r['second_half_rate']:.2f} "
              f"{'PASS' if r['pass'] else 'FAIL'}")
    write_snapshot("E", str(CASES / "personas"), results)


if __name__ == "__main__":
    main()
```

注意：`write_snapshot` 的 `cases_hash` 读文件——传目录会炸，Step 4 里给 report.py 加 3 行目录分支（对目录取各文件 hash 的 hash；测试覆盖）。

- [ ] **Step 4: report.py 目录 hash 分支 + 测试全绿**

```python
# report.py 中 write_snapshot 的 case_hash 计算替换为：
    p = Path(cases_path)
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(p.glob("*.json")):
            h.update(f.read_bytes())
        case_hash = h.hexdigest()[:12]
    else:
        case_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
```

```bash
/opt/homebrew/bin/uv run pytest -q
```

- [ ] **Step 5: 写其余 7 个 persona（schema 同 dev-zh.json，覆盖矩阵如下；每个 16 轮、2–4 条 requirement、requirement 域与任务域一致；至少 2 个 persona 全英文、1 个中英混用）**

| id | 域 | requirement 主题 |
|---|---|---|
| dev-zh | 开发（样例已给） | 代码无解释 / commit 英文短 / 结论先行 |
| writer-zh | 邮件与文档 | 邮件<120词 / 语气坚定 / 文档要目录 |
| researcher-zh | 论文与调研 | 批判分析 / 先结论后依据 / 引用给出处 |
| student-en | 课程作业 | 解题先列思路 / LaTeX 输出 / 逐步推导 |
| pm-en | 会议与规划 | 会议纪要 action-item 化 / 一页纸 / 无行话 |
| datasci-zh | 数据分析 | 图表配一句结论 / 代码带注释例外域 / 单位标注 |
| mixed-lang | 中英混用 | 中文回答英文术语 / 邮件英文 / 代码注释英文 |
| minimalist-zh | 泛工作流 | 回答短 / 不用 bullet / 别复述问题 |

- [ ] **Step 6: NullProvider 冒烟全 8 persona（期望 second-half rate 全 0——库永远空；这就是 v0 的 E 下限，写进 README 水位表）+ Commit**

```bash
uv run python -m bench.runner.run_e2e --provider null
git add bench/cases/personas bench/runner/run_e2e.py tests/test_bench_e2e.py bench/runner/report.py
git commit -m "[bench] Add Suite E personas and the scripted e2e learning loop"
```

---

## Task 9: 可信度与总 gate（含人工闸门）

**Files:**
- Modify: `bench/README.md`
- Create: `bench/gen/judge-audit.md`（抽检记录表）

- [ ] **Step 1: stability check——T suite 连跑 2 遍，case 级判定翻转率**

```bash
uv run python -m bench.runner.run_translate
uv run python -m bench.runner.run_translate
uv run python - <<'EOF'
import json
from pathlib import Path
snaps = sorted(Path("bench/results").glob("T-*.json"))[-2:]
a, b = [{r["id"]: r["pass"] for r in json.loads(s.read_text())["results"]}
        for s in snaps]
flips = [k for k in a if a[k] != b.get(k)]
print(f"flip rate: {len(flips)}/{len(a)}  {flips}")
EOF
```
Expected: 翻转率 <5%（3/60）。超了 → 先看翻转 case 是判据歧义还是 judge 抖动：歧义改 case，抖动收紧 judge prompt（加「when in doubt about wording, judge the semantics」类款），重跑直到达标。

- [ ] **Step 2:（人工闸门，siriux ~30 分钟）judge 抽检**——从最新 T/L snapshot 随机抽 30 条 judge 判定（`results` 里有 criterion + context + verdict），人工标注一致/不一致记入 `bench/gen/judge-audit.md`。一致率 ≥90% → judge 可信，记录背书；<90% → 改 JUDGE_SYSTEM 或拆细判据，重抽。

- [ ] **Step 3: reference 基线跑 L + E（拿"要击败的数字"），README 水位表定稿**

```bash
uv run python -m bench.runner.run_extraction --provider reference
uv run python -m bench.runner.run_e2e --provider reference
uv run python -m bench.runner.report
```

`bench/README.md` 的 Current water line 更新为三行水位 + overall（标注：T=v0 真实分；L/E=reference 基线，非 v1 成绩；gate 判定当前状态）+ stability 翻转率 + judge 抽检一致率，全部带日期与 model id。

- [ ] **Step 4: Commit**

```bash
git add bench/README.md bench/gen/judge-audit.md
git commit -m "[bench] Record stability, judge audit, and reference baselines"
```

---

## Task 10: 收尾

**Files:**
- Modify: `README.md`（根）、`docs/2026-07-23-bench-plan.md`（状态行）

- [ ] **Step 1: 根 README 在 closed loop 段后加一行**

```markdown
- `bench/` — the v1 acceptance bench: **overall ≥ 80% ⇔ the first
  user-facing release is good enough** (T translate / L learn / E e2e;
  see `bench/README.md` for the contract and current water line).
```

- [ ] **Step 2: 本计划顶部加状态行（`> 状态：已执行至 Task N / 全部完成，YYYY-MM-DD`），全量测试 + push**

```bash
/opt/homebrew/bin/uv run pytest -q
git add README.md docs/2026-07-23-bench-plan.md
git commit -m "[bench] Link the bench contract from the README"
git push origin bench
```

---

## 拍板点

1. **Gate 形态**：总分 ≥80% 之外是否加"每 suite ≥70%"下限？（建议加——防 T 满分拖着 L/E 混过；不加则纯 overall，更贴你原话）
2. **Judge 模型**：默认 `claude-opus-4-8`（与 downstream 同档）。bench 判分不是产品路径，不受 anchor §5 flash 限制；也可换更便宜档，代价是 Task 9 抽检一致率风险。
3. **E suite 计分时点**：E 依赖 v1，v1 落地前 overall 永远不可达 80%。(a) 三 suite 从始至终一起算（gate 就是 v1 的验收，当前 fail 是事实陈述）｜(b) 过渡期只算 T+L（权重临时 0.6/0.4），v1 接入后切回三 suite。**建议 (a)**——bench 本来就是"第一版"的标尺，不为中间态改标尺。

## 成本与规模（估）

| 一次全量 | LLM 调用 | tokens 量级 | 费用（估） |
|---|---|---|---|
| Suite T ×1 | 60 translate (haiku) + ~170 judge (opus) | ~80k in-out haiku + ~200k opus | ~$3 |
| Suite L ×1 | 36 provider (haiku) + ~60 judge | ~150k opus | ~$2 |
| Suite E ×1 | 128 translate + ~350 judge + ~30 extract | ~450k opus | ~$5 |
| stability 双跑 T | 同 T | — | ~$3 |

全流程（含 Task 9 三基线 + 双跑）**约 $15–20 / 完整周期**；日常回归只跑单 suite。数字为 prompt 预算估算，首跑后以 usage 实测校准进 README。

## Self-review 记录

- **80% 标准的落点**：§0 契约三件套（分数↔用户行为、日常难度校准、macro 防偏科）+ README 首行合同句 + report.py 的 gate 输出——标准不是口号，是代码路径。
- **anchor 对齐**：§8 小规模（60/36/8×16）、自建为主、PrefEval 仅零散借用且 content 条目反用作负例（Task 6）；§2.2 边界——bench 判"编入请求文本"，不判下游产出（§0）；§5 flash 约束只辖产品路径，judge 用强模型已在 config 注释与拍板点 2 说明。
- **"只做 bench"边界**：全部改动落 `bench/`、`tests/test_bench_*`、根 README 一行、conftest.py、.gitignore；`src/` 零改动。ReferenceProvider 在 bench 内、注释明示非 v1 实现。
- **占位符扫描**：无 TBD/TODO；生成扩展类步骤（T 48 条、L 30 条、7 personas）均给全 prompt 全文/审核 checklist/覆盖矩阵与 seed 全文样例，属"材料齐备的执行动作"而非占位。
- **类型一致性**：`Check(kind,name,args)`、`run_check(name,args,*,polished,case_input)`、provider op `{kind,target_id,text}`、expect op `{kind,target,gist}`（target 是 existing 下标，runner 里换算成 id）——跨 task 已核对；`judge()` 返回 `(ok, parse_flag)` 全文件一致；`write_snapshot(suite, cases_path, results)` 的目录分支在 Task 8 Step 4 补齐并有说明。
- **可复现性**：case 进 git、temperature 0、snapshot 带 model id + case hash、stability check 定量化（<5% 翻转）。
- **风险与对策**：judge 抖动（Task 9 抽检 + fail-closed + flags 上报）；translator 输出天然随机（llm.complete 未暴露 temperature——bench 不改 src，接受抖动并用 stability check 定量）；PrefEval 合格条目可能不足（宁缺毋滥，生成流程兜底）；API/网络不可用（harness 全部 FakeLLM 可测，真跑 blocked 不阻塞构建）。
