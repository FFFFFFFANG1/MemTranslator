# Baseline 对比测试 plan（v0，待批准后执行）

> 2026-07-21。论文从 memory 角度写，baseline 选真实 memory 系统（Mem0、Zep 这类）而非只有自实现注入变体。本文件只定方案，不含执行；批准后并入 pilot harness 执行。

## 0. 对比的问题与战场选择

对比的问题：**同样的用户交互历史，谁的 memory 管线能让下游把当前任务做对。**

战场选择的关键取舍：LoCoMo / LongMemEval 全集是 Mem0/Zep 的主场（事实记忆 QA），而我们的系统**故意不存事实**（design §0 立场 2）——直接上全集必输且跑题。所以：

- **主战场 = preference following**（PrefEval 子集，pilot plan 已定）：把 Mem0/Zep 当作完整 memory 管线接进来，与我们同任务对比。这里"从 memory 角度写"体现为 baseline 是真实系统全管线，不是我们自己实现的削弱版。
- **副战场（可选）= LongMemEval 的 preference 类子集**（SS-Pref 等类目，约 50–100 题）：在 memory 社区的标准 benchmark 上有直接可比数字（Zep、EverMemOS、Mandol 都报 LongMemEval）。是否跑取决于先验闸门（§5）。
- 明确不跑：LoCoMo 全集、LongMemEval 非 preference 类目。论文里说清楚原因（scope：intent 层不是知识层），这比在别人主场输掉更诚实也更省钱。

## 1. 测试臂（6 臂 = 2 系统 baseline + 4 机制臂）

| # | 臂 | 形态 | 说明 |
|---|---|---|---|
| A1 | no-memory | pilot 已有 | 下界 |
| A2 | oracle system-prompt | pilot 已有 | 上界（gold preference 直给） |
| A3 | top-k 注入 | pilot 已有 | 机制 baseline：同我们的 store，检索后注入下游 prompt |
| A4 | **translator（我们）** | pilot 已有 | write path + translate |
| B1 | **Mem0 OSS** | `pip install mem0ai`，自托管 | 两阶段 extraction+update + 向量检索的代表；诊断文稿的主要对比对象 |
| B2 | **Zep/Graphiti OSS** | `graphiti-core` + 本地 Neo4j（docker） | 时序知识图谱路线的代表 |

不加第三个系统（LangMem/Letta/MemOS）：两个系统 baseline 已支撑 "compare against production memory systems"，边际收益低于工程成本；论文 rebuttal 期如被要求再补。

版本锁定并记录（pyproject 里 pin 精确版本），论文注明 commit/version——Mem0 OSS 行为随版本漂移（诊断引述过其 2026 算法回退）。

## 2. 接入协议（公平性规则）

写入侧：PrefEval 的偏好陈述对话按 turn 喂各系统的原生写入接口（Mem0 `add(messages, user_id)`；Graphiti `add_episode`；我们 `run_write_path`）。**不为任何 baseline 做 preference 定向调优**（用其默认 prompt/配置）；这既是公平性也是论文论点——通用事实记忆系统不为 requirement 设计。limitation 里诚实写明。

读出侧：query 时各系统原生检索（Mem0 `search(query, user_id, k=8)`；Graphiti hybrid search，k=8），结果按各自官方推荐格式注入下游 prompt；我们走 `run_translate`。k 统一为 8（与 design §3.3 一致）。

统一变量：
- 下游模型与 pilot 相同（一强一弱两档）；judge、instance 集、评分协议全部复用 pilot 基建（instances/judge/analyze）。
- baseline 内部 LLM 统一为 flash 档（优先配成 haiku；若某系统对 Anthropic 支持不佳则 gpt-4o-mini，论文注明）——B0 冒烟时定案。
- embedding：各系统默认（Mem0 默认 OpenAI text-embedding-3-small；Graphiti 同类）。

