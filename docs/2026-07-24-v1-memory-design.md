# v1 Memory 系统设计（定稿）

> **实现状态（2026-07-24 深夜）**：M0–M6 全部落地（dev 分支），116 测试绿，真机冒烟通过（translate 注入 + submit 预筛入队 + lazy flush 环路 live）。bench 验收：L v1 0.852–0.926（四轮全部超 reference 0.833 且过 gate 0.70）；E v1 0.125–0.375（未过 gate——16 轮链式结构放大单点学歪，run 间方差 ±0.2，宽度锚定修复已在插桩重放中机制级验证；E 计分协议改进为 open item，待 siriux 拍板）。gate overall FAIL（E 短板），按拍板 ③ 属实陈述。三轮实证驱动的设计修正已回写：编号候选协议未出一次 id 错、宽度锚定（用户原话=规则宽度 + 同族证据 contradict 拓宽）、L 判分 gist 等价窄 context 化。

> 2026-07-24。基于 [2026-07-23-memory-pipeline-proposal.md](2026-07-23-memory-pipeline-proposal.md) 与 [2026-07-23-signal-algorithms-proposal.md](2026-07-23-signal-algorithms-proposal.md) 修订定稿；两份 proposal 的内容除本文列出的**修订**外全部继承，细节以 proposal 为准、冲突以本文为准。
>
> **siriux 拍定的两条底线（2026-07-24）：**
> ① **不引入任何额外 API 或模型**——生成式调用只走产品 flash 通道（`MODELS["translator"]`，claude-haiku-4-5）；无 embedding（本地或 API）、无第二家模型。
> ② **禁止对 bench 做 heuristic / overfit 优化**——bench 只做验收，见 §8 评测纪律。
>
> 其余设计决策 siriux 已全权委托，本文直接定稿（每项带理由），不再留拍板点。

## 1. 对 proposal 的修订清单

| # | proposal 原文 | 修订 | 理由 |
|---|---|---|---|
| R1 | pipeline §3 阶段二：本地 embedding 检索 + 低分短路；拍板点 2 embedding 选型 | **整体删除**。规模化路径唯一化为 signal §2.5 符号层：scope 确定性过滤 → key 词面排序 → cap | 底线 ①；且量级几十条，符号层已够（SimpleMem 的向量层是为万级记忆设计的） |
| R2 | signal §1 预筛"可选增强：本地小 embedding 原型句相似度（plan B）" | 删除 | 底线 ① |
| R3 | signal §1 match-judge"LLM 失败→向量最近邻 0.45 兜底" | 删除；同时**砍掉整个灰区 match-judge 第二跳**（signal 拍板点 3 选 (b)） | 底线 ① 砍掉了它的兜底路；更重要：bench 实证 flash 模型裸抄 id 会错（L-173706 supersede 类唯一 fail），少一个 id 引用场景 = 少一类错误。灰区一律 ADD，留给 consolidation 桶内收拾——错误可修复且低频 call 更稳 |
| R4 | pipeline 拍板点 1：入库方式 | 定 **(a) 自动入库**，`source: learned` 标记、前端高亮、可退役 | proposal 建议 + Cursor Memories 教训（逐条人审没立住）；false positive 由改写层人在环兜底 |
| R5 | pipeline/signal 数值拍板点 | 全按默认定稿：批 N=8、空闲冲刷 30min、RECALL_CAP=32、整理触发 active>48 或累计 ADD≥16、隐退 strength≤−2、style_rule≤10 条 | proposal 给的默认即中值；全部进 `config.py` 单点可调，实测后再动 |
| R6 | 两个 call 的目标条目引用（extraction 的 target_id、consolidation 的 target_ids） | **编号候选协议**：prompt 里现有条目以 `[1] [2] …` 编号呈现，LLM 输出**编号**，代码层换算回 id；越界/非整数编号丢弃该 op 并计入 `parse_flags` | bench 实证（同 R3）：8 位 hex 裸抄对 flash 不鲁棒。这是真实系统鲁棒性设计，非 bench 定向优化——它对任何输入都成立 |
| R7 | signal §2 B2 的 `reverted` 进批判"收窄还是退役" | 保留,但输出协议并入 extraction 统一 op 集（`contradict`=收窄改写 / `retire`=退役） | 与 bench op 词表对齐（new/reinforce/contradict/retire/merge），一套词表贯穿产品与评测 |

