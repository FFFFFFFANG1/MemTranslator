# MemTranslator E1 Noisy Performance Report

**原文** | [简体中文](2026-08-26-memtranslator-e1-performance-report.zh-CN.md)

**报告日期：** 2026-08-26  
**评测对象：** MemTranslator native end-to-end pipeline  
**对照对象：** Codex file memory（`AGENTS.md + MEMORY.md`，GPT-5.5 medium）  
**数据集：** E1 protocol v3，12 个 `episodes-noisy` episodes

## Executive summary

MemTranslator 在 E1 noisy 上的当前表现是：**适用记忆能较稳定地带入当前任务，失效或越界记忆多数能被压住，但写入后的内部状态仍有明显误差。** 按 E1 的正式口径，CARRY、SUPPRESS、STATE 三个 band 分开报告，不存在官方加权总分。

| Metric | MemTranslator | 95% CI / count | 结论 |
| --- | ---: | ---: | --- |
| CARRY macro | **0.713** | `[0.637, 0.794]` | 适用记忆的 episode 宏平均命中率 |
| CARRY micro | **69.2%** | `74/107` | 107 个应带入的 memory 中命中 74 个 |
| SUPPRESS macro | **0.894** | `[0.788, 0.970]` | 不适用记忆的 episode 宏平均抑制率 |
| SUPPRESS micro | **85.7%** | `30/35` | 35 个机械负例中压住 30 个，泄漏 5 个 |
| STATE macro | **0.707** | `[0.671, 0.738]` | store 对 gold lifecycle 状态的对齐程度 |
| STATE micro | **70.6%** | `1861/2637` | 所有 checkpoint 状态判定的 pooled 命中率 |
| Task-perfect | **66.0%** | `68/103` | 103 个计分任务中，68 个同时满足全部正负要求 |

与 Codex file memory 相比，MemTranslator 的 observed CARRY 更高，Codex 的 observed SUPPRESS 更高：

- MemTranslator 多命中 **5/107** 个适用 memory，CARRY macro 高 **0.041**。
- Codex 多压住 **4/35** 个负例，SUPPRESS macro 高 **0.093**。
- Task-perfect 为 **68/103 vs 67/103**，只差 1 个任务，实际可视为持平。
- paired episode bootstrap 的 CARRY 与 SUPPRESS 差值区间都跨过 0；这轮结果支持“双方强项不同”，**不支持任何一方总体显著优于另一方**。

## 1. E1 测什么

E1 是一条完整的 memory lifecycle 测试，不只是 Translator 模型的单点测试。它覆盖用户历史进入系统后的提取、写入、失效、检索和最终 request rewrite。因此，本报告中的 “MemTranslator E1 score” 应理解为 **native 完整系统效果**。

三个评分 band 的含义如下：

- **CARRY**：当前任务应该应用的 `should_apply` memory，是否被明确织入最终 request。规则原文或 authored paraphrase 的精确出现走机械 fast path，其余由窄 yes/no judge 判定。单纯“输出碰巧兼容该偏好”但 request 中没有对应要求，不算命中。
- **SUPPRESS**：`must_not_apply` memory 的 distinctive anchor 是否没有出现在最终 request。它覆盖已失效、scope 不匹配等不应生效的规则，完全机械评分，不使用 LLM judge。
- **STATE**：内部 store 是否正确表达 gold lifecycle。活跃 memory 应存在有效对齐项，失效 memory 不应仍有 active 对齐项；先做 substring alignment，miss 再交给窄 judge。

另外，**Task-perfect** 要求一个任务上的所有 CARRY 和 SUPPRESS target 同时正确；它比单条 memory 命中更严格。

## 2. 测试规模与配置

noisy corpus 在每两个 authored turns 之间固定插入 5–10 条 OASST1 普通 root prompts，保留原始 probe、lifecycle 和 checkpoint 语义，只重映射 sequence number。它用于模拟长期历史中“真正需要记忆的偏好被大量普通对话稀释”的情况。

| 项目 | 数值 |
| --- | ---: |
| Episodes | 12 |
| Authored turns | 744 |
| Noise turns | 5,481 |
| Expanded turns | 6,225 |
| Probe/checkpoints | 209 |
| Scored tasks | 103 |
| Gold requirements | 467 |
| CARRY targets | 107 |
| SUPPRESS targets | 35 |