记账（每臂三段分开记，成本表是论文卖点）：write-time 生成式 call 数 + token；query-time 注入 token（进下游 prompt 的 memory 部分）；下游输入总 token。我们的 ⌈user_turns/5⌉+1 vs Mem0 的 per-fact update 在这里量化。

## 3. 指标（同 pilot + 两个新增）

复用 pilot 的：preference adherence（judge）、FAR（负例误应用率）、内容保真（长输入实例）、token 成本。

新增两个中间指标，把"检索质量"和"使用质量"拆开（这是 translator-vs-injection 论证的核心分解）：
1. **memory 召回命中率**：query 时各系统检索出的 memory 是否含 gold preference（判定用字符串/语义匹配，B2 时定）。
2. **命中条件下的 adherence**：只在召回命中的实例上比 adherence——隔离"检索到了但下游没用上"（注入式的核心弱点假设）。

## 4. API key 需求

**默认方案不需要你提供任何新 key**：
- Anthropic key（已有）：我们的系统 + judge + 下游模型 + baseline 内部 LLM（若配 haiku 成功）。
- OpenAI key（已有）：Mem0/Graphiti 的 embedding；及 baseline 内部 LLM 的备选（gpt-4o-mini）。
- Neo4j：docker 本地跑，无 key。Mem0 向量库用内置默认（本地 qdrant/chroma），无 key。

**唯一需要你出手的情形**：若想在论文里对比 **Zep Cloud 产品版**（而非 Graphiti OSS），需要你注册 Zep Cloud 账号拿 API key。我的建议是不需要——OSS 版本可复现、可版本锁定，学术对比更干净；引用其论文数字补充产品版表现。

## 5. 执行切分（批准后开始；估时以 harness 复用 pilot 基建为前提）

| 步骤 | 内容 | 产出/闸门 | 估时 |
|---|---|---|---|
| B0 | 环境冒烟：装 mem0ai、graphiti-core、docker neo4j；各插 3 条偏好、检索回读；确认内部 LLM 能否配 haiku | 冒烟脚本 + 版本/配置定案 | 0.5 天 |
| B1 | adapter 层：`BaselineMemory` 协议（`ingest(turns)` / `inject(query) -> str`），mem0/graphiti 两实现 + 记账埋点 | `pilot/src/pilot/baselines.py` + 单测 | 1 天 |
| B2 | 并入 pilot harness 成 6 臂，20 实例 dry-run，人工看 10 条输出核对注入格式与 judge 行为 | dry-run 结果 + 召回命中判定定案 | 0.5 天 |
| B3 | 全量 PrefEval 子集 6 臂 × 2 下游档，出分析表（含成本表、命中率分解） | `docs/baseline-results.md` | 1 天 |
| B4（可选） | LongMemEval preference 子集：先抽 20 题人工判"是否 requirement-like、judge 能否复用"，**闸门通过才全量**；只跑 A1/A4/B1/B2 四臂 | 闸门 memo → 全量表 | 1 天 |

依赖与顺序：B1–B3 依赖 pilot 的 instances/judge/analyze（pilot plan Task 1–5、8–9）。**推荐执行顺序：pilot 骨架先行（尤其 Task 1 的 PrefEval 假设核验闸门），baseline 臂作为 pilot Task 6（arms.py）的扩展一次接入，B3 与 pilot 主实验同一批跑**——同一套实例与 judge，两篇幅的数字一次产出。

## 6. 风险

- Graphiti 的 Anthropic LLM 支持成熟度未核验（B0 验证；不行就 gpt-4o-mini 并注明）。
- Mem0/Graphiti 的写入延迟可能远高于我们（per-fact update / 图构建）——跑批时间预算按 baseline 臂 ×3 预留；这本身是论文数据不是障碍。
- LongMemEval preference 子集可能太事实化（"记得我喜欢什么"vs 我们的"按我要求的方式做"）——B4 闸门存在的原因；闸门不过就只报 PrefEval，related work 里解释。
- 判定"召回命中"的 gold 匹配有主观性——B2 时用 20 条人工校准判定规则，规则落盘。
