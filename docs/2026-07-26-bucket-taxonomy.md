# Requirement 分桶词表（定稿 v1）

> 2026-07-26 siriux 拍板:保留 `reasoning_policy` 与 `task_goal`,**删除 `domain_criteria`**,其余沿用提案。本文钉死六个桶的定义与判定顺序,供 extraction prompt、consolidation 分桶、Suite R 语料生成三处共用。
>
> 实证依据:224 条现有 bench requirement 的强制归桶(clean 73% / ambiguous 23% / unfittable 4%),歧义分布见 [taxonomy-verdict](2026-07-26-taxonomy-verdict.md)。本文的判定顺序就是针对那 51 条歧义设计的。

## 0. 为什么是有序判定,不是并列定义

七个并列定义在实测中产生 23% 歧义,且**歧义不是标注者的失误,是定义本身重叠**——`deliverables` 认领 "required sections"、`output_contract` 认领 "conclusion first",任何一条同时说"要有什么"和"排在哪"的规则,两个定义都完整覆盖它。

并列定义只能靠标注者的直觉破局,而直觉不可复现、不可写进 prompt。所以改为**有序判定**:从上往下问,**第一个命中的桶即为归属**,后面的不再考虑。歧义由优先级消解,而不是由判断力消解。

一句话不能同时归两个桶。如果它真的同时约束两件事,那是 **atomisation 问题**——先拆成两条,再各自归桶。

## 1. 判定顺序(六问,首次命中即止)

> 删掉这条规则,然后问:

| # | 问 | 命中 → 桶 |
|---|---|---|
| 1 | agent 会去做**另一件事**吗?(动词/产物类型变了) | **task_goal** |
| 2 | 做的事一样,但**下判断的标准或证据门槛**变了吗? | **reasoning_policy** |
| 3 | 标准一样,但答案里会**少掉一块信息**吗? | **deliverables** |
| 4 | 信息一样,只是**排布、渲染、长度、语言**变了吗? | **output_contract** |
| 5 | 渲染一样,只是**语域/对谁说话**变了吗? | **communication_style** |
| 6 | 与产物无关,是 agent **干活时怎么行动**吗?(工具、检索、先问还是先做、保真输入、发到哪) | **execution_policy** |

六问皆不中 → `unclassified`,不猜。`key` 字段留空,交给 consolidation 的 unkeyed 桶。

### 顺序的理由

1 在 2 之前:动词变了,标准的讨论就无意义(评估和展开是两件事,不是同一件事的两种标准)。
3 在 4 之前:这一刀专治 55% 的歧义源——**信息存在性优先于信息排布**。
6 垫底:`execution_policy` 是兜底桶,因为"怎么行动"最容易被泛化解释;把它放最后,防止它吸走本该归产物类的规则。

## 2. task_goal vs reasoning_policy —— 最难的那条线

siriux 给的两个例子内容几乎相同,碰撞就在这里:

| | 例子 | 为什么是这个桶 |
|---|---|---|
| task_goal | "Critically evaluate research ideas **rather than merely elaborate them**" | 点名了**活动之间的替换**:elaborate → evaluate。删掉它,agent 去做的是另一件事 |
| reasoning_policy | "Use critical analysis and **explicitly identify weaknesses**" | 活动仍是分析,只是规定了**分析必须达到的标准**(弱点必须被摆出来) |

判据落到判定顺序的第 1 问:**规则里有没有"不要 A,而要 B"这种活动替换?** 有 → task_goal;没有、只是给同一活动加标准 → reasoning_policy。

用户原话往往两者都沾,这时**拆成两条**:

```
"科研想法要判断 novelty 和可行性，不要只是顺着想法展开，而且要指出可能的问题"
  → task_goal:        评估科研想法的 novelty 与可行性，而不是顺着展开
  → reasoning_policy: 评估时必须显式指出想法的问题与风险
```

两条共享同一个 `evidence_id`,生命周期独立——用户以后说"这次不用挑毛病了"只会退役后者。

### task_goal 是"从哪个方面开展工作"

siriux 的原话。它改的是**任务动词与切入角度**:总结/解释/比较/批判/推荐/生成/修改;探索性讨论还是给结论;帮着把想法做大还是判断值不值得继续;优化还是诊断还是验证。

它**不是**输出风格。"分条分点"这种确定性的呈现方式一律进 `output_contract`,哪怕它听起来也像"怎么开展工作"。

```
"调研类问题先给结论再给依据"    → output_contract（信息都在，只是顺序）
"调研类问题要给出可执行的建议，不要只罗列现状"  → task_goal（产物类型变了）
```

