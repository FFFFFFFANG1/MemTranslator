# Position-Anchor Refactor Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 repo 从「PrefEval 论文式 pilot 驱动」对齐回 `position_anchor.md`（开源 translator 产品优先），一次性完成文档定位重标、pilot 复盘冻结与 pilot/ 删除。

**Architecture:** 方向文档不删只冻结（加 banner）；pilot harness 按拍板从 dev 删除，git history 保留（最后完整版 `cab2cce`）；proto/ 不动（它已符合 anchor：requirement-only、≤2 call、haiku、人在环）。产品功能开发（编辑 diff 回流、default profile、热键壳）**不在本 plan 内**，见文末「后续独立 plan」。

**Tech Stack:** git、Python ≥3.12 + uv（仅 proto 回归验证用）。

---

## 0. 现状诊断（为什么偏了）

依据 2026-07-22 pull 后的 origin/main（d129816）与 origin/dev（cab2cce）：

1. **重心漂移**：dev 的增量几乎全是 PrefEval 四臂实验（harness Tasks 0–8 已建成，B2 dry-run 已跑：20 正例 + 5 负例），外加 Mem0/Zep 六臂 baseline plan、LongMemEval probe。anchor §3/§8 明确：PrefEval 主体是 content preference，不是我们的战场；bench 只是辅助指标。
2. **版本术语被实验挟持**：TODO.md 头部定义「v0 = pilot、v1 = phase 2」；anchor §7 定义 v0 = 产品壳立住。两套 v0 指向完全不同的工作。
3. **产品缺口停滞**：anchor §4 把「编辑 diff 回流」定为算法主线的学习信号，TODO 里它还是未动工事项；TODO 头部甚至写着「前端 demo 已冻结」——与 anchor §1「体验第一」直接冲突。
4. **北极星不在工作分支**：position_anchor.md 只在 main；日常工作在 dev，dev 不含 anchor。（Typeless 分析的权威版在 **research 分支**：151 行、含 2026-07-22 本地 app 逆向一手证据 §8；main 上是 111 行旧版；dev 上已按 adfe8c5「Move Typeless analysis to the research branch」有意移除。research 有独立价值，不动它。）
5. **dry-run 数字需要一个了结**（出处：docs/pilot-results-b2-dryrun.md、docs/pilot-results-b2-neg.md）：content-pref 集上 A3 translator 的 adherence 输给注入臂（强下游 75% vs 100%，Δ−25pp，CI 不含 0），但 FAR 20% vs 40–60%、下游 input token 约为注入的 1/5、P(noop|neg)=4/5。这些数字按旧判据（G1）趋向 NO-GO，按 anchor 视角则是「战场选错了，产品面纪律（noop/FAR/token）反而是亮点」。不写下来就会丢。

**没偏的部分（不动）**：proto/ 全部——requirement-only store、2-call write path、0 生成式 call 的 read path、haiku translator、composer 人在环 demo、30 测试。memory-design.md 仍是 v1 主线设计文档。

---

## 1. 拍板记录（2026-07-22，siriux）

- **D1 = 取消**：pilot 全量 run（原 pilot plan Task 9–13：judge 校准、250 实例、GO/NO-GO）不跑；写复盘冻结（本 plan Task 1），G1–G3 作废。
- **D2 = 删除**：pilot/ 从 dev 移除，不做改名 bench/ 的降级保留；git history 保留一切（最后完整版 `cab2cce`）。将来需要小 bench 时按 anchor §8 重起最小实现或考古 history。
- **D3 = 直接改 dev**：不开 refactor 分支；Task 1–5 逐个 commit 到 dev，完成后 dev→main 同步（Task 6）。
- **执行状态**：Task 0（dev 同步 main）已于 2026-07-22 随本 plan 入库时执行；**Task 1–6 等 siriux 指令后再动**。

---

## Task 0: dev 同步 main（已执行 2026-07-22）

- [x] **Step 1: 本 plan 先入 main**（方向文档与 anchor 放一起）：`git checkout main && git pull && git add docs/2026-07-22-refactor-plan.md && git commit && git push`
- [x] **Step 2: dev 并入 main**：`git checkout dev && git merge main && git push origin dev`（带入 position_anchor.md、新 README、本 plan；无冲突。merge 同时保留了 dev 对 docs/typeless-analysis.md 的删除——该文件按 adfe8c5 归 research 分支管，属预期）

