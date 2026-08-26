# Memory 管线提案：提取 / 更新 / 检索（v1 主线，anchor §4）

> 2026-07-23，提案待拍板。硬预算：**每轮全部 LLM 调用 token 总和（输入+输出）< 10k**，此处按更严的目标设计：常规轮 0，热键轮 ~1.3k，最坏轮 ~8.4k。所有生成式调用走 haiku（anchor §5）；write path 生成式调用 ≤2 次（anchor §4）。数字标注 (估) 的均为 prompt 预算估算，实现后以 usage 实测校准。

## 0. 信号源（已在 events.jsonl 落盘的数据面）

| 信号 | 来源 | 质量 | 获取成本 |
|---|---|---|---|
| 编辑 diff | `edited_after_polish`（polished vs final） | 最高——用户对 requirement 应用方式的直接修正 | 免费（join 已产出） |
| 整体拒绝 | `reverted` | 负信号：requirement 错误或 scope 误判 | 免费 |
| 全盘接受 | `accepted_verbatim` | 正信号，强化用 | 免费 |
| 自然纠正 | `natural` 消息中的纠正/立规句式 | 显式 requirement 的主要来源（"不是让你总结，是要批判分析"／"以后都要X"） | 免费捕获，需预筛 |

## 1. 提取（extraction）

**原则：LLM 不看无信号的消息。** 两级流水：

1. **机械预筛（0 token，每条 submit 都跑）**
   - `edited_after_polish` / `reverted` → 直接进候选队列（带 diff 局部片段，截断 ~300 tokens）；
   - `natural` → 启发式命中才进队列：纠正/立规词面（"不是/别再/以后都/记住/要求/太长/太短/重新"等模式表 + 长度下限），并附带同 session 上一条 submit 作为上下文（各截 ~200 tokens）；
   - `accepted_verbatim` → 不进提取，走 §2 的机械强化。
2. **批量提取 call（write path call #1，haiku）**
   - 触发：候选攒满 **5 条**，或距最早候选 **30 分钟**（空闲冲刷），二者先到；
   - 输入：现有 active requirement 的**一行索引**（`id + ≤20 token 摘要`，cap 32 行 ≈ 700 (估)）+ 候选批 5×~300 + system ~600；
   - 输出 JSON：`[{kind: new|reinforce|contradict, target_id?, text, evidence}]`，requirement 文本用用户语言、单句、只写 how-the-task-is-done（anchor §3 判据进 prompt）；
   - **单次预算 ≈ 3–4k (估)**；均摊到轮 <800。

带索引摘要的意义：new/reinforce/contradict 的关系判定在同一个 call 内完成，多数情况不需要第二个 call。

## 2. 更新（CRUD / consolidation）

沿用 append-only 状态机，加两个字段：`strength: int`（默认 1）、`supersedes: id|null`。

**机械规则（0 token，即时执行）：**
- `accepted_verbatim` 且该轮 applied → 涉及条目 strength +1；
- `reverted` → 涉及条目 strength −1；
- strength ≤ −2 → 自动 retire（隐式退役，前端可见可复活）。

**提取结果落库：**
- `new` → ADD；
- `reinforce` → target strength +1、刷新 updated_at；
- `contradict` → SUPERSEDE：retire 旧条、ADD 新条并记 `supersedes`（历史可追溯，翻案=复活旧条）。

**整理 call（write path call #2，低频，haiku）：**
- 触发：active 条数 > 48，或累计 ADD 达 16 次；
- 输入：全库一行索引（≤48 行）+ system；输出合并/去重/改写 ops；
- **单次预算 ≈ 2–3k (估)**，频率低，均摊忽略。

## 3. 检索（recall，read path）

**阶段一（现状延续）：** active ≤ 32 条时全量送 translator，约 800 tokens——不过早优化。

**阶段二（条数超阈值后启用）：**
- **本地 embedding**（非生成式、不出机器）：multilingual 小模型（bge-m3 / multilingual-e5-small 级，Apple Silicon 单条 ~10ms），ADD/UPDATE 时增量入索引（存 data/，不进 git）；
- 打分：`cosine(query, req) × f(strength) × 新近度衰减` → top-12 进 prompt（~300 tokens）；
- **低分短路**：top-1 低于阈值 → 直接返回 noop，**0 生成式 call**——热键在无关场景更快更省（fallback 显式化：UI 仍提示"无适用 requirement"）。

热键轮 translator call：system ~500 + 召回 ~300 + 用户文本 ~200 + 输出 ~300 ≈ **1.3k (估)**（与 v0 实测量级一致）。

## 4. 每轮 token 账本

| 轮型 | 频率 | LLM 调用 | tokens (估) |
|---|---|---|---|
| 普通轮（hook 落盘+预筛） | 大多数 | 0 | 0 |
| 热键轮 | 用户触发 | translator ×1 | ~1.3k |
| 热键轮（低分短路） | 无关场景 | 0 | 0 |
| 提取轮（攒批到 5） | ~每 5–10 轮一次 | extraction ×1 | 3–4k |
| 整理轮 | 每 ~16 次 ADD | consolidation ×1 | 2–3k |
| **最坏单轮**（三者同轮撞上） | 罕见 | ≤3 | **~8.4k < 10k** |

## 5. 拍板点

1. **新提取的 requirement 入库方式**：(a) 自动入库（source=learned 标记，前端高亮"新学到"，随时退役；改写层还有人工兜底做双保险）｜(b) 进"待确认"区，用户点确认才生效（人在环更深，但增加摩擦）。**建议 (a)**，false requirement 的代价被编辑环节兜住，摩擦最小。
2. **embedding 选型**：(a) 本地小模型（推荐：零网络依赖、体感稳、符合全本地红线；代价是 ~100MB 模型下载 + 依赖组）｜(b) API embedding（voyage 等：无本地依赖，但每次热键多一跳网络，且本机代理闪断会波及）。**建议 (a)**。
3. **数值默认**（都可后调，先给：批=5、冲刷=30min、cap=32、整理阈值=48/16、隐退=strength≤−2、top-k=12）。

## 6. 与 anchor 的对齐

- write path 生成式 ≤2 call：extraction + consolidation，且都是批量/低频 ✓
- 编辑回流是一等信号（§0 表第一行）✓
- context 预算主动控制：一行索引、批处理、top-k、低分短路 ✓
- flash 档全覆盖；embedding 非生成式且本地 ✓
- 人在环不减：学到的条目全部前端可见、可编辑、可退役 ✓
