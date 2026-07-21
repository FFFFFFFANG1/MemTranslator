# Memory 层设计提案（v0）：data structure 与 runtime mechanism

> 2026-07-21。提案性质，供讨论修改；不是定案。
> 定位：这是 [idea.md](idea.md) 中 "Managed User Memory" 的构建层设计——feedback / 重复要求如何变成 memory、memory 如何维护、translator 如何读。pilot（[2026-07-21-pilot-plan.md](2026-07-21-pilot-plan.md)）用 oracle memory，**不依赖本层**；本层是 GO 之后 Phase 2 的实现蓝图，但 schema 现在就定，保证 pilot 的 translator 接口向前兼容。

## 0. 硬约束与设计立场

约束（本次讨论给定）：

1. **Write path 固定两步：extraction → consolidation，各一次 LLM call，每次触发至多 2 次生成式调用。**（embedding 调用不计入：便宜、可本地、非生成式，单独核算。）
2. 只存 **requirement / preference**（用户对 agent 行为的要求），不存事实知识。五个参考系统存的都是通用记忆（事实、事件、实体）；我们是 idea 里说的"意图解释层不是知识层"，这决定了下面一系列取舍。
3. 错误 memory 的代价高于遗漏：translator 会把它编译进指令、下游无从纠错（diagnosis §四）。所以全链路的默认失败方向是**保守**——吃不准就丢弃（DROP），和 translator 的 noop 默认同一哲学。
4. 每条 memory 必须能指回用户原话（provenance + quote）——可审计、可撤销，与 patch-based translation 的卖点一致。

## 1. 参考系统速览与借鉴对照

| 系统 | 核心机制（出处见 §8） | 我们借 | 我们不借（理由） |
|---|---|---|---|
| **Mem0** | 两阶段：extraction（对话摘要+近期消息→候选事实）→ update（**每条候选**一次 LLM call，vs 向量相似旧记忆判 ADD/UPDATE/DELETE/NOOP） | 两阶段骨架；操作词表的思路 | per-fact update call（预算不允许，且批量单 call 让 LLM 有全局视野反而利于去重）；破坏性 UPDATE/DELETE（diagnosis 引述的审计：update/consolidation ~20% 失败率、静默信息丢失，2026 新算法退回 ADD-only——二手，出处 [diagnosis.md](diagnosis.md)） |
| **Zep / Graphiti** | bi-temporal 时序知识图谱：每条 fact 四时间戳（系统线 t_created/t_expired + 事实线 t_valid/t_invalid）；冲突时 **invalidate 旧边而不删除**；episode 级 provenance | invalidate-not-delete → 我们的 status + supersedes 链；episode provenance → 我们的 provenance 数组 | 图存储（requirement 之间关系稀疏，单用户 10²–10³ 条列表足够，唯一的关系就是 supersedes 链）；完整 bi-temporal（requirement 没有"在世界中何时为真"的维度，单时间线 + expires_at 够用） |
| **SimpleMem** | 三视图索引 memory unit（semantic 稠密向量 / lexical 稀疏关键词 / symbolic 结构化元数据）；滑窗 + entropy 闸门过滤后单 pass LLM 压缩；异步 consolidation 把相似簇合成高层抽象、**原条目 archive 不删**；检索按 query 复杂度自适应 k=3–20 | 三视图索引思路（→ embedding + keywords + 结构化 scope）；"先判有没有信号、再提取"内置进 extraction prompt；archive 不删 | 递归摘要合成（把多条记忆合成系统生成的抽象条目会产生"没有用户原话背书的 requirement"，违反立场 4；我们唯一的合成点是 SUPERSEDE 的 merged_requirement，且强制保留双方 provenance） |
| **EverMemOS** | MemCell（Episode 叙述 + Atomic Facts + **Foresight**：带时间区间的前瞻意图/临时状态 + Metadata）；语义边界检测分段；在线聚类成 MemScene（带 recency bias 与冲突追踪）；存储上 Markdown 为 source of truth + LanceDB 索引、后台 daemon 同步 | Foresight 的 time-bounded 概念 → expires_at（"这周先别用 X""这个 deadline 前都要最短路径"这类临时要求）；"人可读文本为 source of truth + 派生索引"的存储模式 | 边界检测（我们以 session 为天然边界）；在线聚类 / MemScene / user profile 合成（同 SimpleMem 一栏的理由） |
| **OpenViking** | 定位为"用户与 agent 之间的 memory center"；`viking://` 虚拟文件系统（resources / user / agent 目录，URI 定位）；写入自动分 L0 一句话摘要 / L1 概要 / L2 全文三层；Directory Recursive Retrieval（先定位目录再层内递归检索） | 架构定位与我们同构（memory 层站在用户与 agent 之间），可在论文 related work 里正面引用；目录路径启发了 scope 的层级 task_type 表示 | L0/L1/L2 分层（requirement 本身就是一句话，即 L0 粒度，无层可分）；文件系统导航式检索（量级不需要） |
| **HMS**（代码深读，见 [hms-mandol-notes.md](hms-mandol-notes.md)） | answer 前用纯规则（regex+词重叠计分，零 LLM）把 recall 结果组织成 evidence ledger；失败 case 全量落盘→人工归纳静态 control→关键词门控注入；consolidation prompt 纪律（NO COMPUTATION / SAME FACET→UPDATE / PRESERVE HISTORY）；`mentioned_at` 代码赋值不信 LLM | wrong-case dump 进 pilot；纪律条款已并入我们 Call 2 prompt；directives 双注入格式参考 translator patch 措辞 | ledger 本体（我们 memory 视图小，暂不需要确定性重组） |
| **Mandol** | basic+abstract 双层图记忆；emotional memory（偏好层）为 session 级 map-reduce 摘要且**默认检索路径不查它**；每 session 数十次 LLM call；match-judge 协议（编号候选+confidence 阈值+向量兜底） | match-judge 协议候选用于 REINFORCE 判定升级；单行可 grep 的监控输出 | 偏好当摘要存（被集成端边缘化的实证反例，论文竞品分析直接引用）；消化式整段重写（与 append-only 对立） |