说明：**不做 main←dev 的反向合并**——pilot 反正要删（D2），不让它在 main 上出现一轮；Task 6 完成后两分支自然收敛一致。本 plan 引用的 `pilot-results-b2-*.md` 在 Task 6 之前只存在于 dev。

---

## Task 1: pilot 复盘冻结 memo

**Files:**
- Create: `docs/pilot-postmortem.md`

- [ ] **Step 1: 写入以下全文**

```markdown
# PrefEval pilot 复盘（冻结 memo）

> 2026-07-22。pilot 按 docs/2026-07-21-pilot-plan.md 执行到 harness 建成 +
> B2 dry-run，之后按 position_anchor.md 重定位停跑。本文记录已产出的数字与
> 结论。数字出处：docs/pilot-results-b2-dryrun.md、docs/pilot-results-b2-neg.md。

## 执行到哪

- harness 全部落地（plan Tasks 0–8：cached client / data_prep / arms /
  translator / judges / orchestrator / analyze + Mem0/Graphiti baseline
  adapter），断点续跑可用。
- 已跑规模：20 正例（run `b2-dryrun`）+ 5 负例（run `b2-neg`）。
- 未执行：judge 人工校准（Task 9）、250 实例全量（Task 10）、GO/NO-GO 决策
  memo（Task 13）。G1–G3 预注册判据随本次冻结**作废**，不再有「pilot 定生死」。

## 数字（n 小，方向性参考）

- **adherence（正例，PrefEval 以 content preference 为主）**：A3 translator
  低于注入臂——强下游 75% vs 100%（Δ −25pp，95% CI [−45, −5]）；弱下游
  70% vs 80–85%（CI 含 0）。
- **FAR（负例 n=5）**：A3 20% vs 注入臂 40–60%；P(noop|neg) = 4/5。
- **下游 input token（均值/实例）**：A3 58/39 vs 注入 302–326/221–246，约 1/5。
- **translator 行为**：P(apply|pos) = 14/20；parse error 0；保真 judge 判
  核心任务改变 0、越权加需求 0。

## 结论（anchor 视角）

1. 在 content preference 主导的数据上，「编译进输入」拉 adherence 确实不如
   「整包注入」——这不是我们的战场（anchor §3/§8）；数字如实留档，不翻案。
2. translator 的产品面优势正在负例纪律（FAR 低、noop 高）与 token 成本——
   与 anchor 的 false-application 人工兜底叙事一致。样本太小，结论待将来的
   delivery bench 复测。
3. harness 代码已按拍板（D2）从 dev 删除，git history 保留（最后完整版
   `cab2cce`）。将来需要小型 delivery bench 时（anchor §8），可考古其中的
   cached LLM client、FAR/preservation judges、bootstrap analyze 与长输入
   保真集，或从零散 case 重起最小实现。
```

- [ ] **Step 2: Commit**

```bash
git add docs/pilot-postmortem.md
git commit -m "[docs] Freeze PrefEval pilot with a postmortem memo"
```

---

## Task 2: 历史文档加冻结 banner

**Files:**
- Modify: `docs/idea.md`（第 1 行标题之后）
- Modify: `docs/diagnosis.md`（同上）
- Modify: `docs/2026-07-21-pilot-plan.md`（原有 blockquote 之前）
- Modify: `docs/2026-07-21-baseline-plan.md`（同上）
- Modify: `docs/longmemeval-pref-probe.md`（同上）

- [ ] **Step 1: 在 idea.md 与 diagnosis.md 标题行后各插入**

```markdown
> **[2026-07-22 冻结]** 历史文稿，不再单独定方向；项目定位以
> [position_anchor.md](../position_anchor.md) 为准。
```

- [ ] **Step 2: 在两份 plan（pilot-plan、baseline-plan）标题行后各插入**

```markdown
> **[2026-07-22 冻结]** 本 plan 随 anchor 重定位停止执行（执行进度与数字见
> [pilot-postmortem.md](pilot-postmortem.md)）；G1–G3 / B0–B4 判据作废。
> harness 已从 dev 删除（git history `cab2cce`），定位以
> [position_anchor.md](../position_anchor.md) §8 为准。
```

- [ ] **Step 3: 在 longmemeval-pref-probe.md 标题行后插入**