本轮 MemTranslator 使用 native extraction、Store、BGE-M3 retrieval 和 DeepSeek V4 Flash Translator；scoped recall cap 为 16。结果快照为 metric version 12、protocol version 3；CARRY judge 为 GLM-5.3，STATE miss judge 为 DeepSeek V4 Pro。12 个 episode 均完整结束，CARRY judge parse flag 为 0。

## 3. MemTranslator 逐集结果

| Episode | CARRY | SUPPRESS | STATE | Task-perfect |
| --- | ---: | ---: | ---: | ---: |
| e-01 | 0.500 | 0.667 | 0.705 | 3/7 |
| e-02 | 0.800 | 1.000 | 0.753 | 7/8 |
| e-03 | 1.000 | — | 0.563 | 7/7 |
| e-04 | 0.526 | 0.667 | 0.700 | 2/12 |
| e-05 | 0.778 | 1.000 | 0.796 | 7/9 |
| e-06 | 0.667 | 0.500 | 0.690 | 5/9 |
| e-07 | 0.800 | 1.000 | 0.743 | 3/4 |
| e-08 | 0.667 | 1.000 | 0.692 | 4/5 |
| e-09 | 0.545 | 1.000 | 0.770 | 6/11 |
| e-10 | 0.750 | 1.000 | 0.658 | 10/12 |
| e-11 | 0.727 | 1.000 | 0.755 | 7/10 |
| e-12 | 0.800 | 1.000 | 0.656 | 7/9 |

`e-03` 没有 SUPPRESS target，因此不进入 SUPPRESS macro 的分母。

### 3.1 适用记忆：有效，但仍是主要损失来源

CARRY macro 为 0.713，micro 为 74/107。这说明 MemTranslator 已能在大量噪声与 29–42 条 peak active memory 下保住约七成适用偏好，但仍漏掉 31 个应带入项。

逐集表现并不均匀：`e-03` 达到 1.000，`e-02`、`e-07`、`e-12` 达到 0.800；`e-01`、`e-04`、`e-09` 只有 0.500–0.545。当前 read path 不是全面失效，而是对 episode/persona 和 memory composition 较敏感。

### 3.2 失效记忆：总体较强，错误集中在少数 episode

SUPPRESS macro 为 0.894，micro 为 30/35。12 个 episode 中，8 个有负例的 episode 达到 1.000；5 次泄漏全部集中在：

- `e-01`：4/6，泄漏 2 个；
- `e-04`：4/6，泄漏 2 个；
- `e-06`：1/2，泄漏 1 个。

因此 SUPPRESS 的整体形状不是“普遍小幅不稳”，而是“大部分场景全对，少数 lifecycle 较复杂的 episode 明显掉分”。

### 3.3 Store state：约七成正确，仍是明确改进空间

STATE macro 为 0.707，micro 为 1861/2637。最低为 `e-03` 的 0.563，最高为 `e-05` 的 0.796。值得注意的是，`e-03` 同时取得 CARRY 1.000：这说明 checkpoint 上的 store 全局状态质量与当前 probe 的可用输出相关但不等价，不能用 CARRY 替代 STATE，也不能仅凭 STATE 推断每个任务一定失败。

### 3.4 端到端任务成功率

68/103 个任务做到所有正负要求同时正确，Task-perfect 为 66.0%。这个数字与 CARRY micro 接近但更严格：只要一个任务中漏掉任意适用 memory，或泄漏任意不适用 memory，整题就不 perfect。

## 4. 与 Codex file memory 的对比

### 4.1 对照协议

Codex baseline 在相同的 12 个 E1 noisy episodes 上维护 `AGENTS.md + MEMORY.md`：每个 authored probe 前增量更新文件，在有 CARRY/SUPPRESS target 的 probe 上，用冻结文件和当前 request 做一次 fresh GPT-5.5 medium rewrite。两边复用相同 E1 CARRY judge 与机械 SUPPRESS scorer，ground truth 不进入被测系统调用。

这使 corpus 和 scorer 可比，但它仍然是**系统级比较**，不是单组件 A/B：两边的 memory representation、writer、retrieval、readout model 和维护协议都不同。

### 4.2 汇总对比

差值方向统一写作 **MemTranslator − Codex**。

