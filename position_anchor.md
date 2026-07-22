# Position Anchor — MemTranslator

> 2026-07-22。项目定位锚点。后续设计、原型、评测与 roadmap 若与本文冲突，以本文为准；`docs/idea.md` 等为历史文稿，可参考但不再单独定方向。

---

## 1. 项目定位

MemTranslator 首先是一个**开源产品/工具**，不是一篇论文的附属实现。

优先级：

1. **体验** — 用户在真实使用中是否感到「越来越懂我」
2. **可用与可维护** — 能装、能跑、能改、能贡献
3. **严谨性与学术创新** — 重要，但排在体验之后；不为刷榜或叙事新颖而牺牲产品形态

我们要做的只有一句话：

> **一个越来越懂用户的、位于用户与 agent 之间的 translator。**

用户提出任务时，风格与意图常常说不清或省略；translator 在请求进入下游 agent **之前**，把这些约束补进输入本身，让 agent 与用户更好协作。下游 agent 不需要读 memory，只执行润色后的请求。

---

## 2. 行为方式（钉死）

产品形态固定为两段，不随实验臂漂移。

### 2.1 Memory 的输入

- 观察用户**曾经明确表达过的 requirement**（纠正、反复强调、显式「以后都要…」等）。
- 收集进 memory，作为用户对 **agent 工作行为与输出** 的约束性喜好。
- 只记「希望任务 **怎么被完成**」，不记泛化的个人档案、事实百科、生活偏好清单。

### 2.2 运行时作用

- 交互形态对齐 Typeless 思路：**热键触发 + 聊天框内快速改写**。
- 润色结果落回输入框，用户可再编辑后发送；人在环是默认，不是可选项。
- 下游只看见用户确认后的文本；memory 不注入 agent 上下文。

---

## 3. 概念澄清：两类 preference 必须分开

| | **Agent delivery preference**（我们做的） | **Content / general preference**（我们不做主战场） |
|--|--|--|
| 含义 | 任务应 **如何被执行与交付** | 回答内容应 **推荐/避开什么** |
| 例子 | 「不要总结，要批判分析」「邮件写短」「直接给代码别解释」「以后论文都要比 related work」 | 「不吃麸质」「不喜欢像素风游戏」「怕高不订顶楼餐厅」 |
| 作用点 | 补全 **underspecified task** 里的风格与意图 | 个性化推荐 / persona 遵循 |
| 典型 bench | （自建 / 筛选的 delivery case） | PrefEval 大部分条目 |

PrefEval 一类数据里，绝大多数是 content preference。用它当主结论会把项目叙事拉偏成「通用偏好遵循」，与 §1、§6 不符。允许借用其中**少数**像 delivery 的 case，但不把 PrefEval 当作项目主 bench。

---

## 4. 真正需要试验与算法设计的地方

产品壳（§2.2）与「oracle memory 能否改写请求」可以先工程验证；**需要研究与迭代的算法主线只有一条：**

```
extraction → CRUD / consolidation → index & 入库 → 检索（recall）
```

约束与目标：

- **迅速、轻量**：一条 memory 的 extraction 路径 **最多 2 次 LLM call**（生成式）；embedding 等非生成式调用另计。
- **学习信号**：用户在 translator 改写之后、再次编辑发送的片段，必须能内化为监督信号（编辑 diff / 确认与否），回流进 write path——人在环不只是安全阀，也是数据。
- **Context 预算**：写入与召回都要主动控制进 LLM 的上下文长度（分批、压缩、只送相关旧记忆），体验与成本优先于「记得更全」。

不在本主线内的：训练专用 intent 模型、大规模知识图谱、通用 persona 档案、为刷榜堆复杂管线。

---

## 5. Backbone model

- **只允许 flash 档模型**（如 Haiku / 同级 flash）承担 translator 与 memory write path。
- **Recall / 热键触发的体感是第一优先级**：延迟、稳定性、可预期的改写幅度，优于极限准确率。
- 下游干活的 agent（Codex、Claude Code 等）可以是任意强模型；我们不替换它们，只改用户通道上的输入。

---

## 6. Motivation（钉死）

我们**不是**在做「记得更多、更全的 memory agent」。

对 Codex / Claude Code 这类**已经很强、专注于干活**的 agent：

- 不需要、也不应该把 memory 做成用户个人信息仓库；
- 只需要记住用户希望 **how the task is done** —— delivery preference / requirement；
- 价值在协作摩擦下降（少重复纠正、少风格跑偏），不在「全知用户画像」。

这是一个**小而清晰的空缺**：现有 general memory 系统什么都记；我们故意只记 requirement，并编译进请求。空缺小，所以产品体验与边界清晰比「全面」更重要。

---

## 7. General roadmap

| 版本 | 目标 |
|------|------|
| **v0** | 软件层先立住：§2.2 的热键 + 框内改写；memory 存储结构；用 **oracle requirement** 验证——给定正确 memory 时，translator 能稳定填充/修改请求。不追求真实提取质量。 |
| **v1** | 探索 memory 系统设计：extraction → CRUD → 入库 → 检索；编辑回流；在真实纠正信号上迭代。 |
| **v2** | Latency 与前端体验优化（flash 路径、缓存、交互细节）。 |

论文式严谨对照、创新性包装，服从上述版本节奏，不倒过来驱动产品。

---

## 8. Bench 态度

- 当前 **PrefEval 整体不适合**作为主评测；其中至多有一小部分 case 贴近 delivery preference，可挑着用。
- **不需要**很大、很严谨的学术 bench。自造、或从现有 bench **零散收集**符合叙事的 case，做**小规模**评测即可。
- 可与 Mem0、Zep 等做一次对照，但预期要清醒：若把 general memory 的 prompt/范围改成「只记 requirement + 同样改写协议」，数字可能接近——我们抓的是 §6 的**产品空缺与边界**，不是不可替代的榜单缺口。
- Bench 是**可量化的辅助指标**，不刷榜；出发点始终是 §1 的体验与开源可用性。

---

## 一句话回收

开源 translator：只记 how-the-task-is-done，热键在聊天框里补全风格与意图；算法力气花在轻量 memory 管线与编辑回流上；flash 体感优先；小 bench 够用，不拿 PrefEval 定生死。