```markdown
> **[2026-07-22 冻结]** LongMemEval 副战场随 anchor §8 取消；本文仅留作数据事实记录。
```

- [ ] **Step 4: Commit**

```bash
git add docs/idea.md docs/diagnosis.md docs/2026-07-21-pilot-plan.md docs/2026-07-21-baseline-plan.md docs/longmemeval-pref-probe.md
git commit -m "[docs] Mark superseded docs as frozen under the position anchor"
```

---

## Task 3: 重写 TODO.md

**Files:**
- Modify: `TODO.md`（整文件替换）

- [ ] **Step 1: 用以下全文替换 TODO.md**

```markdown
# TODO

> 2026-07-22 起以 [position_anchor.md](position_anchor.md) 为纲。版本术语按
> anchor §7：**v0** = 产品壳立住 + oracle requirement 验证；**v1** = memory
> 管线（extraction → CRUD → 入库 → recall）+ 编辑回流；**v2** = latency 与
> 前端体验。旧术语（v0 = pilot）作废，pilot 归档见
> [docs/pilot-postmortem.md](docs/pilot-postmortem.md)。demo 解除冻结。

## v0 — 产品壳（当前优先）

- [ ] **编辑 diff 回流**（anchor §4 钉死的学习信号；typeless-analysis §4.5
  ——research 分支——论证这是我们对 Typeless 的结构性信息优势）：demo
  composer 已能编辑 polished 文本，缺 polished→sent 的 diff 采集、落盘、
  进 write path。
- [ ] **default profile fallback**（design §3.3）：MemoryEntry 加
  `source: "default" | "learned"`；出厂条目参与 recall，learned 优先/可
  SUPERSEDE；demo memory 面板区分展示。内容集待产品定义。
- [ ] **热键壳形态拍板**（anchor §2.2：热键触发 + 聊天框内快速改写）：
  macOS 菜单栏 app（AX 读写焦点输入框）vs 浏览器扩展 vs 继续用 web demo
  承载 v0。拍板后另立 plan。
- [ ] **oracle 验证数字**（anchor §7 v0）：小规模 delivery case 上
  A0（不改写）vs A3（translator），报 delivery adherence / noop / FAR /
  保真 / token。报数字，不设 GO/NO-GO 门（anchor §8）。前置：下方 bench
  段的最小集。

## v1 — memory 管线（设计：docs/memory-design.md）

- [ ] embedding 混合召回（design §3.3；当前 keyword+strength+新近度）。
- [ ] consolidation confidence 字段 + 阈值 + 向量兜底（Mandol 协议，缓解
  design §6-2 重复检测漏召）。
- [ ] `expires_hint` 语义：`"this_session"` 目前直接进 `expires_at` 做字符
  串比较，非 ISO 值因字典序恒判存活——在 to_entry 里解析或 prompt 禁掉。
- [ ] 隐式 retire：strength=1 且 N session 未 applied → retired（等
  last_applied_at 数据积累）。
- [ ] 并发写保护（design §6-4；v0 前提单写者）。
- [ ] wrong-case dump（HMS 借鉴）：判错/漏应用 case 全量落盘，回流迭代。

## v2 — latency / 前端体验

- [ ] 两级生成：即时 patch + 可选终稿深度重写（typeless-analysis §5，
  research 分支）。
- [ ] tiktoken 对 Claude 文本低估 ~15–20%：压缩窗口预算够用；做成本统计时
  换 `count_tokens` API。

## bench（辅助指标，不驱动方向 — anchor §8）

- [ ] 需要时起最小 delivery bench：自建 seed + 零散收集的 delivery case，
  小规模报数字。pilot harness 已从 dev 删除（拍板 D2），git history
  `cab2cce` 可考古 cached client / judges / analyze。
- [ ] （可选，一次性）Mem0 / Graphiti 清醒对照：把 general memory 的范围改
  成只记 requirement + 同样改写协议后再比（anchor §8 预期数字可能接近）。
```

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "[docs] Rewrite TODO around the anchor roadmap and unfreeze the demo"
```

---

## Task 4: README 补新文档条目

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新文档列表**（保留标题与定位句；`position_anchor.md`、`proto/` 行已在）

新增两行：

```markdown
- `docs/typeless-analysis.md` (research branch) — Typeless product analysis (our runtime-form reference)
- `docs/pilot-postmortem.md` — PrefEval pilot: what ran, the numbers, why it stopped
```

并把原 pilot-plan 行改为：

```markdown
- `docs/2026-07-21-pilot-plan.md` — PrefEval pilot plan (frozen; see pilot-postmortem.md)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "[docs] Point README at the postmortem and refactor plan"
```

---

## Task 5: 删除 pilot/

**Files:**
- Delete: `pilot/`（全部跟踪文件，含 src/tests/scripts/data/instances 与 uv.lock）
- Modify: `.gitignore`（去掉 pilot 两行）

保留不删：`docs/pilot-results-b2-*.md`、`docs/prefeval-notes.md`、`docs/baseline-b0-memo.md`——它们是 postmortem 数字的出处与过程记录，留在 docs/。

- [ ] **Step 1: 删除跟踪文件**

```bash
git rm -r pilot
```

- [ ] **Step 2: 清理磁盘残留（未跟踪的 PrefEval clone 与 LLM 缓存；均可再生——PrefEval 可重 clone，缓存按内容寻址、重跑即回填）**

```bash
rm -rf pilot
```

- [ ] **Step 3: .gitignore 去掉 pilot 条目**

```bash
sed -i '' '/^pilot\/data\/raw\/$/d; /^pilot\/runs\/$/d' .gitignore
```

- [ ] **Step 4: 验证 proto 不受影响**

```bash
cd proto && uv run pytest -q && cd ..
```

Expected: 全绿（无 API key 时 e2e smoke 跳过）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "[cleanup] Remove the PrefEval pilot harness per decision D2; history keeps it at cab2cce"
```