一句话总结差异：这些系统解决"**什么都记，然后找得到**"；我们解决"**只记要求，然后用得准**"。规模小三个数量级、错误代价高一个数量级，所以设计整体从"检索效率"倾斜向"写入保守 + 可审计"。

## 2. Data structure

### 2.1 MemoryEntry（存储原子）

```json
{
  "mid": "m-20260721-a3f2",
  "requirement": "When reviewing research papers, compare against related work and assess novelty rather than only summarizing.",
  "polarity": "do",
  "scope": {
    "condition": "the user asks to read, review, or evaluate a research paper or research idea",
    "task_type": "research.paper-review",
    "keywords": ["paper", "review", "novelty", "related work"]
  },
  "strength": 3,
  "status": "active",
  "supersedes": [],
  "superseded_by": null,
  "provenance": [
    {"session_id": "s-0712a", "turn": 14,
     "signal": "next_turn_feedback",
     "quote": "我不是要总结，我要你分析它的问题",
     "at": "2026-07-12T09:30:00Z"}
  ],
  "created_at": "2026-07-12T09:31:02Z",
  "updated_at": "2026-07-20T22:10:44Z",
  "last_applied_at": "2026-07-20T22:10:44Z",
  "expires_at": null
}
```

字段说明与设计理由：

- `requirement`：陈述式、单条单需求、英文（translator prompt 语言）。这是唯一进 translator 上下文的正文。
- `polarity`：`do | dont`。禁止类要求（"不要改我的原始结构"）与要求类分开标，方便 translator 措辞和统计。
- `scope`（三件套，对应 SimpleMem 的三视图）：
  - `condition`（semantic 视图的判定面）：自然语言适用条件，**判定权在 LLM**（consolidation 时比对、translator 读时决定 apply/noop）。机械层从不解析它。
  - `task_type`（symbolic 视图）：开放词表、点分层级（`research.paper-review`、`writing.email`），借 OpenViking 目录路径思路。用于统计、聚合展示、粗过滤；**不是判定依据**。
  - `keywords`（lexical 视图）：召回补充，防换措辞后 embedding 漏召。
- `strength` + `provenance[]`：idea 的"重复即证据"落点——重复不产生新条目，而是 REINFORCE（strength+1、append provenance）。`signal ∈ {next_turn_feedback, repeated_requirement, explicit_instruction}` 对应 idea 的两类监督信号 + 用户显式指示；`quote` 必填（立场 4）。
- `status` + `supersedes/superseded_by`：append-only 状态机（借 Zep invalidate-not-delete、避 Mem0 破坏性改写）。条目一旦写入内容不再变（除 strength/provenance/last_applied_at 的追加类更新）；修订 = 新条目 ADD + 旧条目标 superseded，双向链接。回滚 = 沿链翻转 status，天然可撤销。
- `expires_at`（借 EverMemOS Foresight）：临时要求的过期时间；read path 机械过滤，不劳 LLM。
- `last_applied_at`：translator 的 `applied_memory_ids` 回流写入（见 §3.3），为 retire 策略积累使用数据。
- embedding 不入主记录：主存储保持人可读（借 EverMemOS "Markdown source of truth + 派生索引"模式），embedding 存旁路索引，坏了可全量重建。

