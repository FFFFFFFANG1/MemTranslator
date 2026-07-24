# 两条信号路的算法提案（细化 memory-pipeline-proposal §1–2）

> 2026-07-23，提案待拍板。两条更新信号路：**路 A** = user message 流（按批，5–10 轮提取一次）；**路 B** = 改写后被用户再编辑的 diff（我们独有的信号面）。先盘相关工作的做法，再给算法。token 红线不变：每轮全部 LLM 调用 <10k。

## 0. 相关工作怎么做（与适配判断）

**对话流提取类（路 A 的参照）：**

| 工作 | 机制 | 借 / 不借 |
|---|---|---|
| Mem0（arXiv 2504.19413） | 两阶段：extraction（最新交换+rolling summary+近 m 条）→ update（**每条** fact 检索 top-s 相似旧记忆，LLM 选 ADD/UPDATE/DELETE/NOOP） | 借两阶段解耦与操作集；**不借 per-fact 一次 call**（token 贵），改合批；DELETE 改 SUPERSEDE（append-only） |
| Generative Agents | 记忆流 + importance 打分（LLM 1–10）+ recency/relevance 三元检索；反思由累积 importance 触发 | 借 **salience 打分作噪声闸门**（并入提取输出，不加 call）；反思≈我们的低频 consolidation |
| LangMem 等后台管理器 | hot path 零写入，后台批处理提取+整理 | 与我们"攒批+空闲冲刷"同构，印证方向 |
| Cursor Memories（产品，已下线） | sidecar 模型观察聊天、提议 memory、**人工批准**；2.1.x 起整个功能移除、回归手写 Rules | 教训：低密度聊天猜测 + 逐条人审的组合没立住。我们的差异：行为信号密度高（diff/纠正），入库自动 + 可退役 + 随时可见（上一份提案拍板点 1 的佐证） |
| HMS（深读笔记在 git `ddaf46a`） | requirement 类记忆（directives）**全人工维护**；judge 错例全量落盘→人工归纳静态 controls 迭代十几轮 | 借 wrong-case dump→规则迭代的通道；自动提取是它没做的、我们的空缺 |
| Mandol（同上） | 偏好层=session 级摘要且默认检索**不查**；写路径数十 call | 反面实证（论文可引）；正面借 **match-judge 协议**：编号候选 + confidence≥0.7 才合并 + LLM 失败降级向量最近邻 |
| SimpleMem（arXiv 2601.02553） | memory unit = content/entities/topic/timestamp/salience，**三层索引**：dense 向量 + BM25 + 符号元数据（确定性过滤）；写入时批内合成去冗余；检索按意图分级定深度 k=3–20 | 借**符号层思想**：requirement 加 scope + facet key 做确定性分桶与过滤（§2.5）；借"入库前批内合成"（进提取 prompt 指令）。不借三层索引全套与 per-query intent planning（我们量级几十条、热键轮 0 额外调用是红线） |

**执行反馈归纳类（路 B 的参照——没有现成工作做"改写-再编辑 diff"，以下是最近邻）：**

| 工作 | 机制 | 对应到路 B |
|---|---|---|
| Reflexion | 失败轨迹→语言化反思入库，影响后续尝试 | reverted（整体拒绝）→ 归因"为什么被拒" |
| Dynamic Cheatsheet（arXiv 2504.07952） | Generator+Curator 双模块：答完即策展——有用→入 cheatsheet，错→修剪 | **translator 自己的 style guide 旁库**（见 §2-B2），Curator 即策展 call |
| Agent Workflow Memory | 从成功轨迹归纳可复用 workflow | 从 diff 批归纳可复用的改写规则 |
| TextGrad / OPRO 一族 | 失败案例→"文本梯度"→改 prompt | 连续误用的 requirement → LLM 生成**收窄版**走 SUPERSEDE |
| BPO | 用 (原 prompt, 更好 prompt) 偏好对训练改写器 | 我们不训练，但 (polished, final) 对天然是 BPO 语料形态——先攒着，未来可选 |