---

## Task 6: push 与 main 回同步

- [ ] **Step 1: push dev**

```bash
git push origin dev
```

- [ ] **Step 2: dev→main 同步（两分支自此收敛）**

```bash
git checkout main && git merge dev -m "[docs] Sync the anchor refactor from dev" && git push origin main && git checkout dev
```

预期副作用：main 上的旧版 docs/typeless-analysis.md（111 行）随本 merge 被删——dev 在 adfe8c5 已把该文件移交 research 分支（research 版 151 行更全），main 不再留旧版。

- [ ] **Step 3: research 分支保留不动**——它是 Typeless 分析的权威所在（含 main 旧版没有的 §8 本地逆向一手证据），不是冗余分支。

---

## 后续独立 plan（不在本 plan 内，按 TODO v0 顺序）

1. **编辑 diff 回流**：demo composer 采集 polished→sent diff → 落盘 → 进 write path 作为 requirement 证据源。动 proto/（demo/app.py、transcript.py、pipeline.py），需要先读现行实现再写 plan。
2. **default profile fallback**：schema `source` 字段 + 出厂条目集 + demo 面板区分；「内容集待产品定义」是前置拍板点。
3. **热键壳**：TODO v0 第 3 条拍板后立 plan（mac 菜单栏 app / 浏览器扩展 / 续用 web demo）。
4. **最小 delivery bench**（需要时，anchor §8）：自建 seed case 起步，考古 history 或重写最小 harness。
5. **v1 memory 管线迭代**：TODO v1 段，依赖 diff 回流落地后的真实信号。

## Self-review 记录

- anchor §1–§8 逐条对照：§1/§7（TODO 重排，Task 3）、§2（proto 不动，诊断 §0）、§3/§8（postmortem + TODO bench 段，最小 bench 推迟到需要时）、§4 学习信号（后续 plan 1，TODO v0 置顶）、§5（proto 已 haiku，无动作）、§6（banner，Task 2）。无遗漏。
- 拍板 D1/D2/D3 已写入 §1 并贯穿各 task；原「pilot→bench 降级复用」方案随 D2 废弃。
- 无 TBD/占位符；所有插入文本给全文。
- 一致性：Task 1/2/3 三处对 pilot 删除的表述统一为「已从 dev 删除，git history `cab2cce`」；banner 链接相对路径（docs/ 内互链、`../position_anchor.md`）已核。
- 2026-07-22 修正：初版误记「research 已并入 main、无独立价值」——实际 typeless-analysis 权威版在 research（151 行，含 §8 本地逆向；main 旧版 111 行；dev 按 adfe8c5 有意不携带）。相关引用已改标 research 分支，Task 6 对 main 旧版的预期删除已写明。