## 2. 模块与文件布局

```
src/memtranslator/
  schema.py        # Requirement 扩展（§3）——改
  store.py         # append-only 状态机 + 机械 strength 规则（§3）——改
  signals.py       # 新：B1 span 归因 + A 路句级预筛（§4）
  extraction.py    # 新：call #1——A+B 合批提取/归因（§5）
  consolidate.py   # 新：call #2——桶内去重/合并/style 策展（§6）
  pipeline.py      # 新：触发器（批满/空闲冲刷/整理阈值）+ 落库执行器
  recall.py        # 新：scope 过滤 + cap（从 translate.recall 抽出并扩展，§7）
  translate.py     # style_rule 注入点（≤250t）——小改
  llm.py / config.py  # 不动 / 数值与词表单点
bench/runner/providers.py  # 增 V1Provider 适配器（§9）——bench merge 进 dev 后
```

## 3. Schema 与状态机（继承 pipeline §2 + signal §2.5，汇总）

```python
Requirement = {
  text, id, status: active|retired,
  kind: "requirement" | "style_rule",          # signal §2-B2 修订：同库同状态机
  key: "facet.attribute",                       # 受控两段式，词表引导+允许新造
  scope: {app?: str, task?: str, lang?: str},   # 缺省 global；确定性过滤用
  strength: int = 1, salience: int,             # 机械层/提取层各自维护
  supersedes: id|None, source: "manual"|"learned",
  created_at, updated_at,
}
```

机械规则（0 token，store 层即时执行,不进任何 LLM）：
`accepted_verbatim` 且 applied → strength+1；`reverted` → strength−1；strength≤−2 → 自动 retire。
落库映射：`new`→ADD；`reinforce`→strength+1 + touch；`contradict`→SUPERSEDE（retire 旧 + ADD 新 + 记 supersedes）；`retire`→retire；`merge`→retire 全部 targets + ADD 合并条（supersedes 记首个 target）。

## 4. 信号层 `signals.py`（继承 signal §1 预筛 + §2 B1，无修订）

- **B1 机械 span 归因**：difflib opcodes 求 `Δ_inject=diff(raw,polished)` 与 `Δ_edit=diff(polished,final)` 重叠 → 每条 applied requirement 判 kept/touched/removed；kept/removed 即时驱动 strength，touched 与 diff 三元组进候选批。
- **A 路句级预筛**：分块（材料区 vs 话语区）→ 句级特征打分（纠正/立规词表 + meta-discourse 词 + 祈使 + 二人称 + 位置 + 已有 key 词面命中）→ top-k span ±1 句、单轮 ≤600t。无句过阈 → 不入批。
- **词表来源纪律（底线 ②）**：词表与特征权重只从 proposal 原文、v0 events 实录和通用语言现象构造；**禁止**从 bench case 文本反向摘词。词表文件头部注明来源。

## 5. Extraction call `extraction.py`（合并 pipeline §1 与 signal §1/§2-B2 为单一 call）

一个 call 同时消化两路候选（A 路 span + B 路 diff 三元组），把 proposal 中 A 提取与 B2 归因合并——同批同 prompt 分节呈现，输出统一 op 集：

- 输入：system（含 anchor §3 判据、HMS 纪律、salience 门）+ 现有 active 条目**编号索引**（`[n] key | text≤20t`，cap 48 行）+ A 节候选 span + B 节 (raw, polished, final, applied 摘要, B1 span 标注)。
- 输出（JSON array）：`{op: new|reinforce|contradict|retire, target: int|null, text?, key?, scope?, salience, evidence: "quote"}`，外加 B 路专属 `{op: style_rule, text}` 与逐 diff verdict（misapplied 计数驱动 SUPERSEDE 收窄,signal §2-B2 落库规则不变）。
- salience<3 丢弃;编号越界丢弃并 flag(R6)。
- 触发（pipeline.py）：候选满 N=8 或最早候选 30min，二者先到。预算 ~3–5k/次。

