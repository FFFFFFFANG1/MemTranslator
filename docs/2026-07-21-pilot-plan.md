# Memory-Grounded User Translator — Pilot 实施 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 两周内在 PrefEval 子集上跑通 translator-vs-injection 四臂对照实验（oracle memory 条件），按预注册判据得出 pilot go/no-go 结论。

**Architecture:** 四臂（无记忆 / system prompt 注入 / user context 注入 / translator patch）× 两档下游模型 × 正负两类实例。memory 用 oracle（ground-truth preference 直接当 memory store），把"记忆应用"从"记忆构建"中解耦出来单独验证。全部 LLM 调用走带磁盘缓存的薄 client，可断点续跑、有进度心跳。

**Tech Stack:** Python ≥3.12 + uv；`anthropic` SDK（downstream / translator / judge 默认全走 Anthropic 直连，config 可换）；无 agent 框架，纯脚本 + pytest。

**依据:** [idea.md](idea.md)（原始文稿）+ [diagnosis.md](diagnosis.md)（诊断，本 plan 直接执行其第五节建议）。

---

## 0. 范围与 go/no-go 判据（预注册，跑全量前定稿）

pilot 回答且只回答一个问题：**oracle memory 条件下，把记忆编译进用户输入（translator）是否优于把记忆注入 agent 上下文（system prompt / context 注入）**。

明确不在 pilot 内（GO 后进 Phase 2，见 §9）：feedback→requirement 提取、memory CRUD、CUPID scope 专门实验、retrieval、diff 格式 patch 的完整实现。

**判据（默认值是我的提议，可改数字；但必须在跑全量 run 之前定稿，之后不许放宽）：**

- **G1（adherence 胜利）**：弱下游上，adherence(A3) − max(adherence(A1), adherence(A2)) ≥ **+5pp**，且配对 bootstrap 95% CI 下界 > 0。
- **G2（控制维度换胜利）**：G1 不满足，但弱下游上 adherence(A3) ≥ max(A1,A2) − 2pp，**且**（FAR(A3) ≤ FAR(best-injection) − 10pp **或** A3 下游输入 tokens ≤ 60% × A2）。
- **G3（门槛，独立于 G1/G2）**：translator 在负例上的 no-op 率 P(noop | neg) ≥ **70%**。低于此，false application 风险否掉整个部署故事（诊断第四节），除非 error 分析显示有明确修复方向。
- **GO** = (G1 或 G2) 且 G3。**NO-GO** = 其余情形。
- 强下游上 A3 无优势属预期（CUPID：显式记忆对大模型收益极小甚至为负；BPO：输入侧改写对弱模型收益最大），不单独构成 NO-GO，但必须如实进结论。

---

## 1. 实验设计

### 1.1 四臂

| 臂 | 名称 | memory 到达下游的方式 |
|---|---|---|
| A0 | `A0_none` | 不给。下限 baseline |
| A1 | `A1_system` | 全部 8 条 memory 写进 system prompt（产品内建 memory 风格，如 ChatGPT memory） |
| A2 | `A2_inject` | 全部 8 条 memory 以 `<user_memories>` 块附在 user 消息尾部（RAG 注入风格） |
| A3 | `A3_translator` | translator 读 memory + 原始请求 → 输出 patch → 下游只见 polished request，**不见任何 memory** |

### 1.2 关键设计决定（与理由）

1. **Oracle memory。** memory store 直接用 PrefEval 的 ground-truth preference 文本：正例 = 1 条相关 + 7 条来自其他 topic 的干扰；负例 = 8 条全是干扰。理由：pilot 只测"应用"环节；如果连 oracle 条件下 translator 都打不过注入，提取环节做得再好也没意义。提取噪声会污染对照。
2. **不做 retrieval。** 8 条 memory 全量给 A1/A2/A3，scope 判别全部交给模型。理由：消除 retriever 这个混淆变量，A2 与 A3 看到完全相同的 memory 集合，差异只剩"作用位置"——这正是研究问题。k=8 条短文本，上下文开销可忽略。
3. **下游单轮调用。** 不复现 PrefEval 原始的"偏好陈述 + 多轮间隔对话 + 提问"长上下文设定。理由：本架构的部署设定是跨 session（历史不可得，只有 memory 系统），PrefEval 的长上下文退化结论是本方向的动机，不是对照对象。
4. **Pilot 的 patch = 整体重写 REQUEST 块。** translator 输出 JSON（`noop` 或 `apply + new_request`），harness 只替换 REQUEST、CONTENT 由 harness 原样拼接——translator 在机制上无法触碰用户材料，content preservation 由构造保证。diff 格式的 patch（idea 中的完整设想）在 pilot 中不需要：PrefEval 的 request 都是短句。patch vs full-rewrite 的保真差异用 §1.5 的长输入小集合单独测（Task 12）。
5. **不传 temperature。** claude-opus-4-8 会对 temperature 参数返回 400（sampling 参数已移除），全部调用统一省略；同一 run 内的可复现性由磁盘缓存保证。
6. **translator 对两档下游共用。** translator 输出只依赖 instance，不依赖下游模型，每个 instance 只调一次，polished request 复用给两档下游。

### 1.3 数据构造（PrefEval 子集）

| 集合 | n | 构造 | 用途 |
|---|---|---|---|
| 正例 | 150 | (preference, query) 相关对，按 topic 分层抽样；相关 preference 混入 memory_store 的随机位置 | adherence 主实验 |
| 负例 | 100 | query 来自 topic X，memory_store 8 条全部来自 ≠X 的 topic | FAR / no-op（诊断第四节要求的一等指标） |
| 长输入保真集 | 30 | 短 REQUEST + 300–800 词 CONTENT（生成后人工过目），配相关 preference | 仅 Task 12 preservation ablation，不进 adherence 主表 |

负例的坑：跨 topic 的 preference 可能仍然普适（如"回答要简短"）。对策：构造后用 judge 模型预筛"该 preference 是否可能适用于该 query"，剔除可疑项后人工抽查 30 条（Task 9）。

### 1.4 模型（config 单点定义，可换）

| 角色 | 默认 model ID | 理由 |
|---|---|---|
| downstream 强 | `claude-opus-4-8` | frontier 档；诊断预判此档测不出差异，必须实测确认 |
| downstream 弱 | `claude-haiku-4-5` | 小模型档；BPO 证据下的预期受益区 |
| translator | `claude-haiku-4-5` | idea 明确要求 flash 级即可用；备选 `gemini-2.5-flash`（llm.py 加分支即可） |
| judge | `claude-opus-4-8` | 主指标靠它，用最强档 + 30 条人工校准闸门（Task 9） |

弱下游与 translator 同为 haiku 的 same-family 顾虑：translator 任务是改写不是执行，风险低；如担心，切 translator 为 gemini-2.5-flash 重跑 A3 臂即可（缓存使成本仅为 A3 增量）。

### 1.5 指标（全部在 analyze.py 落地）

| 指标 | 定义 | 数据集 |
|---|---|---|
| adherence | judge 判 followed / violated / not_applicable；adherence = followed/(followed+violated) | 正例 × 4 臂 × 2 下游 |
| FAR (false application rate) | judge 判 response 是否被不适用 memory 带偏 | 负例 × 4 臂 × 2 下游 |
| translator scope 准确率 | 机械统计：P(apply\|正例)、P(noop\|负例)（后者即 G3） | 全部 instance × translator |
| request 语义保真 | judge 判 polished 与 original 是否同一核心任务、是否加了 memory 之外的要求 | 正例 × A3 patch |
| content 保真 | A3 patch 构造保证 100%（报告机制）；full-rewrite 臂机械 diff 测 corruption | 长输入集 × Task 12 |
| token 成本 | 下游 input tokens/instance 分臂统计 + translator 每次调用开销 | 全部 |
| 统计 | 同 instance 配对差值 + bootstrap 95% CI（重采样 2000 次） | — |