### 2.2 状态机

```
           ADD                    SUPERSEDE(by new)
  (candidate) ──→ active ──────────────────────────→ superseded
                    │  ↑ REINFORCE (strength+1)            │
                    │                                      │ (人工/回滚: 翻转)
                    └──→ retired（显式作废或长期未用，策略见 §6）
```

任何状态都不物理删除。read path 只见 `active` 且未过期的条目。

### 2.3 物理存储

- 单文件 JSONL（或 SQLite，实现时定）+ 旁路 embedding 索引（numpy 文件即可）。单用户 10²–10³ 条，全量扫描都在毫秒级，**不引入向量库/图库依赖**。
- `schema_version` 字段留在文件头，方便演化。

## 3. Runtime mechanism

### 3.1 触发

默认 **session 结束时触发一次** write path（一个 session 一份 transcript，天然边界，不需要 EverMemOS 式边界检测）。变体：长 session 可加中途触发（每 N 轮），预算按次计，机制不变。

### 3.2 Write path（两次 LLM call，流程图）

```
 session transcript
        │
        ▼
 [Call 1: Extraction]  ──  0 候选 ──→  结束（本次共 1 call）
        │ 1..8 候选
        ▼
 embedding 召回（非 LLM）：每候选 top-5 相关 active 记忆，合并去重 ≤20 条
        │
        ▼
 [Call 2: Consolidation（批量单 call）]
        │ 每候选一个 op
        ▼
 机械执行：ADD / REINFORCE / SUPERSEDE / DROP
 （parse 失败 → 整批 DROP + 原始输出进 quarantine 文件待人工）
```

**Call 1 — Extraction。** 输入：session transcript（超长则截尾部 + 前部摘要，实现细节）。输出契约：

```json
{"candidates": [
  {"requirement": "...", "polarity": "do",
   "scope_condition": "...", "task_type": "...", "keywords": ["..."],
   "signal": "next_turn_feedback", "quote": "用户原话", "turn": 14,
   "expires_hint": null}
]}
```

Prompt 要点（完整 prompt 实现时写，要点先定）：

- 只认三类信号：next-turn 纠正/补充（idea 信号 1）、同类要求重复出现（idea 信号 2）、用户显式的"以后都要 X"。
- **不提取**：一次性情境要求（"这次翻译成法语"）、事实信息（"我用 conda"这类环境事实不是行为要求——是否单独建事实层是另一个提案，本层不管）、从 agent 行为反推的猜测。
- 每 session 上限 8 条，"only the clearest"；没有就输出空数组（SimpleMem entropy 闸门的职能内置到这里，不花第二次 call）。
- `quote` 必须逐字摘自 transcript（机械可校验：substring 检查，不通过的候选直接丢——零成本防幻觉）。

**Call 2 — Consolidation。** 输入：全部候选 + 召回的相关旧记忆。输出契约：

```json
{"ops": [
  {"candidate_idx": 0, "op": "ADD"},
  {"candidate_idx": 1, "op": "REINFORCE", "target_mid": "m-..."},
  {"candidate_idx": 2, "op": "SUPERSEDE", "target_mid": "m-...",
   "merged_requirement": "…（新表述，须同时被新旧 provenance 支持）"},
  {"candidate_idx": 3, "op": "DROP", "reason": "one-off situational request"}
]}
```

操作语义（与 Mem0 词表的对应关系标在括号里）：

| op | 语义 | 执行 |
|---|---|---|
| ADD（≈Mem0 ADD） | 新要求，与现存都不同 | 新建 active 条目 |
| REINFORCE（≈Mem0 NOOP 的加强版） | 与某现存条目语义等同 | target strength+1、append provenance；不产生新条目 |
| SUPERSEDE（替代 Mem0 UPDATE+DELETE） | 与某现存条目同 scope 明确冲突或明确修订 | 新条目 ADD（可用 merged_requirement）+ target 标 superseded，双向链接 |
| DROP | 一次性 / 情境性 / 吃不准 | 丢弃（extraction 原始输出留档，可事后审计） |

关键规则：SUPERSEDE 仅限"明确冲突/明确修订"；语义相近但不冲突 → 宁可 ADD 两条并存（translator 端有 scope 判定兜底），也不合并——合并是 Mem0 静默丢信息的主要来源（diagnosis 引述）。不确定一律 DROP（立场 3）。