## 1. 路 A：对话流批量提取

```
每条 submit ─▶ 机械预筛(0 token) ─▶ 信号轮入队
                                       │  批满 N=8 轮（5–10 可调）或空闲 30min
                                       ▼
                     Extraction call ×1（haiku，3–4k）
                     输入：信号轮(各截300t) + 全库一行索引(≤700t)
                     输出：candidates[{text, kind, target_id?, salience, quote}]
                                       │  salience<3 丢弃
                                       ▼
                     落库：new→ADD / reinforce→strength+1 / contradict→SUPERSEDE
                                       │  仅灰区（相似度0.55–0.8且A3未定target）
                                       ▼
                     match-judge call ×1（可选低频，~1k）：编号候选+confidence≥0.7，
                     LLM失败→向量最近邻0.45兜底（Mandol 协议）
```

- 预筛路由（**2026-07-23 修订：句式表升级为句级候选定位**，rule-based 轮级门在长输入下不成立——用户把整份文档粘进 input、requirement 只是其中一句时，轮级截断会把信号截丢）：
  - `edited_after_polish`/`reverted` 归路 B；`accepted_verbatim` 走机械 strength+1；`natural` 进**三步定位**（全 0 LLM）：
  - **①分块**：标点+换行规则分句；识别"材料区"（连续长句、代码块、markdown 结构、引用块）vs"话语区"——粘贴文档的正文属于材料区，永不进提取 prompt；
  - **②句级打分**（特征加权）：纠正/立规词表（强）+ meta-discourse 领域词（格式/语气/长度/语言/风格/单位…）+ 祈使句式 + 对 agent 的二人称指涉 + 首尾位置加成 + 与已有 requirement key 的词面命中（提示 reinforce）。可选增强：本地小 embedding 对十几条原型句做相似度（plan B，先不引重依赖）；
  - **③span 提交**：top-k 高分句 ±1 句上下文窗，单轮提交上限 ~600t；全轮无句过阈 → 该轮不入批。**整批无信号 → 0 call 的性质保留**；recall 边界从"句式没命中"缩小到"多特征全不命中"，仍宁漏勿噪。
- 与 Mem0 的关键差异：关系判定（new/reinforce/contradict）借"索引在场"在提取 call 内一次完成，per-batch 而非 per-fact；灰区才补第二跳。
- 纪律（HMS，已在 v0 prompt 沿用）：NO COMPUTATION、SAME FACET → UPDATE NOT CREATE；只提 how-the-task-is-done（anchor §3 判据进 prompt）。

## 2. 路 B：编辑 diff 归因（核心：diff 不是一个信号，是四类）

| 类型 | 含义 | 去向 |
|---|---|---|
| b1 误用/过宽 | 我们注入的约束被删或削弱 | requirement 的问题 → strength−1；连续≥2 次 → 收窄或退役 |
| b2 措辞被改 | 约束保留但表达被重写 | **translator 的问题**（不是 memory 的）→ style guide |
| b3 新增约束 | 用户补了我们没注入的要求 | 新 requirement 候选 → 回流路 A 队列 |
| b4 内容改动 | 与约束无关的任务内容变化 | 噪声，丢弃 |

**B1 机械 span 归因（0 token，每次 diff 即时跑）：**
- `Δ_inject = diff(raw, polished)`（requirement 注入产生的 span，translate 时已知 applied_ids）
- `Δ_edit = diff(polished, final)`（用户改动的 span）
- 两组 span 求重叠 → 每条 applied requirement 机械判 kept / touched / removed
- 即时驱动 strength：removed → −1，kept → +1（difflib opcodes，免费）；touched 待 B2 定性

