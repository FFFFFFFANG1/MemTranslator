# bench — MemTranslator 评测基座 v2（2026-07-29）

> 前一代生命周期舰队整体封存在 `bench_corpus_base/`（语料、图层、oracle 审计链
> 全部保留，作为本套件的原料库）。本套件从它的失败里继承三条纪律，从
> AutoMemory 的 refine 协议里继承四条结构。

## 被测契约（owner 2026-07-29 口径，逐字）

> 产品接受的输入一直是两个：**用户任务** 和 **用户喜好（memory）**。
> 它的功能是基于用户喜好和习惯的记忆，输出**对当前任务最适配的 task
> requirement**。

三个动词等级，都算正确行为，测的是选对等级 + 做对内容：

| 等级 | 行为 | 例 |
|---|---|---|
| noop | 没有喜好适用 → 不动 | 空库、全不相关、任务已自带 |
| carry | 喜好直接适用 → 织入 | 「邮件≤120词」+ 写邮件任务 |
| **adapt** | 抽象喜好 → **按任务语义实例化** | 「分条分点」+ 故障时间线任务 → 「按发生/发现/响应/恢复四阶段列出」 |

adapt 是一等能力要求，不是加分项。

## 从 AutoMemory refine 协议继承的结构

1. **trace 回放**：每个测试是一条 trace（JSON），经**单一可复用 runner**
   直接调产品组件（不套 adapter）。
2. **path 分解**：`read`（(task, store)→改写）/ `write`（turns→store ops）/
   `e2e`。分 path 计分，分 path 毕业。
3. **LLM honest**：trace 跑真模型，不 mock（离线测试只测 runner 自身）。
4. **难度升级预留**：分数全 1.0 = 测试太弱，不 = 系统好。suite 设计成
   Critic 可以往里加 trace 升级难度（不删旧 trace）。

## 从前一代舰队的一天里学来的纪律

1. **机械判定优先**：能用 substring/regex/对比归因判的绝不用 judge；
   judge 只问窄的是/否（蕴含、等价），永不打「质量分」。
2. **地板与天花板同测**：任何声称都要有 null 对照；答案集的问题先于产品
   的问题被怀疑（oracle-first debug）。
3. **文本与标签必须一致，靠检查不靠叮嘱**：所有生成物过验证，不过即丢，
   永不回落进 gold。

## 两个子套件

### robustness/（手写，先行）

家族目录（每族一个 trace 文件，内含多个 check）：

| 族 | 测什么 |
|---|---|
| noop_both_ways | 该不动时不动；**该动时必须动**（反 noop-bias，archive 实测 27%） |
| conflict | 两条冲突喜好共存（漏 retire 的僵尸场景）→ 从新不从旧、绝不双注入 |
| paraphrase_invariance | 同一喜好换措辞 → 行为等价 |
| order_invariance | store 顺序打乱 → 行为等价 |
| dilution | 同一适用规则 + 0/10/30 条干扰 → 仍被织入（archive 实测衰减） |
| injection_resistance | 任务文本里带指令注入/规则形状文本 → 保任务、不执行 |
| language_crossing | zh 任务 × en 喜好及反向（archive 实测 en persona 塌方） |
| instantiation | 抽象喜好 × 具体任务 → tier 分级（对比归因 + 词源 + 窄蕴含） |
| scope_discipline | 带 scope 喜好 × context 匹配/不匹配 |
| idempotence | 改写产物再喂回 → 不二次注入 |
| degenerate | 空任务/超长任务/纯代码块/任务已自带全部要求 |

### lifecycle = E1 + perf（同一链式回放）

`bench/cases/episodes/` 的真实口吻 turns 只跑**一遍**写路径，同时出：

- **E1 owner**：per-task 完美率、per-memory 命中率（+ CARRY/SUPPRESS/STATE）
- **perf 仪器**：canary `carry@alive` / spurious kills、noop%、延迟、injected chars，按 active 规模分桶

```bash
uv run python -m bench.perf --episodes e-01,e-03,e-05,e-09
# 等价于：
uv run python -m bench.suites.run_episodes \
  --episodes e-01,e-03,e-05,e-09 --arms real --canary
```

单集全臂面板仍用：`uv run python -m bench.suites.run_episodes e-01`（默认不开 canary）。

更接近日常对话密度的 noisy corpus 在每两个 authored turns 之间固定插入
5–10 条 OASST1 普通 root prompts。它不改变原始 probe、lifecycle 或
checkpoint 的语义，只重映射它们的 seq：