---

## 2. Day-1 假设核验清单（Task 1 的闸门）

以下是本 plan 依赖但**我未核验**的二手信息（来源：诊断文稿 + 我的训练记忆），Task 1 逐条核验，任何一条失败先改 plan 再动工：

| # | 假设 | 来源 | 核验方法 |
|---|---|---|---|
| V1 | PrefEval repo 在 `github.com/amazon-science/PrefEval`，含 ~3000 preference、20 topics | 诊断（二手） | clone 后看 README + 数据目录 |
| V2 | 存在 explicit preference + query 的结构化数据文件，可解析出 (topic, preference, query) 三元组 | 推测 | 打开数据文件看字段名，据此改 `load_prefeval()` |
| V3 | repo 自带 LLM judge 的评测 prompt（violation/acknowledgment 判定） | 推测 | 在 repo 里 grep judge/eval prompt；有则优先采用官方版并在 judge.py 注明出处 |
| V4 | license 允许研究使用 | 推测 | 看 LICENSE 文件 |
| V5 | 每 topic 的 (preference, query) 对数量足够支撑 150 正例 + 100 负例的分层抽样 | 推测 | 统计后写进 prefeval-notes.md |

核验结果落盘到 `docs/prefeval-notes.md`（字段表、judge prompt 位置、license、数量统计），这是后续所有 Task 的数据事实来源。

---

## 3. 目录结构

```
MemTranslator/                   ← git repo（github.com/FFFFFFFANG1/MemTranslator）
  docs/
    idea.md                      ← 已存在
    diagnosis.md                 ← 已存在
    2026-07-21-pilot-plan.md     ← 本文件
    prefeval-notes.md            ← Task 1 产出
    pilot-results.md             ← Task 11 产出（自动生成的结果表）
    go-no-go.md                  ← Task 13 产出（决策 memo）
  pilot/
    pyproject.toml
    src/pilot/
      config.py                  ← 模型、路径、常量单点定义
      llm.py                     ← 带缓存/重试的薄 client
      data_prep.py               ← PrefEval → 正/负例 instances
      longdoc_prep.py            ← 长输入保真集
      arms.py                    ← 四臂 prompt 组装
      translator.py              ← translator prompt + patch 应用
      judge.py                   ← 三个 judge + 校准
      run_experiment.py          ← 编排、断点续跑、心跳
      analyze.py                 ← 指标表 + bootstrap CI → pilot-results.md
    tests/
      test_instances.py
      test_arms.py
      test_patch.py
      test_metrics.py
    data/
      raw/                       ← PrefEval clone（gitignore）
      instances/                 ← 生成的 jsonl（提交，保可复现）
    runs/                        ← llm_cache/ + results/（gitignore）
```

编译产物/缓存进 gitignore，最终报告单独在 docs/——符合"产出目录干净"约定。commit 全英文 1–2 句，无 co-author。git 命令串行执行。

---

## Task 0: 项目脚手架

**Files:**
- Create: `pilot/pyproject.toml`, `pilot/src/pilot/__init__.py`, `pilot/src/pilot/config.py`, `.gitignore`

- [ ] **Step 1: 目录与 uv 项目**（git repo、.gitignore、remote 已于 2026-07-21 建好，此处只补 pilot 结构）

```bash
cd "/Users/siriux/Library/Mobile Documents/com~apple~CloudDocs/Documents/Codes/Projects/MemTranslator"
mkdir -p pilot/src/pilot pilot/tests pilot/data/instances pilot/runs
touch pilot/src/pilot/__init__.py
```

- [ ] **Step 2: 写 `pilot/pyproject.toml`**

```toml
[project]
name = "pilot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["anthropic>=0.92"]

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pilot"]
```

- [ ] **Step 3: 写 `.gitignore`（repo 根）**

```
pilot/data/raw/
pilot/runs/
__pycache__/
.pytest_cache/
*.egg-info/
.venv/
.DS_Store
```

- [ ] **Step 4: 写 `pilot/src/pilot/config.py`**

```python
"""Single source of truth for models, paths, and experiment constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # pilot/
DATA = ROOT / "data"
INSTANCES = DATA / "instances"
RUNS = ROOT / "runs"
CACHE_DIR = RUNS / "llm_cache"
RESULTS = RUNS / "results"
DOCS = ROOT.parent / "docs"

MODELS = {
    "downstream_strong": "claude-opus-4-8",
    "downstream_weak": "claude-haiku-4-5",
    "translator": "claude-haiku-4-5",
    "judge": "claude-opus-4-8",
}

ARMS = ["A0_none", "A1_system", "A2_inject", "A3_translator"]
DOWNSTREAM_TIERS = ["downstream_strong", "downstream_weak"]

N_POS = 150
N_NEG = 100
K_DISTRACTORS = 7
SEED = 42
```

- [ ] **Step 5: 环境就绪验证**

```bash
cd pilot && uv sync
uv run python -c "import anthropic, pilot.config as c; print(c.MODELS)"
```
Expected: 打印 MODELS dict，无 ImportError。

- [ ] **Step 6: Commit**

```bash
cd .. && git add -A && git commit -m "[pilot] Scaffold project with uv and experiment config"
```

---

## Task 1: PrefEval 获取与假设核验（闸门）

**Files:**
- Create: `docs/prefeval-notes.md`
- 依赖: §2 核验清单

- [ ] **Step 1: 浅 clone**

```bash
cd pilot/data/raw
git clone --depth 1 https://github.com/amazon-science/PrefEval
```
若 URL 404：搜 "PrefEval ICLR 2025 preference following benchmark github" 找正确 repo，更新本步骤。

- [ ] **Step 2: 逐条核验 §2 的 V1–V5**

```bash
ls PrefEval; cat PrefEval/README.md
find PrefEval -name "*.json" | head -30
grep -ril "judge\|violat\|acknowledg" PrefEval --include="*.py" --include="*.txt" | head
cat PrefEval/LICENSE
```
打开 1–2 个数据文件确认字段名与结构（explicit/implicit 偏好的组织方式、query 在哪个字段）。

- [ ] **Step 3: 写 `docs/prefeval-notes.md`**

内容：TL;DR、数据文件路径与字段表、topic × 条数统计、官方 judge prompt 的位置（或"无，用自研 fallback"）、license 结论、V1–V5 逐条核验结果、对本 plan 的修改点（若有）。数字→出处（repo 文件路径）。

- [ ] **Step 4: 闸门判定**

V2 失败（无法解析三元组）→ 停，改 plan §1.3 与 Task 3 后再继续。V4 失败（license 不允许）→ 停，报告 siriux。

- [ ] **Step 5: Commit**

```bash
git add docs/prefeval-notes.md && git commit -m "[docs] Record PrefEval data layout verification"
```

---

## Task 2: LLM client（缓存 + 重试）

**Files:**
- Create: `pilot/src/pilot/llm.py`

- [ ] **Step 1: 写 `llm.py`**

```python
"""Thin LLM client. Every call in the pilot goes through call():
disk cache keyed by full input -> reproducible + resumable + free re-runs."""
import hashlib
import json
import time

import anthropic

from pilot.config import CACHE_DIR

_client = anthropic.Anthropic()


def call(model: str, user: str, system: str | None = None,
         max_tokens: int = 2048) -> dict:
    """Returns {"text", "input_tokens", "output_tokens", "cached"}."""
    key = hashlib.sha256(json.dumps(
        [model, system, user, max_tokens],
        ensure_ascii=False).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        out = json.loads(cache_file.read_text())
        out["cached"] = True
        return out

    last_err = None
    for attempt in range(4):
        try:
            kwargs = dict(model=model, max_tokens=max_tokens,
                          messages=[{"role": "user", "content": user}])
            if system is not None:
                kwargs["system"] = system
            resp = _client.messages.create(**kwargs)
            text = "".join(b.text for b in resp.content if b.type == "text")
            out = {"text": text,
                   "input_tokens": resp.usage.input_tokens,
                   "output_tokens": resp.usage.output_tokens}
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(out, ensure_ascii=False))
            out["cached"] = False
            return out
        except (anthropic.RateLimitError, anthropic.InternalServerError,
                anthropic.APIConnectionError) as e:
            last_err = e
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"LLM call failed after retries: {last_err!r}")
```