与 Mem0 update phase 的本质差异：**批量单 call**。全部候选与全部相关旧记忆同框，LLM 有全局视野（候选之间的重复也能一次去掉），而 per-fact call 每次只见局部。这既是预算约束的产物，也可能是更好的设计——Phase 2 可作为消融点。

### 3.3 Read path（translator 消费，0 次生成式 call）

1. 机械过滤：`status == active` 且未过期；
2. 混合召回：query embedding 相似度 + keywords 命中，取 top-K（K=8，与 pilot 对齐；单用户量级小时可全量）；
3. 排序信号：相似度为主，strength、新近度为次；
4. 全部候选交给 translator——**scope 的最终判定在 translator**（pilot 已确立的路线：机械层只管召回，不管判定）；
5. 回流：translator patch 的 `applied_memory_ids` 写回对应条目的 `last_applied_at`，形成使用闭环。

**Runtime 形态（2026-07-21 决策）：typeless 式人在环。** polished input 生成后落回聊天输入框、**可被用户直接编辑后再发送**（类比 Typeless 语音输入的转写-修改流）。这改变了 false application 的风险论证：diagnosis §四指出翻译式架构错误不可逆（下游无从纠错），但在此形态下每个 patch 都过用户的眼睛和手，错误应用有人工兜底；被用户改掉的 patch 本身还是 next-turn feedback 的一种（编辑 diff 即监督信号，接近 PRELUDE/CIPHER 的 edit 信号），可回流 write path。FAR 指标仍是一等公民（用户不该被迫频繁修正），但从"安全问题"降级为"体验问题"。原型（proto/demo）已实现此交互。

不做 SimpleMem 式复杂度自适应 k、不做 OpenViking 式目录导航：量级不需要，等真到 10³+ 再说。

### 3.4 失败与降级表

| 故障 | 行为 |
|---|---|
| Call 1 输出 parse 失败 | 本 session 放弃提取，原始输出进 quarantine；下个 session 正常 |
| Call 1 quote 校验失败（非 substring） | 丢该候选，其余照常 |
| Call 2 输出 parse 失败 | 整批 DROP + quarantine（不猜、不重试半批） |
| Call 2 引用不存在的 target_mid | 该 op 降级为 ADD（宁可多一条，不可错改一条） |
| embedding 服务不可用 | Call 2 在无旧记忆对照下只允许 ADD/DROP；或推迟到下次触发 |
| store 写入中断 | JSONL append-only，天然半写可检测；重放 quarantine 恢复 |

## 4. Idea §Memory CRUD 的七种情形 → 本设计的映射

| idea 列举 | 落点 |
|---|---|
| 新增 | ADD |
| 重复 / 强化 | REINFORCE（strength+1，不重复建条） |
| 修改 / 冲突 | SUPERSEDE（append-only 修订链） |
| 失效 | expires_at 到期（机械） 或 retire（§6 策略） |
| 删除 | 用户显式要求 → 作为 next_turn_feedback 提取 → SUPERSEDE/retire；永不物理删除 |
| 读取 | read path（§3.3） |

即：把 CRUD 的开放问题收窄为**两个写操作（ADD、REINFORCE）+ 一个链式修订（SUPERSEDE）**，不做自由 UPDATE/DELETE。这是对 diagnosis "CRUD 是真难题、当副产品做大概率做不好"的正面回应：不解决通用 CRUD，只保留 requirement 场景需要的最小子集。

## 5. 预算核算（估算）

每次触发（= 每 session）：

| 项 | 次数 | 规模 |
|---|---|---|
| Extraction call | 1 | 输入 ~3–8k tok（transcript），输出 ~0.5k |
| Consolidation call | 0–1 | 输入 ~1.5k（候选+旧记忆），输出 ~0.3k |
| embedding | ~8 次 | 候选数 × 1（旧记忆 embedding 已缓存） |

flash 级模型（haiku / gemini-flash）下每 session < $0.01。生成式调用 ≤2，满足约束 1；无信号 session 只花 1 次。

## 6. 开放问题（不装作已解决）

