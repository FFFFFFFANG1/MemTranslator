# MemTranslator Benchmark

`bench/` 只保留当前产品仍可运行的评测代码和固定语料。历史运行产物与已退役的
语料生成工作区不再放在这里；相关决策由 Git 历史和 `docs/` 下的定期报告保留，
避免旧入口被误认为当前协议。

## 当前口径

- **指标版本：** `12`（`bench.suites.config.METRIC_VERSION`）。不同指标版本的
  分数不可直接比较。
- **主要生命周期评测：** E1 protocol v3，分别报告 **CARRY**、
  **SUPPRESS**、**STATE**。当前没有加权总分，也没有自动发布门槛。
- **最近一次公开结果：**
  [2026-08-26 E1 含噪声场景报告](../docs/2026-08-26-memtranslator-e1-performance-report.zh-CN.md)
  覆盖 12 个交互序列、6,225 轮历史和 103 个计分任务；CARRY 为 0.713、
  SUPPRESS 为 0.894、STATE 为 0.707，Task-perfect 为 68/103。这些是带日期的
  实验结果，不应当作永久有效的产品结论。
- **改写稳健性契约：** 检查 noop、冲突规则、不变性、干扰稀释、提示注入、
  跨语言适用、任务内实例化、作用域和幂等性。

本基准评估记忆维护和请求改写，不评估下游 Agent 最终回答的质量。

## 目录结构

| 路径 | 用途 |
| --- | --- |
| `runner.py`、`traces/` | 8 个改写稳健性 trace 家族，直接调用产品组件。 |
| `cases/translate/` | 60 个 Translator 聚焦用例，供 Suite T 诊断。 |
| `cases/extraction/` | 55 个写路径用例，供 Suite L 诊断。 |
| `cases/personas/` | 8 个旧版链式 persona，供 Suite E 诊断。 |
| `cases/episodes/` | 12 个 E1 v3 交互序列，共 744 个 authored turns、209 个 probe/checkpoint。 |
| `cases/episodes-noisy/` | 在相同序列中确定性插入 5,481 条 OASST1 噪声。 |
| `cases/noise/` | 固定噪声池、来源、许可证和再生成说明。 |
| `graph/` | E1 回放和语料校验使用的约束生命周期模型。 |
| `suites/` | runner、scorer、provider、report、oracle 工具和消融分析。 |
| `results/` | 运行生成的快照；整个目录由 Git 忽略。 |

`bench/state.json`、`bench/perf_results.json` 和分片运行状态也都是本地产物，
不是源码。分片状态默认位于 `${TMPDIR}/memtranslator-bench`，可通过
`BENCH_RUN_DIR` 修改位置。

## 准备环境

安装项目和开发依赖：

```bash
./scripts/dev-sync.sh
```

在线评测读取仓库根目录的 `.env`，至少需要配置 `LLM_API_KEY` 和
`LLM_BASE_URL`。当前审计过的默认值如下：

| 角色 | 默认模型 | 覆盖变量 |
| --- | --- | --- |
| CARRY / 窄语义评判器 | `glm-5.3` | `JUDGE_MODEL` |
| STATE fallback 评判器 | `deepseek-v4-pro` | `STATE_JUDGE_MODEL` |
| 产品 Translator / writer | 产品配置 | `MT_TRANSLATOR`、`MT_WRITER` |

快照会记录实际使用的评判器和指标版本。比较两次运行之前，还应核对快照中的
语料哈希、协议版本、产品模型和检索预算。

## 快速离线校验

下列测试使用 fake 或机械检查，不会调用外部模型：

```bash
uv run --no-sync python -m pytest \
  tests/test_bench_*.py \
  tests/test_e1_retrieval_ablation.py \
  tests/test_episode_*.py \
  tests/test_graph.py \
  tests/test_oracle_attribute.py \
  tests/test_run_episodes_offline.py
```

修改语料、评分器、provider 或结果结构后，应先运行这组测试。

## 在线评测

以下命令会调用已配置的模型，可能运行较久并产生费用。

### 改写稳健性

```bash
uv run --no-sync python -m bench.runner --workers 4
uv run --no-sync python -m bench.runner --trace conflict --workers 4
```