注意：4xx（如 BadRequestError）不重试直接抛——那是代码错误不是瞬时故障。temperature/thinking 均不传（§1.2-5）。

- [ ] **Step 2: smoke 验证（真实调用 ×1 + 缓存命中 ×1）**

```bash
cd pilot
uv run python -c "
from pilot.llm import call
r1 = call('claude-haiku-4-5', 'Reply with exactly: ok')
r2 = call('claude-haiku-4-5', 'Reply with exactly: ok')
print(r1['text'], r1['cached'], r2['cached'])"
```
Expected: `ok False True`（第二次命中缓存）。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "[pilot] Add cached LLM client with retry on transient errors"
```

---

## Task 3: 实例构造（data_prep.py）

**Files:**
- Create: `pilot/src/pilot/data_prep.py`
- Test: `pilot/tests/test_instances.py`

- [ ] **Step 1: 写失败测试（用假数据，不依赖 PrefEval）**

```python
# pilot/tests/test_instances.py
from pilot.data_prep import build_instances


def fake_items():
    return [{"topic": f"t{i}", "preference": f"pref-{i}-{j}",
             "query": f"query-{i}-{j}"}
            for i in range(10) for j in range(30)]


def test_counts_and_shape():
    pos, neg = build_instances(fake_items(), n_pos=20, n_neg=10)
    assert len(pos) == 20 and len(neg) == 10
    for inst in pos + neg:
        assert len(inst["memory_store"]) == 8
        assert inst["content"] == ""


def test_positive_has_exactly_one_relevant_memory():
    pos, _ = build_instances(fake_items(), n_pos=20, n_neg=10)
    for inst in pos:
        hits = [m for m in inst["memory_store"]
                if m["mid"] == inst["relevant_memory_id"]]
        assert len(hits) == 1
        assert hits[0]["text"] == inst["preference"]
        others = [m for m in inst["memory_store"]
                  if m["mid"] != inst["relevant_memory_id"]]
        assert all(m["topic"] != inst["topic"] for m in others)


def test_negative_has_no_same_topic_memory():
    _, neg = build_instances(fake_items(), n_pos=20, n_neg=10)
    for inst in neg:
        assert inst["preference"] is None
        assert all(m["topic"] != inst["topic"] for m in inst["memory_store"])


def test_deterministic():
    a = build_instances(fake_items(), n_pos=20, n_neg=10)
    b = build_instances(fake_items(), n_pos=20, n_neg=10)
    assert a == b
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_instances.py -q
```
Expected: FAIL（ImportError / build_instances 不存在）。

- [ ] **Step 3: 写 `data_prep.py`**

```python
"""Build pilot instances from PrefEval.
The LOADER section encodes assumptions verified in docs/prefeval-notes.md
(Task 1) -- adjust paths/field names there if the repo layout differs;
keep load_prefeval()'s return schema unchanged."""
import json
import random

from pilot.config import (DATA, INSTANCES, K_DISTRACTORS, N_NEG, N_POS, SEED)

RAW = DATA / "raw" / "PrefEval"


# ---- LOADER: 唯一允许依赖 PrefEval 文件布局的地方（按 Task 1 核验结果修改） ----
def load_prefeval() -> list[dict]:
    """Returns [{"topic": str, "preference": str, "query": str}, ...].

    ASSUMPTION (V2, verify in Task 1): a data directory holds per-topic JSON
    with explicit-preference entries carrying a preference text and a related
    user query. Update the glob and the two field names below to match
    docs/prefeval-notes.md; nothing else in the pilot reads the repo.
    """
    items = []
    for f in sorted((RAW / "benchmark_dataset").glob("*.json")):
        for row in json.loads(f.read_text()):
            items.append({"topic": f.stem,
                          "preference": row["preference"],
                          "query": row["question"]})
    return items
# --------------------------------------------------------------------------


def _mem(rng, mid, text, topic):
    return {"mid": mid, "text": text, "topic": topic}


def _distractors(rng, by_topic, exclude_topic, k):
    pool = [(t, it) for t, its in by_topic.items()
            if t != exclude_topic for it in its]
    picks = rng.sample(pool, k)
    return [(t, it["preference"]) for t, it in picks]


def build_instances(items, n_pos=N_POS, n_neg=N_NEG, k=K_DISTRACTORS):
    rng = random.Random(SEED)
    by_topic = {}
    for it in items:
        by_topic.setdefault(it["topic"], []).append(it)
    topics = sorted(by_topic)

    # 分层：轮转 topic 抽样，保证覆盖
    def stratified(n):
        picked, i = [], 0
        used = {t: set() for t in topics}
        while len(picked) < n:
            t = topics[i % len(topics)]
            avail = [j for j in range(len(by_topic[t])) if j not in used[t]]
            if avail:
                j = rng.choice(avail)
                used[t].add(j)
                picked.append((t, by_topic[t][j]))
            i += 1
        return picked

    positives = []
    for idx, (t, it) in enumerate(stratified(n_pos)):
        mems = [(t, it["preference"])] + _distractors(rng, by_topic, t, k)
        rng.shuffle(mems)
        store = [_mem(rng, f"m{i+1}", text, mt)
                 for i, (mt, text) in enumerate(mems)]
        rel = next(m["mid"] for m in store if m["text"] == it["preference"]
                   and m["topic"] == t)
        positives.append({
            "id": f"pos-{t}-{idx:04d}", "kind": "positive", "topic": t,
            "preference": it["preference"], "request": it["query"],
            "content": "", "memory_store": store, "relevant_memory_id": rel,
        })

    negatives = []
    for idx, (t, it) in enumerate(stratified(n_neg)):
        mems = _distractors(rng, by_topic, t, k + 1)
        store = [_mem(rng, f"m{i+1}", text, mt)
                 for i, (mt, text) in enumerate(mems)]
        negatives.append({
            "id": f"neg-{t}-{idx:04d}", "kind": "negative", "topic": t,
            "preference": None, "request": it["query"],
            "content": "", "memory_store": store, "relevant_memory_id": None,
        })
    return positives, negatives


def main():
    items = load_prefeval()
    pos, neg = build_instances(items)
    INSTANCES.mkdir(parents=True, exist_ok=True)
    out = INSTANCES / "pilot.jsonl"
    with out.open("w") as f:
        for inst in pos + neg:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
    topics = {i["topic"] for i in pos + neg}
    print(f"{len(pos)} positive + {len(neg)} negative -> {out}")
    print(f"{len(topics)} topics covered")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 测试通过 + 真实数据生成**

```bash
uv run pytest tests/test_instances.py -q          # Expected: 4 passed
uv run python -m pilot.data_prep                  # Expected: 150 positive + 100 negative -> .../pilot.jsonl
```
LOADER 若因字段名报错，按 prefeval-notes.md 修正后重跑（这是设计内的调整点，不改 schema）。