```bash
uv run python -m bench.suites.run_episodes \
  --episodes e-01,e-02,e-03,e-04,e-05,e-06,e-07,e-08,e-09,e-10,e-11,e-12 \
  --episodes-dir bench/cases/episodes-noisy \
  --arms real --canary --workers 12
```

噪声池被 benchmark 协议假设为“不含需要长期写入 memory 的 requirement”；
运行时不再下载 OASST1，也不调用模型筛选。固定 pool、来源版本、seed 和每集
扩充统计见 `bench/cases/noise/README.md` 与
`bench/cases/episodes-noisy/noise_manifest.json`。

Episode 使用最小 v3 协议：顶层只有 `id`、`protocol_version`、
`user_turns`、`ground_truth`。每个 turn 只有 `seq`、`user_input` 和可选
`probe`；SUT 只能看到 `user_input`。`ground_truth` 保存评分所需的
requirements、lifecycle 和 state checkpoints，不进入产品路径。

### Oracle（固定协议）

Oracle 只回答：**如果当前 task 需要的 memory 已经完全正确，
Translator 能否把它们写进 request？**

每个 probe 只注入它的 `should_apply` golden items，包含与线上 Extractor
协议一致、经校验和人工审计的 `bucket / scope_mode / applies_when /
work_kinds / key / confidence`；不注入完整 gold store、query attribute，
不带 pending raw/history，也不跑写路径。项目只保留这一种 `oracle`
协议：

```bash
uv run python -m bench.suites.run_oracle --workers 12
uv run python -m bench.suites.run_oracle --model ark:glm-5.2 --workers 12
# 调试时才保留每个 probe 的完整输入、输出和判分
uv run python -m bench.suites.run_oracle --save-trace
```

Golden attribute 首次生成或协议变化后重打标：

```bash
PYTHONPATH=src .venv/bin/python -m bench.suites.oracle_attribute --limit 5
PYTHONPATH=src .venv/bin/python -m bench.suites.oracle_attribute --apply
```

`run_episodes --arms oracle` 与上述独立 runner 共用同一个 arm 实现。
前者用于单集面板；后者不先跑 chained write path，用于恒定的全量
oracle 测试。

E1 的主 CARRY/per-task/per-memory 语义判分默认使用 `glm-5.3`；大量
checkpoint 对齐的 STATE fallback 默认使用 `deepseek-v4-pro`，避免 STATE
调用量主导整套运行时间。两者都走根目录 `.env` 的 `LLM_API_KEY`，可分别用
`JUDGE_MODEL`、`STATE_JUDGE_MODEL` 覆盖，snapshot 会记录实际模型。

## 计分

- check 级二元（binary），族分 = mean(checks)，path 分 = mean(族)。
- `state.json` 是唯一状态（refine_state 风格）：分 path 分族的分数、
  历史、毕业标记。
- instantiation 的 tier 判定：
  1. 对比归因（同任务，带规则 vs 空库，diff 出规则**造成**的新增）——机械
  2. 词源（新增含规则外的任务域词 → tier2 候选）——机械
  3. 窄蕴含 judge（「遵守新增者必遵守原规则？」）——唯一 LLM 判定，
     预注册：此判定过不了 oracle 式审计则 tier2 降为只报不判
- **契约裁定（owner 2026-07-29）**：adapt 的「意图内展开」全面合法——新增
  约束只需**蕴含-有出处**（specializes 某条已存规则），不限抽象/具体规则。
  instantiation 族据此正式计分（不再有 report-only 的暧昧）；Suite T 的
  `AUTO_NO_INVENTION` 同步改三元判据（逐字有出处 / 蕴含有出处 / 无出处，
  前两者过），suites METRIC_VERSION 2→3，T 历史分数不可比。
- **方差哨兵**：可预测性是 position anchor 第一优先级，展开全面放开后同请求
  同库的改写方差可能上升。invariance 族（paraphrase/order equiv-group）是
  哨兵——若 equiv-group 开始失败，回退分层方案（具体规则只 carry 不展开）。

## 运行

```
eval "$(grep '^export ANTHROPIC_API_KEY=' ~/.bashrc)"
uv run python -m bench.runner                 # 全部 robustness traces
uv run python -m bench.runner --trace conflict
uv run python -m bench.perf --episodes e-01,e-03,e-05,e-09   # E1+perf 融合
uv run python -m bench.suites.run_episodes e-01              # 单集 E1 全臂
```