### reasoning_policy 覆盖面

批判性还是支持性;要不要核实事实;是否优先原始文献/官方文档而非二手;是否区分事实、推断与猜测;是否比较多种解释;不确定性怎么处理;是否反驳用户的假设;对 novelty、风险、因果的判断门槛。

## 3. 已删除:domain_criteria

**删除理由(siriux 2026-07-26 拍板)**:该桶在实证中命中 6 条,其中至少 2 条("只在工作日安排会议""周二上午 10 点开团队会")正是 anchor §3 明令不存的**内容偏好**,也正是 Suite L 的 `noise-reject-content` 类别判为**失败**的东西。保留它等于让产品从"交付偏好翻译器"漂移成"通用偏好记忆",并使 L 的 6 个 case 自相矛盾。

原本落在该桶的少数**确实是交付约束**的规则(如"写代码用 TypeScript"),按判定顺序自然落入 `output_contract`(第 4 问:产物形态)或 `execution_policy`(第 6 问:用什么工具/技术路线)。不为它们单开桶。

## 4. 六个桶之外的正交属性

桶回答"这条规则改请求的哪一部分";下列字段回答"它什么时候适用、多硬、怎么来的、现在还算不算数"。

| 字段 | 取值 | 说明 |
|---|---|---|
| `scope` | `{app?, task?, lang?}` | 沿用现状,确定性过滤用;缺省 global |
| `binding` | `hard` / `soft` / `default` / `suggestion` | **新增**。约束力。注意与现有 `strength` 区分 |
| `strength` | int | **沿用现状,不改语义**。它是证据计数器(accepted +1 / reverted −1),不是约束力 |
| `polarity` | `require` / `prefer` / `avoid` / `prohibit` | **新增**。`avoid` 容例外,`prohibit` 不容 |
| `salience` | 1–5 | 沿用现状,提取期置信度 |
| `evidence_id` | str | **新增**。同一句用户原话拆出的多条共享此 id,生命周期各自独立 |
| `source` | `manual` / `learned` | 沿用现状 |
| `status` | `active` / `retired` | **沿用二值**,不采纳 7 值方案(见 verdict §4.3) |

命名冲突已处理:提案的 `strength` 枚举改名 **`binding`**,现有整数计数器 `strength` 不动——两者语义正交,一个是"用户多坚持",一个是"证据多充分"。

`kind: style_rule` 与六个桶**正交,不是第七个桶**:桶约束下游 agent 该怎么做事,`style_rule` 约束**我们自己的改写**该怎么措辞。收件人不同,不是抽象层级不同。

## 5. 落地清单

1. `schema.py`:`Requirement` 加 `bucket`、`binding`、`polarity`、`evidence_id`,全部有默认值,v1 记录零迁移即可加载。
2. `extraction.py`:六问判定顺序进 system prompt;输出 schema 加 `bucket`/`polarity`;要求一句话多约束时拆多条并共享 `evidence_id`。
3. `consolidate.py`:分桶主键从"`key` 精确 → 前缀"改为"`bucket` + `key` 精确 → `bucket` 前缀 → 同 `bucket` 未分类",跨桶不合并。
4. Suite R 语料生成:672 条按桶分层,配额见 §6。
5. 六问判定顺序**同时**用于生成端与判分端,保证语料标注与产品理解同源。

## 6. 生成配额(Suite R,12 scenario × 56 constraint)

按实证分布 + 两个薄桶的补足需求定:

| 桶 | 占比 | 条数 | 语料来源 |
|---|---|---|---|
| output_contract | 30% | ~200 | WildIFEval、IFEval 系、Google/GOV.UK 风格指南 |
| deliverables | 18% | ~120 | WildIFEval、Google devdocs |
| execution_policy | 15% | ~100 | Conventional Commits、工程规范、渠道/工具类 |
| **reasoning_policy** | **15%** | **~100** | **待定,见 sourcing 工作流** |
| communication_style | 12% | ~80 | 风格指南、PRISM 人写字段 |
| **task_goal** | **10%** | **~70** | **待定,见 sourcing 工作流** |

两个薄桶合计 25%(~170 条)。现有已清许可的语料**供不出这两桶**——它们几乎全是输出形态类,所以另起一轮 sourcing(同行评审指南、方法学标准、代码评审规范、事实核查准则、任务分类语料)。缺口如补不足,配额下调并如实记录,不靠改写现有 output 类条目凑数。