runner 会生成本地 `R-*.json` 快照并更新被忽略的 `bench/state.json`。评分时
先执行机械检查，再调用窄语义评判器。

### E1 生命周期

用完整诊断 arm 面板运行一个 authored episode：

```bash
uv run --no-sync python -m bench.suites.run_episodes e-01
```

用原生 pipeline 运行当前含噪声语料：

```bash
uv run --no-sync python -m bench.suites.run_episodes \
  --episodes e-01,e-02,e-03,e-04,e-05,e-06,e-07,e-08,e-09,e-10,e-11,e-12 \
  --episodes-dir bench/cases/episodes-noisy \
  --arms real \
  --canary \
  --workers 12
```

聚合每个 episode 最新的完整快照：

```bash
uv run --no-sync python -m bench.suites.report_e1
```

E1 将每段用户历史通过原生写路径回放一次，并在 authored probe 上评估：

- **CARRY：** 当前适用的记忆是否明确进入改写后的请求；
- **SUPPRESS：** 已失效或越界的记忆是否没有泄漏进请求；
- **STATE：** 内部 store 是否与预期生命周期状态一致；
- **Task-perfect：** 当前任务的全部正例和负例是否同时正确。

`--canary` 和 `--sizes` 在同一条链上增加安全性与性能仪器，不产生另一套
生命周期总分。只在诊断时使用 `--save-trace`；完整 trace 体积更大，而且可能
包含模型输入和输出文本。

### Translator Oracle

Oracle 用于隔离 read path：每个 probe 只获得其经过审计的 gold
`should_apply` 记忆，因此 extraction、maintenance 和 retrieval 不会成为
本轮 miss 的原因。

```bash
uv run --no-sync python -m bench.suites.run_oracle --workers 12
uv run --no-sync python -m bench.suites.run_oracle \
  --model ark:glm-5.2 \
  --workers 12
```

只有 schema 或协议发生变化时，才重新生成 oracle attributes：

```bash
uv run --no-sync python -m bench.suites.oracle_attribute --limit 5
uv run --no-sync python -m bench.suites.oracle_attribute --apply
```

提交生成的 attribute 改动前，应先人工检查 diff。

### T / L / E 聚焦诊断

这些较小的 suite 仍适合定位回归，但旧版加权 acceptance score 已退役：

```bash
uv run --no-sync python -m bench.suites.run_translate --workers 4
uv run --no-sync python -m bench.suites.run_extraction --provider v1 --workers 4
uv run --no-sync python -m bench.suites.run_e2e --provider v1 --workers 4
uv run --no-sync python -m bench.suites.report
```

`null` 是地板 provider，`reference` 是简单的 harness 基线；二者都不代表产品
写路径。评估原生 pipeline 时使用 `v1`。

Suite T 使用产品唯一的 `plan → patch → audit` 流式协议。结果同时记录
`ready_latency_ms` 和完整 `latency_ms`，分别表示
文本框可安全替换的时间与后台 audit 结束的时间。Suite L 只测
extraction，不用于判断 Translator 协议。

## 语料与评分规则

1. Ground truth 不得进入被测系统。E1 只向系统暴露 `user_input`；requirements、
   lifecycle transitions 和 checkpoints 留在 `ground_truth` 中用于评分。
2. 优先使用机械评分。只有精确匹配不足时，才让 LLM 评判器回答范围明确的蕴含
   或等价问题。
3. 含噪声序列保留 authored probe 和 lifecycle 语义。OASST1 子集、来源版本、
   过滤规则、SHA-256 与 seed 记录在 `cases/noise/README.md` 和
   `cases/episodes-noisy/noise_manifest.json`。
4. Scorer、protocol 或指标含义变化时必须提升 metric version。旧快照只能标记为
   历史结果，不能直接并入趋势线。
5. 生成的结果不进入 Git。对外发布时应写带日期的报告，并说明语料、配置、
   不确定性和证据边界。

## 修改基准时

- 可以增加难度，不要因为产品未通过就删除仍然有效的旧用例。
- 先修正错误的 gold data，再考虑调整产品行为。
- 通过 validator 和测试保证用例文本与标签一致。
- 导入外部语料时记录来源和许可证。
- 先跑离线校验和覆盖改动的最小在线切片，再启动完整 noisy fleet。