1. **scope_condition 写多宽**：extraction 时生成的 condition 泛化粒度直接影响 translator 的 false application。CUPID 的警告（SOTA 模型 scope 推断 precision <50%，二手，出处 diagnosis.md）说明这是本方向最大的能力风险；兜底是 pilot 的 FAR 指标 + G3 门槛，但 extraction 端的 condition 生成规范需要 Phase 2 实验定。
2. **repeated_requirement 的跨 session 视野**：重复检测依赖 Call 2 时召回到旧条目（换措辞可能 embedding 漏召，keywords 只是补丁）。若实验发现漏召显著，候选方案：REINFORCE 判定放宽到"高相似即等同"，或加一个廉价的定期离线去重 pass（会破 2-call 约束，需另立预算）。
3. **retire 策略**：隐式退休（如 strength=1 且 N 个 session 未 applied → retired）的 N 取多少、要不要衰减，等 last_applied_at 数据积累后再定；v0 只做显式 retire。
4. **并发写**：同一用户多 session 并行（我们自己就是这种用户）。v0 单写者队列（write path 串行执行）；真冲突再考虑 per-session staging + 合并。
5. **超长 transcript**：extraction 输入的截断/摘要策略（SimpleMem 滑窗 vs 简单截尾），实现时用真实数据定。
6. **事实层要不要**（"我用 conda、路径带空格"这类环境事实对 translator 也有用，但不是 requirement）：本提案显式排除；若要，另立一层，勿混入本 store。

## 7. 与 pilot / 论文的关系

- pilot 的 `memory_store` 条目 `{mid, text, topic}` 是本 schema 的投影：`text ↔ requirement`、`topic ↔ scope.task_type`。translator 消费格式不变，pilot 结论可直接迁移到本层产出的真实 memory 上。
- Phase 2 的 feedback→requirement 提取实验（CUPID session / WildFeedback 信号）就是对 Call 1 的评测；translator-vs-injection 结论若 GO，本设计是系统论文里 "Managed User Memory" 一节的实现。
- 论文叙事上：§1 的对照表直接可用作 related work 中 memory 系统一节的骨架（正面处理而非归为 top-k 注入，回应 diagnosis 的立论软肋）。

## 8. 出处

访问日期均 2026-07-21。标注：一手 = 论文/官方文档原文；二手 = 媒体/摘要站转述，关键论断建议实现前复核原文。

| 系统 | 来源 | 性质 |
|---|---|---|
| Mem0 | [arXiv 2504.19413](https://arxiv.org/pdf/2504.19413)（两阶段、ADD/UPDATE/DELETE/NOOP） | 一手（摘要级核对） |
| Mem0 失败率与 2026 ADD-only 回退 | [diagnosis.md](diagnosis.md) 引述的错误审计 | 二手，未独立核验 |
| Zep / Graphiti | [arXiv 2501.13956](https://arxiv.org/abs/2501.13956)；[Zep docs](https://help.getzep.com/graphiti/getting-started/overview)（bi-temporal 四时间戳、edge invalidation） | 一手（摘要级核对） |
| SimpleMem | [arXiv 2601.02553](https://arxiv.org/abs/2601.02553)（三视图索引、滑窗 τ=0.35 闸门、每窗口单 pass、簇触发 consolidation τ=0.85、k=3–20 自适应、原条目 archive；vs Mem0 F1 +26.4%、构建 14×） | 一手（HTML 全文提取） |
| EverMemOS | [arXiv 2601.02163 汇总页](https://www.emergentmind.com/papers/2601.02163)（MemCell 四组件、MemScene、三阶段生命周期）；[DeepWiki](https://deepwiki.com/EverMind-AI/EverMemOS/6.2-memory-extraction-components)（Markdown source of truth + LanceDB + daemon）；[repo](https://github.com/EverMind-AI/EverMemOS) | 二手（汇总站/生成式 wiki），实现前建议读原论文 |
| OpenViking | [MarkTechPost 2026-03](https://www.marktechpost.com/2026/03/15/meet-openviking-an-open-source-context-database-that-brings-filesystem-based-memory-and-retrieval-to-ai-agent-systems-like-openclaw/)（viking:// 文件系统、L0/L1/L2、Directory Recursive Retrieval）；[官方 blog](https://blog.openviking.ai/post/openviking-agent-memory-design/)（未能抓取，网络拦截） | 二手 |
| HMS | [Shadow-Weave/HMS](https://github.com/Shadow-Weave/HMS) 代码深读，关键引用经人工抽查，文件行号见 [hms-mandol-notes.md](hms-mandol-notes.md) | 一手（代码级） |
| Mandol | [AgentCombo/Mandol](https://github.com/AgentCombo/Mandol)（main 分支）代码深读 + [arXiv 2606.29778](https://arxiv.org/abs/2606.29778)；注意 main ≠ paper-repro，详见 notes | 一手（代码级） |