- [ ] **Step 5: 人工抽查 5 条正例 + 5 条负例**（`head`/`jq` 看 request 与 memory 是否合理配对），发现构造 bug 回 Step 3。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "[pilot] Build positive and negative instances from PrefEval"
```

---

## Task 4: 长输入保真集（longdoc_prep.py）

**Files:**
- Create: `pilot/src/pilot/longdoc_prep.py`

- [ ] **Step 1: 写 `longdoc_prep.py`**

用强模型生成 30 条伪材料（避免引外部抓取依赖；材料本身真假不影响保真测量——测的是"改写是否动了材料"）：

```python
"""Generate 30 long-content instances for the preservation ablation (Task 12).
Each: a short analysis-type request + 300-800 word attached material +
one applicable preference from PrefEval. Human-review the output file."""
import json
import random

from pilot import llm
from pilot.config import INSTANCES, MODELS, SEED
from pilot.data_prep import build_instances, load_prefeval

KINDS = ["a research paper abstract", "an email thread (3 messages)",
         "a project README section", "a meeting-notes excerpt",
         "a product review", "a short technical blog post"]

GEN_SYSTEM = ("Write realistic synthetic text for benchmark construction. "
              "Output only the text, no preamble.")


def main():
    rng = random.Random(SEED)
    pos, _ = build_instances(load_prefeval(), n_pos=30, n_neg=0)
    out = INSTANCES / "longdoc.jsonl"
    with out.open("w") as f:
        for i, inst in enumerate(pos):
            kind = KINDS[i % len(KINDS)]
            doc = llm.call(
                MODELS["downstream_strong"],
                f"Write {kind}, 300-800 words, on any everyday topic. "
                f"Seed: {rng.randint(0, 10**6)}",
                system=GEN_SYSTEM, max_tokens=2048)["text"].strip()
            inst = dict(inst)
            inst["id"] = f"long-{i:04d}"
            inst["kind"] = "longdoc"
            inst["request"] = f"Please take a look at the following {kind.split(' (')[0]} and share your thoughts."
            inst["content"] = doc
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")
            print(f"[{i+1}/30] {inst['id']}", flush=True)
    print(f"-> {out}  (human-review before use)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 生成并人工过目**

```bash
uv run python -m pilot.longdoc_prep
```
Expected: 30 行 jsonl。抽 5 条读 content 是否像样、request 是否与 preference 可发生作用。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "[pilot] Generate long-content instances for the preservation ablation"
```

---

## Task 5: 四臂 prompt 组装（arms.py）

**Files:**
- Create: `pilot/src/pilot/arms.py`
- Test: `pilot/tests/test_arms.py`

- [ ] **Step 1: 写失败测试**

```python
# pilot/tests/test_arms.py
from pilot.arms import build_downstream_call

INST = {"request": "Recommend a restaurant in Seattle.", "content": "",
        "memory_store": [{"mid": f"m{i}", "text": f"pref text {i}",
                          "topic": "t"} for i in range(1, 9)]}


def test_a0_clean():
    system, user = build_downstream_call("A0_none", INST)
    assert "pref text" not in system + user
    assert INST["request"] in user


def test_a1_memories_in_system_only():
    system, user = build_downstream_call("A1_system", INST)
    assert all(f"pref text {i}" in system for i in range(1, 9))
    assert "pref text" not in user


def test_a2_memories_in_user_only():
    system, user = build_downstream_call("A2_inject", INST)
    assert all(f"pref text {i}" in user for i in range(1, 9))
    assert "pref text" not in system


def test_a3_uses_polished_and_no_memories():
    system, user = build_downstream_call(
        "A3_translator", INST, polished_request="Recommend a vegan restaurant in Seattle.")
    assert "vegan" in user and "pref text" not in system + user


def test_content_appended_verbatim():
    inst = dict(INST, content="RAW-MATERIAL-XYZ do not touch")
    for arm, pol in [("A0_none", None), ("A3_translator", "rewritten req")]:
        _, user = build_downstream_call(arm, inst, polished_request=pol)
        assert "RAW-MATERIAL-XYZ do not touch" in user
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_arms.py -q
```
Expected: FAIL（ImportError）。

- [ ] **Step 3: 写 `arms.py`**

```python
"""Prompt assembly for the four arms. Downstream sees ONLY what its arm allows."""

DOWNSTREAM_SYSTEM = "You are a helpful assistant."

MEMORY_HEADER = (
    "The following are stored long-term memories about this user, collected "
    "from past conversations. Apply them when they are relevant to the "
    "current request.")


def _memory_block(memories):
    return "\n".join(f"- [{m['mid']}] {m['text']}" for m in memories)


def _with_content(request, content):
    return request if not content else f"{request}\n\n{content}"


def build_downstream_call(arm, instance, polished_request=None):
    """Returns (system, user_text) for one downstream call."""
    req = instance["request"]
    content = instance["content"]
    if arm == "A0_none":
        return DOWNSTREAM_SYSTEM, _with_content(req, content)
    if arm == "A1_system":
        system = (f"{DOWNSTREAM_SYSTEM}\n\n{MEMORY_HEADER}\n"
                  f"{_memory_block(instance['memory_store'])}")
        return system, _with_content(req, content)
    if arm == "A2_inject":
        user = (f"{_with_content(req, content)}\n\n<user_memories>\n"
                f"{_memory_block(instance['memory_store'])}\n</user_memories>")
        return DOWNSTREAM_SYSTEM, user
    if arm == "A3_translator":
        if polished_request is None:
            raise ValueError("A3 requires polished_request")
        return DOWNSTREAM_SYSTEM, _with_content(polished_request, content)
    raise ValueError(f"unknown arm: {arm}")
```

- [ ] **Step 4: 测试通过**

```bash
uv run pytest tests/test_arms.py -q
```
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "[pilot] Add four-arm downstream prompt assembly"
```

---

## Task 6: Translator（translator.py）

**Files:**
- Create: `pilot/src/pilot/translator.py`
- Test: `pilot/tests/test_patch.py`

- [ ] **Step 1: 写失败测试**

```python
# pilot/tests/test_patch.py
from pilot.translator import apply_patch, parse_patch

INST = {"request": "original request", "content": "MATERIAL"}


def test_noop_keeps_original():
    assert apply_patch(INST, {"decision": "noop"}) == "original request"


def test_apply_replaces_request_only():
    p = {"decision": "apply", "applied_memory_ids": ["m2"],
         "new_request": "better request"}
    assert apply_patch(INST, p) == "better request"


def test_malformed_json_falls_back_to_noop():
    patch, err = parse_patch("not json at all")
    assert patch == {"decision": "noop"} and err is True


def test_fenced_json_ok():
    patch, err = parse_patch(
        '```json\n{"decision": "apply", "applied_memory_ids": ["m1"], '
        '"new_request": "x"}\n```')
    assert patch["decision"] == "apply" and err is False


def test_apply_without_new_request_is_noop():
    patch, err = parse_patch('{"decision": "apply"}')
    assert patch == {"decision": "noop"} and err is True
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_patch.py -q
```
Expected: FAIL（ImportError）。

- [ ] **Step 3: 写 `translator.py`**

```python
"""The user translator: rewrites the request iff a stored memory applies.
Content preservation is by construction: only the request string is ever
replaced; attached content is assembled by arms.py from the instance."""
import json

from pilot import llm
from pilot.arms import _memory_block
from pilot.config import MODELS

TRANSLATOR_SYSTEM = """You are a user-input translator sitting between a user and an AI assistant.
You receive the user's raw request plus the user's stored preference memories.
Your job: rewrite the request ONLY when some stored memory clearly applies to it, so that the assistant can satisfy the user without ever seeing the memories.

Rules:
1. If no stored memory clearly applies to this request, output a no-op. When uncertain, prefer no-op -- an underspecified request is often intentional.
2. Never invent requirements that are not grounded in a stored memory.
3. Never change the core task the user is asking for; only make implicit, memory-backed requirements explicit.
4. Never touch, summarize, or rewrite any material the user attached (documents, code, data). You may only rewrite the request itself.
5. Keep the rewritten request natural, as if the user had typed it themselves. Do not mention memories, profiles, or this translation step.

Output strictly one JSON object, nothing else:
{"decision": "noop"}
or
{"decision": "apply", "applied_memory_ids": ["m3"], "new_request": "..."}"""


def _translator_user(instance):
    mem = _memory_block(instance["memory_store"])
    content_note = ""
    if instance["content"]:
        head = instance["content"][:1500]
        content_note = ("\n\nAttached material (first 1500 chars, shown for "
                        f"context only -- DO NOT rewrite it):\n{head}")
    return (f"Stored user memories:\n{mem}\n\n"
            f"User request:\n{instance['request']}{content_note}\n\nJSON:")


def parse_patch(raw: str) -> tuple[dict, bool]:
    """Returns (patch, parse_error). Any failure degrades to noop."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.removeprefix("json").strip()
    try:
        patch = json.loads(s)
        if patch.get("decision") == "noop":
            return {"decision": "noop"}, False
        if (patch.get("decision") == "apply"
                and isinstance(patch.get("new_request"), str)
                and patch["new_request"].strip()):
            return {"decision": "apply",
                    "applied_memory_ids": patch.get("applied_memory_ids", []),
                    "new_request": patch["new_request"].strip()}, False
    except json.JSONDecodeError:
        pass
    return {"decision": "noop"}, True


def apply_patch(instance, patch) -> str:
    if patch.get("decision") == "apply" and patch.get("new_request"):
        return patch["new_request"]
    return instance["request"]


def translate(instance) -> dict:
    """Returns {"patch", "polished_request", "parse_error", tokens...}."""
    out = llm.call(MODELS["translator"], _translator_user(instance),
                   system=TRANSLATOR_SYSTEM, max_tokens=1024)
    patch, parse_error = parse_patch(out["text"])
    return {"patch": patch,
            "polished_request": apply_patch(instance, patch),
            "parse_error": parse_error,
            "translator_input_tokens": out["input_tokens"],
            "translator_output_tokens": out["output_tokens"]}
```

- [ ] **Step 4: 测试通过 + 单条真实 smoke**

```bash
uv run pytest tests/test_patch.py -q      # Expected: 5 passed
uv run python -c "
import json
from pilot.translator import translate
inst = json.loads(open('data/instances/pilot.jsonl').readline())
r = translate(inst)
print(json.dumps(r['patch'], indent=2)); print(r['polished_request'])"
```
Expected: 合法 JSON patch；正例大概率 `apply` 且 new_request 融入了偏好。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "[pilot] Add translator with noop-default patching and robust parsing"
```

---

## Task 7: Judges（judge.py）

**Files:**
- Create: `pilot/src/pilot/judge.py`

前提：若 Task 1 发现 PrefEval 官方 judge prompt（V3），adherence 用官方版并在文件头注明出处；下面的 fallback 版本保留作负例 FAR / preservation 用（官方无对应物）。

- [ ] **Step 1: 写 `judge.py`**

```python
"""LLM judges. Adherence prefers PrefEval's official prompt if found in
Task 1 (cite path in docs/prefeval-notes.md); FAR and preservation are ours.
All judges output strict JSON and are calibrated in Task 9."""
import json

from pilot import llm
from pilot.arms import _memory_block
from pilot.config import MODELS

ADHERENCE_SYSTEM = """You evaluate whether an AI assistant's response respects a user's stated preference.
Judge only the response text. Output strictly one JSON object:
{"verdict": "followed" | "violated" | "not_applicable", "reason": "..."}
- "followed": the response respects the preference (explicitly or implicitly).
- "violated": the response contradicts or ignores the preference where it clearly applied.
- "not_applicable": the preference genuinely does not bear on this request."""

FAR_SYSTEM = """You check whether an AI assistant's response was inappropriately steered by stored user memories that do NOT apply to the request.
Output strictly one JSON object:
{"steered": true | false, "steering_memory_ids": ["m2"], "reason": "..."}
"steered" is true only if the response's content, constraints, or style was clearly shaped by one of the listed memories even though that memory is irrelevant to this request. Generic helpfulness is not steering."""

PRESERVE_SYSTEM = """You compare an original user request with a rewritten version, given the user's stored memories.
Output strictly one JSON object:
{"same_core_task": true | false, "added_beyond_memories": true | false, "reason": "..."}
- same_core_task: both versions ask for the same underlying thing.
- added_beyond_memories: the rewrite adds requirements NOT grounded in any provided memory."""


def _parse(raw: str, default: dict) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").removeprefix("json").strip()
    try:
        d = json.loads(s)
        d["judge_parse_error"] = False
        return d
    except json.JSONDecodeError:
        return {**default, "judge_parse_error": True}


def judge_adherence(preference, request, response):
    user = (f"User preference: {preference}\n\nUser request: {request}\n\n"
            f"Assistant response:\n{response}\n\nJSON:")
    out = llm.call(MODELS["judge"], user, system=ADHERENCE_SYSTEM,
                   max_tokens=1024)
    return _parse(out["text"], {"verdict": "not_applicable", "reason": ""})


def judge_far(memories, request, response):
    user = (f"Stored memories (all irrelevant to this request):\n"
            f"{_memory_block(memories)}\n\nUser request: {request}\n\n"
            f"Assistant response:\n{response}\n\nJSON:")
    out = llm.call(MODELS["judge"], user, system=FAR_SYSTEM, max_tokens=1024)
    return _parse(out["text"], {"steered": False, "reason": ""})


def judge_preservation(memories, original, rewritten):
    user = (f"Stored memories:\n{_memory_block(memories)}\n\n"
            f"Original request: {original}\n\n"
            f"Rewritten request: {rewritten}\n\nJSON:")
    out = llm.call(MODELS["judge"], user, system=PRESERVE_SYSTEM,
                   max_tokens=1024)
    return _parse(out["text"], {"same_core_task": True,
                                "added_beyond_memories": False, "reason": ""})
```

- [ ] **Step 2: 单条 smoke**

```bash
uv run python -c "
from pilot.judge import judge_adherence
print(judge_adherence('The user avoids seafood.',
                      'Recommend a restaurant in Seattle.',
                      'Try the salmon at Pike Place Chowder!'))"
```
Expected: `verdict: violated`。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "[pilot] Add adherence, false-application, and preservation judges"
```

---

## Task 8: 编排（run_experiment.py）

**Files:**
- Create: `pilot/src/pilot/run_experiment.py`

- [ ] **Step 1: 写 `run_experiment.py`**

```python
"""Orchestrates the pilot: per instance -> translate once -> 4 arms x 2
downstream tiers -> judges -> append one JSON line. Resumable by id;
heartbeat printed per instance (run under nohup for the full run)."""
import argparse
import json
import time

from pilot import llm
from pilot.arms import build_downstream_call
from pilot.config import (ARMS, DOWNSTREAM_TIERS, INSTANCES, MODELS, RESULTS)
from pilot.judge import judge_adherence, judge_far, judge_preservation
from pilot.translator import translate


def load_instances(path):
    return [json.loads(l) for l in path.open()]


def process_one(inst):
    row = {"id": inst["id"], "kind": inst["kind"], "topic": inst["topic"]}
    tr = translate(inst)
    row["translator"] = {k: v for k, v in tr.items() if k != "polished_request"}
    row["polished_request"] = tr["polished_request"]

    if inst["kind"] == "positive":
        row["preservation"] = judge_preservation(
            inst["memory_store"], inst["request"], tr["polished_request"])

    row["arms"] = {}
    for tier in DOWNSTREAM_TIERS:
        model = MODELS[tier]
        for arm in ARMS:
            polished = tr["polished_request"] if arm == "A3_translator" else None
            system, user = build_downstream_call(arm, inst, polished)
            resp = llm.call(model, user, system=system, max_tokens=1024)
            cell = {"input_tokens": resp["input_tokens"],
                    "output_tokens": resp["output_tokens"]}
            if inst["kind"] == "positive":
                cell["adherence"] = judge_adherence(
                    inst["preference"], inst["request"], resp["text"])
            else:
                cell["far"] = judge_far(
                    inst["memory_store"], inst["request"], resp["text"])
            row["arms"][f"{tier}/{arm}"] = cell
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="pilot")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--instances", default=str(INSTANCES / "pilot.jsonl"))
    ap.add_argument("--dry-run", action="store_true",
                    help="print planned call counts and exit")
    args = ap.parse_args()

    from pathlib import Path
    instances = load_instances(Path(args.instances))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / f"{args.run_id}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.open()}
    todo = [i for i in instances if i["id"] not in done]
    if args.limit:
        todo = todo[:args.limit]

    n_down = len(todo) * len(ARMS) * len(DOWNSTREAM_TIERS)
    print(f"{len(todo)} instances to run ({len(done)} already done); "
          f"~{len(todo)} translator + {n_down} downstream + ~{n_down} judge calls")
    if args.dry_run:
        return

    t0 = time.time()
    with out_path.open("a") as f:
        for n, inst in enumerate(todo, 1):
            row = process_one(inst)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            el = time.time() - t0
            eta = el / n * (len(todo) - n) / 60
            print(f"[{n}/{len(todo)}] {inst['id']} done "
                  f"({el:.0f}s elapsed, ~{eta:.0f}m left)", flush=True)
    print(f"-> {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: dry-run + smoke n=3**

```bash
uv run python -m pilot.run_experiment --dry-run
uv run python -m pilot.run_experiment --run-id smoke --limit 3
```
Expected: dry-run 打印 ~250/2000/2000 调用数；smoke 产出 3 行 jsonl，每行含 8 个 arm cell。打开看一遍结构。

- [ ] **Step 3: 断点续跑验证**

```bash
uv run python -m pilot.run_experiment --run-id smoke --limit 5
```
Expected: 首行打印 "2 instances to run (3 already done)"（跳过已完成）。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "[pilot] Add resumable orchestrator with per-instance heartbeat"
```

---

## Task 9: Judge 校准 + 负例筛查（闸门，需要 siriux ~30 分钟）

**Files:**
- Create: `pilot/src/pilot/calibrate.py`

- [ ] **Step 1: 写 `calibrate.py`**

```python
"""Two gates before the full run:
(a) negative-set screening: judge flags cross-topic memories that might still
    apply; flagged instances are dropped after human confirmation.
(b) judge calibration: sample 30 judged cells from the smoke run into a TSV;
    human fills a 'human' column; this script then reports agreement."""
import argparse
import csv
import json
import random

from pilot import llm
from pilot.config import INSTANCES, MODELS, RESULTS, SEED

SCREEN_SYSTEM = """Given a user query and one stored preference from a DIFFERENT topic, answer whether the preference could still plausibly constrain a good answer to this query (e.g. universal style preferences).
Output strictly: {"could_apply": true | false}"""


def _could_apply(raw: str) -> bool:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`").removeprefix("json").strip()
    try:
        return bool(json.loads(s).get("could_apply"))
    except json.JSONDecodeError:
        return True   # unparseable -> flag for human review, never silently pass


def screen_negatives():
    path = INSTANCES / "pilot.jsonl"
    insts = [json.loads(l) for l in path.open()]
    flagged = []
    for inst in insts:
        if inst["kind"] != "negative":
            continue
        for m in inst["memory_store"]:
            out = llm.call(MODELS["judge"],
                           f"Query: {inst['request']}\nPreference: {m['text']}"
                           f"\nJSON:", system=SCREEN_SYSTEM, max_tokens=256)
            if _could_apply(out["text"]):
                flagged.append((inst["id"], m["mid"], m["text"]))
                break
    print(f"{len(flagged)} negatives flagged for human review:")
    for row in flagged:
        print("  ", *row)
    (INSTANCES / "neg_flagged.json").write_text(json.dumps(flagged, indent=2))


def export_calibration(run_id="smoke", n=30):
    rows = [json.loads(l) for l in (RESULTS / f"{run_id}.jsonl").open()]
    rng = random.Random(SEED)
    cells = []
    for r in rows:
        for key, cell in r["arms"].items():
            if "adherence" in cell:
                cells.append((r["id"], key, "adherence",
                              cell["adherence"]["verdict"]))
            if "far" in cell:
                cells.append((r["id"], key, "far",
                              str(cell["far"]["steered"])))
    sample = rng.sample(cells, min(n, len(cells)))
    out = RESULTS / "calibration.tsv"
    with out.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["instance_id", "arm", "metric", "judge_label", "human"])
        for row in sample:
            w.writerow([*row, ""])
    print(f"-> {out}: fill the 'human' column, then run --score")