| Metric | MemTranslator native | Codex file memory | Delta |
| --- | ---: | ---: | ---: |
| CARRY macro | **0.713** `[0.637, 0.794]` | 0.672 `[0.585, 0.767]` | **+0.041** |
| CARRY micro | **74/107 (69.2%)** | 69/107 (64.5%) | **+5/107** |
| SUPPRESS macro | 0.894 `[0.788, 0.970]` | **0.987** `[0.961, 1.000]` | **−0.093** |
| SUPPRESS micro | 30/35 (85.7%) | **34/35 (97.1%)** | **−4/35** |
| Task-perfect | **68/103 (66.0%)** | 67/103 (65.0%) | **+1/103** |
| STATE | **0.707** `[0.671, 0.738]` | 不可比 | — |

### 4.3 Paired episode 分析

当前仓库保留了 MemTranslator 的逐 episode 机器结果，用户提供的 Codex 报告也给出了逐 episode 表，因此可以按 episode 配对计算差值。使用 2,000 次、seed 17 的 paired episode-cluster bootstrap：

| Paired metric | Mean delta | 95% bootstrap CI | Episode wins / ties / losses |
| --- | ---: | ---: | ---: |
| CARRY | **+0.041** | `[-0.083, +0.156]` | 6 / 2 / 4 |
| SUPPRESS | **−0.093** | `[-0.212, +0.009]` | 1 / 7 / 3 |

两个区间都跨过 0。样本支持的稳妥表述是：

- **MemTranslator 的 observed strength 是 CARRY**：多带入 5 个适用 memory，在 12 集中赢 6 集、输 4 集、平 2 集。
- **Codex 的 observed strength 是 SUPPRESS**：只泄漏 1/35，MemTranslator 泄漏 5/35；但多数 episode 没有差异，差距由 3 个 episode 驱动。
- **Task-perfect 基本持平**：66.0% vs 65.0%。当前 12-cluster 样本不足以建立总体统计优势。

### 4.4 逐集对比

| Episode | MT CARRY | Codex CARRY | MT SUPPRESS | Codex SUPPRESS | MT perfect | Codex perfect |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| e-01 | 0.500 | **0.833** | 0.667 | **1.000** | 3/7 | **6/7** |
| e-02 | **0.800** | 0.600 | 1.000 | 1.000 | **7/8** | 6/8 |
| e-03 | **1.000** | 0.750 | — | — | **7/7** | 5/7 |
| e-04 | 0.526 | **0.684** | 0.667 | **1.000** | 2/12 | **7/12** |
| e-05 | **0.778** | 0.667 | 1.000 | 1.000 | **7/9** | 6/9 |
| e-06 | **0.667** | 0.500 | 0.500 | **1.000** | **5/9** | 3/9 |
| e-07 | 0.800 | **1.000** | 1.000 | 1.000 | 3/4 | **4/4** |
| e-08 | 0.667 | 0.667 | 1.000 | 1.000 | 4/5 | 4/5 |
| e-09 | 0.545 | 0.545 | 1.000 | 1.000 | 6/11 | 6/11 |
| e-10 | 0.750 | **0.875** | **1.000** | 0.857 | 10/12 | 10/12 |
| e-11 | **0.727** | 0.545 | 1.000 | 1.000 | 7/10 | 7/10 |
| e-12 | **0.800** | 0.400 | 1.000 | 1.000 | **7/9** | 3/9 |

对比也说明“总体均值”掩盖了较强的 episode interaction：MemTranslator 在 `e-03`、`e-12` 的 CARRY 明显领先，但在 `e-01`、`e-04` 明显落后；下一轮优化更应该定位这些 episode 的 write/retrieval/readout loss，而不是只追一个 aggregate 分数。

## 5. 运行侧观测

MemTranslator 这轮的补充运行指标如下：

| 指标 | 数值 |
| --- | ---: |
| Peak active memory / episode | 29–42 |
| Episode-macro mean active-store text / probe | 2,345 chars |
| Episode-macro mean Translator latency / probe | 11,225 ms |
| Episode-macro mean noop rate | 7.1% |
| CARRY judge parse flags | 0 |

Codex 报告给出的运行元数据为 209 次 memory-maintenance calls、103 次 scored readouts、2,082,725 reported tokens、15,179,459 ms summed call latency，以及 scored readout 时平均 4,470.6 个 frozen memory-file characters。