## 6. Consolidation call `consolidate.py`（继承 pipeline §2 + signal §2.5 分桶）

- 触发：active>48 或累计 ADD≥16。
- 先机械分桶（key 精确→前缀），**只有同桶 ≥2 条才进 prompt**（多数触发轮 0 call 即返回）；桶内编号呈现，输出 `merge`/改写 ops + style_rule 策展剪枝（≤10 条上限）。
- 预算 ~2–3k/次，低频。

## 7. Recall `recall.py`（R1 修订后的唯一路径）

1. status=active 且 kind=requirement（style_rule 不参与 scope 检索，仅 translate 组装时注入）；
2. scope 确定性过滤：app/task/lang 与当前上下文规则匹配（0 LLM）；
3. ≤RECALL_CAP(32) 全量注入（现状延续）；超过时 key 词面命中排序 + 新近度取 cap。
无 embedding、无低分短路——热键轮恒定 1 次 translator call（v0 行为不回退）。

## 8. 评测纪律（底线 ② 的操作化）

1. 全部 prompt、词表、阈值从 proposal / 产品需求 / v0 实录推导；开发期**不打开** `bench/cases/*.jsonl` 对照调参。
2. bench 只在**类别聚合层**读结果（category rate）；单 case 输出仅用于定位 harness bug 或确认能力缺陷方向,禁止据此改词表/加分支。
3. 任何"为了过某类 case"的规则若不能陈述为**产品级通用需求**（对任意用户输入成立），不得进入 src/。
4. 迭代循环：改 src → 跑 L/E → 只看类别分与 parse_flags → 回到 proposal 层面找结构性改进。
5. 违反判据：diff 里出现与 bench case 文本的字面耦合（关键词、专有实体、阈值数字反推）即 review 打回。

## 9. 与 bench 的接口

bench merge 进 dev 后，`providers.py` 增：

```python
class V1Provider:            # 薄适配器：无触发器（触发器归 pipeline.py 的 daemon 面）
    def extract(self, events, existing):     # bench 直接喂批 → signals 预筛照跑 → extraction call
    def consolidate(self, existing):         # 直接进桶内整理
```

被测面 = 真实产品路径（signals→extraction→ops），仅剥离时间触发器。验收：L ≥0.70 且 E ≥0.70 进 gate；要击败的基线 L 0.833 / E 0.500。

## 10. Token 账本（R1/R3 修订后）

| 轮型 | LLM 调用 | tokens (估) |
|---|---|---|
| 普通轮 | 0 | 0 |
| 热键轮（translator + style_rule ≤250t） | 1 | ~1.6k |
| 提取轮（A+B 合批，每 ~8 信号轮） | 1 | 3–5k |
| 整理轮（低频，先机械分桶） | ≤1 | 2–3k |
| 最坏单轮全撞 | ≤3 | **~8.6k < 10k** ✓ |

灰区第二跳砍除后,write path 生成式 ≤2 call/轮型恒成立（anchor §4 ✓）。

## 11. 实现分解（TDD，dev 分支）

- **M0** schema/store 扩展 + 机械 strength 规则（纯单测，FakeLLM 不需要）
- **M1** signals.py：B1 span 归因 + A 路预筛（纯机械，单测密集——这是 0-token 层的正确性根基）
- **M2** extraction.py + pipeline.py 触发器（FakeLLM 单测 + 编号协议边界测试）
- **M3** consolidate.py + 分桶（同上）
- **M4** recall.py + translate 的 style_rule 注入（v0 行为回归测试保绿）
- **M5** bench merge 进 dev + V1Provider + 首跑 L/E 真分，水位进 bench/README
- **M6** hook/daemon 接线（events.jsonl → pipeline 触发器）+ 真机冒烟

每个 M 一个 commit 系列,M5 出分后按 §8 纪律迭代。