def score_calibration():
    with (RESULTS / "calibration.tsv").open() as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    done = [r for r in rows if r["human"].strip()]
    agree = sum(r["judge_label"].lower() == r["human"].strip().lower()
                for r in done)
    print(f"agreement: {agree}/{len(done)} = {agree/len(done):.0%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["screen", "export", "score"])
    ap.add_argument("--run-id", default="smoke")
    args = ap.parse_args()
    {"screen": screen_negatives,
     "export": lambda: export_calibration(args.run_id),
     "score": score_calibration}[args.mode]()
```

- [ ] **Step 2: 跑负例筛查，人工确认 flagged 项**

```bash
uv run python -m pilot.calibrate screen
```
被 flag 的负例由 siriux 过目：确属"跨 topic 仍适用"→ 从 pilot.jsonl 剔除并在 data_prep 里补抽（保持 n=100）；误报 → 保留。

- [ ] **Step 3: 先跑 smoke n=20，导出校准表**

```bash
uv run python -m pilot.run_experiment --run-id smoke --limit 20
uv run python -m pilot.calibrate export --run-id smoke
```

- [ ] **Step 4: siriux 填 `runs/results/calibration.tsv` 的 human 列（~20 分钟），然后：**

```bash
uv run python -m pilot.calibrate score
```
**闸门**：agreement ≥ 85% 通过；否则改 judge prompt（Task 7）→ 清掉受影响缓存 → 重校准。judge 不可靠时任何下游结论都无效，不许跳过。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "[pilot] Add negative-set screening and judge calibration gates"
```

---

## Task 10: 全量 run

- [ ] **Step 1: 复核成本（--dry-run 打印调用数，对照 §8 预算）**

```bash
uv run python -m pilot.run_experiment --dry-run
```

- [ ] **Step 2: 后台跑 + 心跳可查**

```bash
cd pilot
nohup uv run python -m pilot.run_experiment --run-id pilot-full \
  > runs/pilot-full.log 2>&1 &
echo $! > runs/pilot-full.pid
tail -f runs/pilot-full.log        # 随时看心跳；Ctrl-C 只断开 tail
```
预计串行 3–5 小时（~4400 次调用 × 2–4s）。中断后重跑同一命令自动续跑（llm 缓存 + jsonl resume 双保险）。

- [ ] **Step 3: 完成检查**

```bash
wc -l runs/results/pilot-full.jsonl     # Expected: 250
grep -c '"parse_error": true' runs/results/pilot-full.jsonl   # translator 解析失败数，>10 需先查
```

- [ ] **Step 4: Commit（只提交 log 摘要说明，不提交 runs/）**

```bash
git add -A && git commit -m "[pilot] Record full run completion notes"
```

---

## Task 11: 分析（analyze.py）

**Files:**
- Create: `pilot/src/pilot/analyze.py`
- Test: `pilot/tests/test_metrics.py`

- [ ] **Step 1: 写失败测试（bootstrap 与配对差值的纯函数）**

```python
# pilot/tests/test_metrics.py
from pilot.analyze import bootstrap_ci, paired_delta_ci


def test_bootstrap_degenerate():
    mean, lo, hi = bootstrap_ci([1, 1, 1, 1])
    assert mean == lo == hi == 1.0


def test_bootstrap_range():
    mean, lo, hi = bootstrap_ci([0, 1] * 50)
    assert 0.35 < lo <= mean <= hi < 0.65


def test_paired_delta_sign():
    a = [1] * 80 + [0] * 20   # 80%
    b = [1] * 60 + [0] * 40   # 60%
    delta, lo, hi = paired_delta_ci(a, b)
    assert 0.15 < delta < 0.25 and lo > 0
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_metrics.py -q
```
Expected: FAIL（ImportError）。

- [ ] **Step 3: 写 `analyze.py`**

```python
"""Aggregate pilot results -> docs/pilot-results.md with all §1.5 metrics.
Adherence excludes not_applicable and judge_parse_error cells (counts shown)."""
import argparse
import json
import random
from collections import defaultdict

from pilot.config import ARMS, DOCS, DOWNSTREAM_TIERS, RESULTS, SEED


def bootstrap_ci(flags, n_boot=2000, seed=SEED):
    rng = random.Random(seed)
    if not flags:
        return float("nan"), float("nan"), float("nan")
    means = sorted(sum(rng.choices(flags, k=len(flags))) / len(flags)
                   for _ in range(n_boot))
    return (sum(flags) / len(flags),
            means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1])


def paired_delta_ci(a, b, n_boot=2000, seed=SEED):
    """a, b: same-length 0/1 lists over the same instances."""
    rng = random.Random(seed)
    idx = list(range(len(a)))
    deltas = sorted(
        sum(a[i] for i in (s := rng.choices(idx, k=len(idx)))) / len(idx)
        - sum(b[i] for i in s) / len(idx)
        for _ in range(n_boot))
    delta = sum(a) / len(a) - sum(b) / len(b)
    return delta, deltas[int(0.025 * n_boot)], deltas[int(0.975 * n_boot) - 1]


def collect(rows):
    """-> {(tier, arm): {"adh": {id: 0/1}, "far": {id: 0/1}}}, translator stats"""
    cells = defaultdict(lambda: {"adh": {}, "far": {}, "in_tok": []})
    tr = {"pos_apply": 0, "pos_total": 0, "neg_noop": 0, "neg_total": 0,
          "parse_err": 0, "preserve_bad_task": 0, "preserve_overreach": 0}
    for r in rows:
        d = r["translator"]["patch"]["decision"]
        tr["parse_err"] += r["translator"]["parse_error"]
        if r["kind"] == "positive":
            tr["pos_total"] += 1
            tr["pos_apply"] += (d == "apply")
            p = r.get("preservation", {})
            tr["preserve_bad_task"] += (p.get("same_core_task") is False)
            tr["preserve_overreach"] += (p.get("added_beyond_memories") is True)
        else:
            tr["neg_total"] += 1
            tr["neg_noop"] += (d == "noop")
        for key, cell in r["arms"].items():
            tier, arm = key.split("/")
            cells[(tier, arm)]["in_tok"].append(cell["input_tokens"])
            if "adherence" in cell:
                a = cell["adherence"]
                if not a.get("judge_parse_error") and a["verdict"] in (
                        "followed", "violated"):
                    cells[(tier, arm)]["adh"][r["id"]] = int(
                        a["verdict"] == "followed")
            if "far" in cell:
                fa = cell["far"]
                if not fa.get("judge_parse_error"):
                    cells[(tier, arm)]["far"][r["id"]] = int(
                        bool(fa["steered"]))
    return cells, tr


def fmt_pct(triple):
    m, lo, hi = triple
    return f"{m:.1%} [{lo:.1%}, {hi:.1%}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="pilot-full")
    args = ap.parse_args()
    rows = [json.loads(l)
            for l in (RESULTS / f"{args.run_id}.jsonl").open()]
    cells, tr = collect(rows)

    lines = [f"# Pilot results — run `{args.run_id}`", "",
             f"n = {len(rows)} instances "
             f"({tr['pos_total']} positive, {tr['neg_total']} negative)", ""]

    lines += ["## Adherence (positive set)", "",
              "| tier | arm | n | adherence [95% CI] |", "|---|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        for arm in ARMS:
            adh = cells[(tier, arm)]["adh"]
            lines.append(f"| {tier} | {arm} | {len(adh)} | "
                         f"{fmt_pct(bootstrap_ci(list(adh.values())))} |")

    lines += ["", "## Paired deltas: A3 vs best injection arm", "",
              "| tier | comparison | delta [95% CI] |", "|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        a3 = cells[(tier, "A3_translator")]["adh"]
        for other in ("A1_system", "A2_inject"):
            o = cells[(tier, other)]["adh"]
            common = sorted(set(a3) & set(o))
            if common:
                d = paired_delta_ci([a3[i] for i in common],
                                    [o[i] for i in common])
                lines.append(f"| {tier} | A3 − {other} | "
                             f"{d[0]:+.1%} [{d[1]:+.1%}, {d[2]:+.1%}] |")

    lines += ["", "## False application rate (negative set)", "",
              "| tier | arm | n | FAR [95% CI] |", "|---|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        for arm in ARMS:
            far = cells[(tier, arm)]["far"]
            lines.append(f"| {tier} | {arm} | {len(far)} | "
                         f"{fmt_pct(bootstrap_ci(list(far.values())))} |")

    lines += ["", "## Translator behavior", "",
              f"- P(apply | positive) = {tr['pos_apply']}/{tr['pos_total']}"
              f" = {tr['pos_apply']/max(tr['pos_total'],1):.1%}",
              f"- P(noop | negative) = {tr['neg_noop']}/{tr['neg_total']}"
              f" = {tr['neg_noop']/max(tr['neg_total'],1):.1%}  ← 判据 G3",
              f"- parse errors: {tr['parse_err']}",
              f"- preservation: core-task changed {tr['preserve_bad_task']},"
              f" over-reach beyond memories {tr['preserve_overreach']}"
              f" (of {tr['pos_total']} positives)"]

    lines += ["", "## Downstream input tokens (mean per instance)", "",
              "| tier | arm | mean input tokens |", "|---|---|---|"]
    for tier in DOWNSTREAM_TIERS:
        for arm in ARMS:
            toks = cells[(tier, arm)]["in_tok"]
            mean = sum(toks) / max(len(toks), 1)
            lines.append(f"| {tier} | {arm} | {mean:.0f} |")

    out = DOCS / "pilot-results.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 测试通过 + 生成报告**

```bash
uv run pytest tests/test_metrics.py -q          # Expected: 3 passed
uv run python -m pilot.analyze --run-id pilot-full
```
Expected: `docs/pilot-results.md` 生成，含 5 张表。渲染检查一遍（表格对齐、无 nan 意外）。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "[pilot] Add analysis with bootstrap CIs and generate the report"
```

---

## Task 12: Preservation ablation（patch vs full-rewrite）

**Files:**
- Create: `pilot/src/pilot/ablation_rewrite.py`

目的：给 patch 机制（idea 的辨识度设计）拿到第一手证据——full-rewrite 会不会弄丢/改坏用户材料。

- [ ] **Step 1: 写 `ablation_rewrite.py`**

```python
"""Full-rewrite ablation on the 30 long-content instances:
the translator regenerates the ENTIRE input (request + content).
We then measure content corruption mechanically. The patch arm's content
preservation is 100% by construction; this quantifies what full rewriting
costs -- the motivation for patch-based translation."""
import difflib
import json

from pilot import llm
from pilot.arms import _memory_block
from pilot.config import DOCS, INSTANCES, MODELS, RESULTS

FULL_REWRITE_SYSTEM = """You are a user-input rewriter. You receive the user's full input (request plus attached material) and the user's stored preference memories.
Rewrite the ENTIRE input so that applicable memories are incorporated, preserving the attached material. Output only the rewritten input, no commentary."""


def main():
    insts = [json.loads(l) for l in (INSTANCES / "longdoc.jsonl").open()]
    rows = []
    for n, inst in enumerate(insts, 1):
        full_input = f"{inst['request']}\n\n{inst['content']}"
        out = llm.call(
            MODELS["translator"],
            f"Stored user memories:\n{_memory_block(inst['memory_store'])}\n\n"
            f"User input:\n{full_input}\n\nRewritten input:",
            system=FULL_REWRITE_SYSTEM, max_tokens=4096)
        rewritten = out["text"]
        content = inst["content"]
        exact = content in rewritten
        sim = difflib.SequenceMatcher(
            a=content, b=rewritten).find_longest_match(
            0, len(content), 0, len(rewritten)).size / max(len(content), 1)
        rows.append({"id": inst["id"], "content_exact_match": exact,
                     "longest_block_ratio": round(sim, 3),
                     "len_original": len(content),
                     "len_rewritten_total": len(rewritten),
                     "output_tokens": out["output_tokens"]})
        print(f"[{n}/{len(insts)}] {inst['id']} exact={exact} "
              f"block={sim:.2f}", flush=True)

    exact_rate = sum(r["content_exact_match"] for r in rows) / len(rows)
    mean_block = sum(r["longest_block_ratio"] for r in rows) / len(rows)
    mean_tok = sum(r["output_tokens"] for r in rows) / len(rows)
    report = [
        "", "## Ablation: full-rewrite vs patch (30 long-content instances)",
        "", f"- patch arm content preservation: 100% (by construction)",
        f"- full-rewrite content exact-match rate: {exact_rate:.0%}",
        f"- full-rewrite mean longest-preserved-block ratio: {mean_block:.1%}",
        f"- full-rewrite mean output tokens: {mean_tok:.0f} "
        f"(patch arm rewrites only the request)", ""]
    with (DOCS / "pilot-results.md").open("a") as f:
        f.write("\n".join(report))
    (RESULTS / "ablation.json").write_text(json.dumps(rows, indent=2))
    print("appended to docs/pilot-results.md")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑 + 检查**

```bash
uv run python -m pilot.ablation_rewrite
```
Expected: 30 行心跳；pilot-results.md 末尾多出 ablation 小节。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "[pilot] Add full-rewrite ablation quantifying content corruption"
```

---

## Task 13: go/no-go memo

**Files:**
- Create: `docs/go-no-go.md`

- [ ] **Step 1: 按此模板写 memo（判据回填数字，结论留给 siriux）**

```markdown
# Pilot go/no-go — <日期>

## 判据回填（预注册于 2026-07-21-pilot-plan.md §0）
- G1: adherence(A3) − max(A1,A2) @ weak = <x>pp, CI [<lo>, <hi>] → 满足/不满足
- G2: <逐项回填> → 满足/不满足
- G3: P(noop|neg) = <x>% → 满足/不满足
- 机械结论: GO / NO-GO

## 主要数字（出处: docs/pilot-results.md, run pilot-full）
<адherence 表、FAR 表、token 表的关键行摘录>

## 强下游结果（如实报告，不作判据）
<...>

## 意外发现 / error 分析
<translator 失败案例分类：scope 误判 / 过度补全 / parse 失败，各举 2 例原文>

## 若 GO：Phase 2 头三步
1. CUPID scope 主实验（诊断 §三-3）
2. related work 正面对比表：CIPHER / RECAP / BPO / AndroidIntent / Persona2Web
3. 部署卖点（黑盒下游）改写进 motivation
## 若 NO-GO：死因与残值
<哪个环节死的；负例集 / harness / 校准协议可复用于什么>
```

- [ ] **Step 2: Commit**

```bash
git add docs/go-no-go.md && git commit -m "[docs] Write pilot go/no-go memo"
```

---

## 7. 时间线（两周，D = 工作日）

| 天 | 内容 | 落盘检查点 |
|---|---|---|
| D1 | Task 0 + Task 1（**核验闸门**） | prefeval-notes.md |
| D2 | Task 2 + Task 3 | pilot.jsonl + stats |
| D3 | Task 4 + Task 5 | longdoc.jsonl |
| D4 | Task 6 + Task 7 | translator/judge smoke 输出 |
| D5 | Task 8 smoke(n=20) + Task 9（**校准闸门**，需 siriux ~30min 标注） | calibration.tsv + agreement |
| D6–7 | Task 10 全量（后台 + 心跳日志） | pilot-full.jsonl |
| D8 | Task 11 + Task 12 | pilot-results.md |
| D9–10 | Task 13 memo + 与 siriux 对判据 | go-no-go.md |
| D11–14 | buffer：允许**一次**修补迭代（只许改 translator prompt；重跑 translator + A3 臂即可，缓存使其它臂零成本；判据不放宽） | — |

每个落盘检查点 = 跨 session 可恢复点：任何 session 从 docs/ + runs/ 就能接上状态。

---

## 8. 预算（估算，按 claude-api skill 2026-06 缓存价：opus-4-8 $5/$25，haiku-4-5 $1/$5 每 MTok）

| 项 | 调用数 | 估 tokens | 估成本 |
|---|---|---|---|
| translator (haiku) | ~250 | 0.2M in / 0.04M out | <$1 |
| downstream opus | 1000 | 0.5M in / 0.3M out | ~$10 |
| downstream haiku | 1000 | 0.5M in / 0.3M out | ~$2 |
| judges (opus) | ~2150 | 1.7M in / 0.3M out | ~$16 |
| 负例筛查 + smoke + 校准 + ablation | ~1000 | — | ~$6 |
| **合计** | ~5400 | — | **~$35–45**（上限按 $60 留） |

judge 换 `claude-sonnet-5` 可省约一半（intro 价 $2/$10），代价是校准闸门更关键——默认不换。

---

## 9. Phase 2 概要（GO 之后才展开成 task，此处只记方向）

1. **CUPID scope 主实验**：translator 的 scope 判别用 CUPID 756 条评测（自带 PREFMATCHER-7B）；
2. **feedback→requirement 提取**：CUPID session 内反馈 + WildFeedback 信号识别思路，协议自搭；
3. **"重复即证据"（诊断认定最薄弱的一环）**：无现成 benchmark，需自构造多 session 重复要求数据——是否做、以多小的规模做，GO 之后单独决策；
4. **CRUD**：LongMemEval（knowledge updates / abstention）+ BEAM 相关类别 adapt 到 instruction 层；
4. **diff 式 patch 完整实现**（长 REQUEST 场景才需要）；
5. **论文重定位**：从"position + 系统"转为"对照研究 + scope-aware patching"；related work 正面处理 CIPHER、RECAP、BPO、AndroidIntent、Persona2Web；"黑盒下游、只控用户通道"从项目边界提升为核心 motivation（与 BPO 论证同构）。

---

## 10. 风险与对策（对应诊断第四节）

| 风险 | 对策（本 plan 落点） |
|---|---|
| 翻译式误用不可逆、下游无从纠错 | FAR 为一等指标（100 负例）+ G3 门槛 + error 分析进 memo |
| underspecification 是故意的 | translator prompt 规则 1（noop 默认）+ P(noop\|neg) 指标 |
| 与产品内建 memory 双重应用 | pilot 下游 system prompt 干净，不涉及；记入 Phase 2 部署讨论 |
| judge 不可靠污染全部结论 | Task 9 校准闸门（30 条人工，agreement ≥85%） |
| PrefEval 假设失效 | Task 1 Day-1 核验闸门，失败先改 plan |
| 结果难看时事后挑指标 | §0 判据预注册，全量 run 前定稿，之后不放宽 |