**B2 批量归因 call（haiku，攒 K=5 个 diff 或搭路 A 的批一起发，~2–3k）：**
- 输入：(raw, polished, final, applied 一行摘要) ×K，diff span 已由 B1 标注
- 输出逐条：`{req_id, verdict: misapplied|style|new_requirement|content, refined_text?, style_rule?}`
- 落库：
  - `misapplied` 且该 requirement 累计≥2 次 → 用 refined_text 走 SUPERSEDE（TextGrad 式：把"何时不适用"写进条目，如"邮件保持120词以内——正式求职信除外"）
  - `style` → 写入 **`kind: style_rule` 条目（同一 memory 后端，2026-07-23 修订）**：≤10 条、每条≤25 token（如"保留用户原句式，约束以从句追加，不整句重写"），随 translator system prompt 注入（+~250t）；超限时由同一 call 策展剪枝（Dynamic Cheatsheet 的 Curator）。**这是"改进改写机制"的具体载体**——语义上 requirement 管"任务怎么交付"、style_rule 管"改写本身怎么做"，但物理上同库同状态机同管理页（style_rule 不参与 scope 检索，仅在改写 prompt 组装时注入）
  - `new_requirement` → 入路 A 候选队列（两路在 update 层汇合）
- `reverted` 也进 B2 批：LLM 判"scope 收窄还是退役"（机械 −1 已先行）

## 2.5 Schema 升级：scope + facet key（2026-07-23 增，借 SimpleMem 符号层）

每条 requirement 除 text 外携带结构化属性（提取 call 顺带输出，不加调用）：

```
{ text, kind: requirement | style_rule,
  key: "facet.attribute",              # 受控两段式，词表引导+允许新造：email.length / code.explanation / tone.formality
  scope: {app?, task?, lang?},         # 缺省 = global；app 来自 hook/AX 上下文，task 由规则粗分类
  salience, strength, status, ... }
```

用途（对应 SimpleMem 的 rk 符号层，但不搬三层索引全套）：

- **Consolidation 分桶（D5 收紧）**：新候选先按 key 精确→前缀匹配分桶；同桶才做 REINFORCE/SUPERSEDE 判定——HMS 的 SAME FACET 纪律从 prompt 文字变成数据结构；灰区 match-judge 的范围从全库缩到桶内，多数情况桶命中后连第二跳都免了。
- **检索确定性过滤（D1 的规模化路径具体化）**：读路径先 scope 过滤（app/task 匹配当前上下文，0 LLM 规则判定），过滤后集合照旧全量注入；>100 条时再加 key 词面排序取 top-N——结构化路径先于 embedding。
- **与 SimpleMem 的差异要点**：它的 intent-aware retrieval planning 是 per-query 推断（QA 场景值得），我们热键轮 0 额外调用是红线——scope 过滤必须纯确定性。

## 3. 汇合与更新后的账本

**单一 memory 后端**：两路产出统一进同一个 store 的 update 层（ADD / REINFORCE / SUPERSEDE + 机械 strength 规则）。diff 是改进这个 store 的机制，不是第二套存储；style_rule 也只是库里的一种 kind。

| 轮型 | LLM 调用 | tokens (估) |
|---|---|---|
| 普通轮 | 0 | 0 |
| 热键轮（translator + style guide） | 1 | ~1.6k |
| 路 A 提取轮（每 ~8 轮） | 1（+灰区 match-judge ≤1） | 3–5k |
| 路 B 归因轮（diff 稀疏，常与 A 同批） | ≤1 | 2–3k |
| 最坏单轮全撞 | ≤4 | **~9.6k < 10k**（若拍板砍掉灰区第二跳则 ~8.6k） |

## 4. 拍板点

1. **批大小 N**：默认 8（你给的 5–10 区间中值），空闲冲刷 30min——数字可调。
2. **style_rule（原"style guide 旁库"）**：2026-07-23 已定——做，但**并入单一 memory 后端**作为 `kind: style_rule`（不另立库）；≤10 条上限可调。
3. **灰区 match-judge 第二跳**：(a) 保留（合并精度高，预算内）｜(b) 砍掉，灰区一律 ADD、留给低频 consolidation 收拾（更省更简单）。建议 (a) 先上，实测灰区命中率低再降级 (b)。
4. (polished, final) 偏好对持续落盘（已在 events 里），未来是否用于 BPO 式改写器训练——现在不决定，只保证数据形态不丢。