这些数字**不能直接用于速度或成本排名**：MemTranslator 快照没有记录完整 writer/extractor token 与调用成本，且其 11.2 秒是 Translator probe latency；Codex 的 15.18M ms 则合并了 maintenance 与 readout calls。两边的 character 指标也分别是 active-store text 与完整 frozen files，只能作为各自运行规模说明。

## 6. 结论与下一步

当前 E1 noisy 结果给 MemTranslator 的定位很清楚：

1. **产品能力已经成立，但不是接近饱和。** 在 6,225-turn noisy histories 上，69.2% 的适用 memory 被正确带入，66.0% 的任务全部正确。
2. **相对 Codex，MemTranslator 更偏“记得并用上”。** CARRY 多命中 5/107，尤其在 `e-03`、`e-12` 有明显优势。
3. **Codex 更偏“宁缺毋滥”。** 它在 SUPPRESS 上只泄漏 1/35；MemTranslator 的 5 次泄漏集中在 `e-01`、`e-04`、`e-06`，适合做定向 lifecycle error analysis。
4. **内部状态仍是核心改进面。** STATE 约 0.707，说明 store 中缺失 active memory 或残留 dead memory 的问题尚未解决。读路径优化不能替代 write/lifecycle 修复。
5. **当前总体胜负未定。** paired CI 均跨 0，Task-perfect 只差 1/103。下一轮应增加重复运行或 episode clusters，并固定一个 common readout 做 writer/retrieval attribution，避免把模型能力差异误归因于 memory architecture。

优先建议按以下顺序继续：

1. 对 `e-01`、`e-04`、`e-06` 的 5 个 SUPPRESS leaks 做逐项 trace attribution，分成 write 未 retire、retrieval 越界、Translator 忽略状态三类。
2. 对 `e-01`、`e-04`、`e-09` 的 CARRY misses 记录 gold 是否进入 store、是否进入 recall candidate、是否进入 prompt、是否被 Translator 采用，形成四段漏斗。
3. 在同一 metric version 上做至少 3 次完整复跑，报告 paired run distribution，而不是用单轮模型波动裁决小于 5 个点的差异。
4. 补齐 end-to-end token、调用数和 wall-clock 账本后，再与 Codex 做成本—效果比较。

## 7. 限制与数据来源

- E1 只有 12 个 episode clusters，置信区间仍较宽；单轮结果不适合裁决小差距。
- CARRY 是 judge band；本轮 parse flag 为 0，但 judge 仍可能存在系统性偏差。
- 本比较是 native system vs native system，不隔离 memory writer、retriever 或 readout model 的单独贡献。
- Codex 没有与 MemTranslator Store 等价的结构化状态，因此不报告或推断 Codex STATE。
- MemTranslator 的 12 份 metric-v12 机器快照已在撰写本报告时的工作区核验；这些运行产物生成在被 Git 忽略的 `bench/results/`，不作为源码长期保存。Codex 的逐集与汇总数字来自用户提供的 `2026-08-25-codex-vs-memtranslator-e1.md`。其文中提到的 formal Codex snapshot 当时不在本 workspace，故本报告未独立重放 Codex 原始 checkpoint。
- 旧版 E1 score log 使用不同子集、metric version 和配置，不应与本轮 noisy fleet 直接串成趋势线。

### Reproduction and source files

按 [`bench/README.md`](../bench/README.md) 重跑 E1 noisy fleet 后，聚合本地快照：

```bash
PYTHONPATH=src:. .venv/bin/python -m bench.suites.report_e1
```

主要来源：

- E1 评分实现：[`bench/suites/run_episodes.py`](../bench/suites/run_episodes.py)
- E1 fleet 聚合：[`bench/suites/report_e1.py`](../bench/suites/report_e1.py)
- Noisy corpus 协议：[`bench/README.md`](../bench/README.md)
- Noisy corpus manifest：[`bench/cases/episodes-noisy/noise_manifest.json`](../bench/cases/episodes-noisy/noise_manifest.json)
- MemTranslator 机器结果：运行时生成在被 Git 忽略的 `bench/results/`；本报告表格保留已核验的汇总结果
- Codex 对照来源：用户提供的 `2026-08-25-codex-vs-memtranslator-e1.md`
