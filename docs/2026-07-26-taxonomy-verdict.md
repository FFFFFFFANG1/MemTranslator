以下是 verdict 文档本体。

---

# Taxonomy 提案裁决书

日期 2026-07-26 · 依据 dev @ `ccbfb7a` · 实证样本 114 个 bench case + 8 个 persona

## 0. 一句话结论

**7 个桶本身可用，但按现在的定义不可实施：三对边界是写进定义里的重复，两个桶（`task_goal`、`reasoning_policy`）在 224 条真实 requirement 上拿到 0 条无歧义命中，`domain_criteria` 与 anchor §3 正面冲突；把它作为 store 的 schema 字段值得做，作为 translation IR 现在不值得做。**

| 提案条目 | 裁决 | 一句话理由 |
|---|---|---|
| 7 桶作为 store 的受控词表 | **修改后采纳** | 桶作为新字段 `bucket`，与 `key` 并列；`key` **不**改成 `bucket.attribute`（§2、§4） |
| 三对桶边界的定义 | **修改** | 6 条判据必须写进定义再交给任何 classifier，否则 51 条歧义里 43 条无解（§1） |
| `domain_criteria` | **修改 + 需 owner 拍板** | 定义里「饮食/价格/位置限制」正是 anchor §3 明令排除的类；收窄为 actor+source 双条件并改名 `work_constraints`（§3.3、Q1） |
| atomisation（一句话拆多条） | **采纳** | 9 条字符串不拆无法归桶，另 ~13 条拆后才干净；且 `l-diff-001` 的 gold 本身就是反例（§2.3） |
| polarity 作为 attribute、不设 `constraints` 桶 | **采纳** | ~40 条否定式字符串全部自然落入语义桶，无一需要极性桶（§2.2） |
| `strength` 枚举（hard/soft/…） | **修改** | 与现有整数计数器撞名；枚举改叫 `binding`，整数不动（§4.2） |
| 7 值 `status` | **拒绝** | 把 recall 谓词和审计轨迹混成一个字段，9 处调用点要各自学会哪些值可召回；改为二值 + `retire_reason`（§4.3） |
| `persistence` 字段 | **拒绝** | 三个取值全部可由 `salience`/`strength`/`scope` 推出，append-only 日志里存第四份必然过期（§4.3） |
| `kind: style_rule` 与桶正交 | **采纳** | 理由不是「抽象层级不同」而是**收件人不同**：桶约束下游 agent，style_rule 约束我们自己的改写（§4.4） |
| buckets as translation IR | **拒绝（现阶段）** | 它瞄准的三个靶子，一个是 bench 标注错、一个已被 `preserves_request` 更强覆盖、第三个它会让情况变坏（§5） |
| 三篇论文作为立论依据 | **拒绝 2 篇、降格 1 篇** | 全部未过 ICML/ICLR/NeurIPS 门槛；其中 2 篇被用来支持它们并不支持的主张（§6） |

---

## 1. 实证检验结果

### 1.1 口径与方法学警告（先说，因为它决定了下面数字能承多重）

样本 = `bench/cases/translate/cases.jsonl`（60 case）+ `bench/cases/extraction/cases.jsonl`（54 case）+ 8 个 persona，共 **224 条 requirement 字符串**。

三点必须先声明，否则数字会被高估：

1. **口径不一致。** T 语料按 unique string 计（88，去掉 8 条重复），L 语料按 occurrence 计（95，其中 90 unique），E 语料按字符串计（41）。合计 224 里有约 13 条是跨语料的同义重复（`"代码类回答只给代码，不要解释。"` 一条就在三个语料里各出现一次）。
2. **单标注者、强制单选。** 没有第二个标注者，所以「歧义率」是标注者自陈的，不是由标注分歧测出来的。真实分歧率大概率更高。
3. **这是人类标注者手里拿着定义的成绩，不是 flash 的成绩。** 73% clean 是 classifier 准确率的上界，不是预期值。

### 1.2 三个桶吃掉一半，两个桶吃到 0

| bucket | 强制归桶（n=215） | 无歧义（clean） |
|---|---|---|
| `output_contract` | 104（48%） | 42 + 19 + ~n/a(T 未分列) |
| `deliverables` | 45 | 4 + 6 |
| `execution_policy` | 27 | 21 + 1 |
| `communication_style` | 25 | 5 + 2 |
| `domain_criteria` | 6 | 5 + 1 |
| `reasoning_policy` | 6 | **0** |
| `task_goal` | 2 | **0** |
| 无法归桶 | 9 | — |

clean / ambiguous / unfittable = **164 / 51 / 9**（73% / 23% / 4%）。分语料：T 60/25/3（68%），L 77/16/2（81%），E 27/10/4（66%）。

三个数字值得单独盯着看：

- **`task_goal` 和 `reasoning_policy` 在 224 条上各拿到 0 条无歧义命中。** 唯一碰到它们的 6 条字符串，每一条都同时落在另一个桶里。这不能证明这两个桶是错的——L 是格式与 ops 规则集，T 是 delivery 集，E 的 8 个 persona 全是单轮 delivery 型——但它确实意味着：**7 桶方案在现有全部证据上从未被验证过，实测到的是一个 4-5 桶方案，且其中一个桶吃掉近一半。**
- **`output_contract` 48% 的占比是它定义太宽的直接后果**，不是数据性质。把「序列化」以外的东西（信息存在性、输入保真、语法表面）从它身上剥走之后，它会缩回到一个合理体量。
- **`domain_criteria` 的 6 条命中里，5 条来自 L，且其中至少 2 条（「只在工作日安排会议」「周二上午 10 点开团队会」）是 anchor §3 明令 store 不该持有的内容偏好。** 详见 §3.3。

### 1.3 六对边界，51 条歧义的全部来源

按触及数据量排序。每条给「现在为什么分不开」+「改成什么判据能分干净」，判据必须写进桶定义本身，不能靠标注者的直觉。

**(1) `deliverables` ↔ `output_contract` —— 28/51 条歧义（55%），压倒性第一。**

根因写在提案自己的文字里：`deliverables` 认领「required sections」，`output_contract` 认领「heading levels / conclusion first / bullets」。任何一条同时点名「哪个成分」和「它在哪/长什么样」的规则，两个定义都完整覆盖。真实字符串：

- `"Start with a summary"` / `"End with overall assessment"`（t-noop-007）
- `"Start every email with a greeting and end with a signature."`（t-lang-009）
- `"For code reviews, point out style issues first"`（t-noop-007）/ `"PR review 的时候先列风格问题，再说逻辑问题。"`（t-noop-004）
- `"Numbers in reports must carry units."` / `"报告里的数字要标上单位"`（L，3 次）
- `"include deadlines in parentheses for action items"`、`"Always include timestamps in logs."`
- `"长文档开头要带一个目录"`（writer-zh req[2]）
- `"代码类回答只给代码，不要解释。"`（跨三个语料，共 8 次出现）

**判据 D1（存在性 vs 排布）：删掉这条规则，答案里会不会少掉一块信息？会 → `deliverables`；信息还在、只是换个渲染或顺序 → `output_contract`。**

代入：「先列风格问题」= 排布 → OUT；「include a subject line」= 信息缺失 → DELIV；「目录」是从既有内容派生出来的导航 → OUT；「action items with owners and due dates」引入新承诺 → DELIV；「数字要带单位」单位是信息 → DELIV；「用括号标 deadline」是记法 → OUT。同时断言两者的字符串（`"研究结果用表格形式呈现，包括方法、结果和局限性。"`）必须拆成两条。

这条判据能用，但**它不可能从现在的桶描述里推导出来**——今天的归桶结果取决于「code」这个词碰巧出现在哪个定义的例子列表里。必须带上上面这组 worked example 一起写进 prompt。

**(2) `execution_policy` ↔ `output_contract` —— preserve-long 全家（5 条歧义 + 2 条不可归桶）。**

提案把 "preserve the original input" 放在 `execution_policy`，把 "preserve original structure" 放在 `output_contract`——**这是同一条规则写了两遍**。涉及：`"Pasted code blocks must be kept verbatim in any rewrite."`、`"Preserve all URLs exactly, do not shorten or change."`、`"Keep all speaker names and quotes verbatim."`、`"Keep all citations and quoted text exactly as is."`、`"Keep all step numbers and code blocks unchanged."`

**判据 D2（脱离输入可验证吗）：验证合规需要拿输出去比对用户的原文 → `execution_policy`（输入保真）；只看输出就能验 → `output_contract`。**

整族路由到 EXEC，OUT 变成纯粹的输出形态桶。这一条不是洁癖：preserve-long 是 T 里最弱的类别（0.40），而 taxonomy 原样复制了系统正在失败的那个混淆——「别重写我的输入」（过程）vs「结果该长这样」（形态）。不过要注意 §5 的实测结论：那 0.40 有 60% 是标注缺陷，判据 D2 解决的是分类一致性，不是那个分数。

**(3) `communication_style` ↔ `output_contract` —— 5 条。**

`"Use imperative mood."`、`"Use past tense."`、`"Technical descriptions must avoid first-person pronouns."`、`"Commit messages must not contain emojis."`、`"别复述我的问题，直接答"`。既不是 register/audience，也不是长度/格式。

**判据 D3（是否随读者变化）：规则点名的是读者能感知的语域（正式度、温度、行话水平、受众专业度）→ `communication_style`；是与读者无关的、机械可验的表面属性（时态、语气、人称、emoji 禁令、缩进）→ `output_contract`。**

同时**必须从 `communication_style` 的描述里删掉 "avoid padding"**——它是结构属性不是语域属性，`"别复述我的问题"` 的三向歧义就是它造成的。删掉之后 `communication_style` 收缩成纯 tone 桶，在 E 语料里只剩两条干净成员（`"No corporate jargon in anything written for the team"`、`"邮件语气要坚定专业，别软绵绵的"`），定义反而清晰了。

**(4) `task_goal` ↔ `reasoning_policy` ↔ `deliverables` —— 8 条，且它是唯一触及 taxonomy 上半部分的一族。**

这一对是**定义层面的自相矛盾**：`task_goal` 的例子列表里有 "critique"，`reasoning_policy` 的定义开头就是 "critical vs supportive"。所以 `"分析论文要批判性的，指出方法弱点，别光夸"`（researcher-zh req[0] 及其 correction）和 `"paper analysis should be critical, not praise or plain summary"`（l-corr-001）按构造就在两个桶里。

**判据 D4：`task_goal` 只在规则改变用户拿到的**产物类型**时触发（要一份 critique 而不是一份 summary）；`reasoning_policy` 管产物类型不变时所用的**判断/证据标准**；点名某个必须出现的维度或章节 → `deliverables`。并且必须从两个描述之一里划掉 "critical/critique"。**

代入：`"code review should focus on logic and correctness, not typos"` = 同一活动的覆盖子集 → DELIV（不是 GOAL）；`"分析论文要批判性的，指出方法弱点"` = 2 个原子（批判性 → REAS，指出弱点 → DELIV）；`"Focus on constructive feedback, not criticism."` = 措辞方式 → STYLE。按这条判据走完，`reasoning_policy` 在三个语料里归零。这是判据的代价，也是它的诚实之处。

**(5) `deliverables` ↔ `reasoning_policy`（引用族）—— 4 条。**

`"Cite sources for any factual claims, excluding common knowledge"`、`"调研类问题要求给出至少两个信息来源。"`、`"引用别人的观点或数据要给出处"` 及其 correction。"citations" 这个词同时出现在三个桶的定义里（deliverables 的 "whether citations are needed"、reasoning_policy 的证据标准、output_contract 的 "citation format"）。

**判据 D5（收集 vs 展示 vs 形式）：对 agent 必须**去获取/核实**的证据设门槛 → `reasoning_policy`；要求证据必须**被展示** → `deliverables`；规定出处的**呈现形式**（链接、脚注、bibtex）→ `output_contract`。**

`"至少两个信息来源"` 由此暴露为拆分案例：收集 ≥2 源 = REAS，展示出来 = DELIV。

**(6) 两处无家可归。**

- **artifact 内部的技术约定。** `"When writing code, use TypeScript."` 是干净的 `domain_criteria`（技术路线），但 `"Python 代码一律带 type hints。"` 不是路线、不是格式、不是成分，哪儿都不合适。要么把 `domain_criteria` 拓宽到 artifact-internal 技术约定，要么在 `output_contract` 下开一个 code_conventions 子面。放着不管，每条代码风格规则都会被分得不一致。
- **交付路由。** 5 条 L 字符串——`"always CC manager on project update emails"`、`"Send all notification emails to my personal inbox."`、`"send notifications to Slack instead of email"`、`"All emails should be sent using SMTP."`、`"Send notifications via Slack."`——讲的是渠道、传输和收件人。7 个桶没有一个提到 recipient 或 channel，它们被塞进 `execution_policy`（因为「用哪些工具」最接近），悄悄把 EXEC 的占比抬高了。要么在 EXEC 描述里显式写上 channel/recipient/transport，要么承认一个 routing 子面。

  附带的时间约束判据 **D7：对 agent 自身动作的时限（"2 小时内回复"、"周五才 deploy"）= `execution_policy`；对被安排/被推荐的对象的时限（"周二上午 10 点开会"）= `domain_criteria`。** 这条在 9 条带时间的字符串上全部成立，但必须明写。

### 1.4 横切结论：atomisation 必须先于 classification

9 条字符串在拆分前不可能归任何单一桶，另有约 13 条拆分后才变干净。三条最硬的证据：

- `"研究结果用表格形式呈现，包括方法、结果和局限性。"`（t-single-010）——两半分属 OUT 和 DELIV，且必须有独立生命周期：日后一句「这次不要表格」不能顺手杀掉覆盖度要求。
- E 语料 4 条 unfittable 全是 `natural_correction`，而**它们各自的 persona 文件本身就用 `applicable:[0,2]` / `[0,1,2]` / `[0,1]` 记录了它们是 2–3 条独立 requirement**。bench 自己的 ground truth 已经站在 atomisation 这边。
- 反向的铁证：`l-diff-001` 的 gold 期望把 `"emails to the landlord in English, with a firm tone"` 存成**一条**。按提案这必须是两条。**这条 gold 是错的，且不改它的话，L 分数会惩罚正确的 atomisation。**

同样重要的是：atomisation 与桶设计**正交**。E 语料另有 3 条字符串在同一个桶内部捆了多个可独立撤销的原子（`"commit message 用英文，一两句话，不要 bullet"` 三个原子全在 OUT）。所以桶覆盖率永远无法验证 atomisation 这个主张，反过来也一样——两件事要分开立项、分开度量。

### 1.5 这份语料**不能**证明什么

- 不能证明 7 桶比 5 桶好。上半部分（GOAL/REAS）零无歧义命中。
- 不能证明桶能提升 recall 或 apply 精度。语料只测了「一条字符串能不能被归类」，没测「归类之后系统是否表现更好」。
- 不能证明 flash 能执行这套判据。全部标注是人做的。

---

## 2. 相对现状明确更好的地方

这一节逐条对上 `src/memtranslator/schema.py` 与 `consolidate.py` / `recall.py` 的**具体**缺陷，不讲抽象好处。

### 2.1 `key` 是自由文本，没有受控词表，dedup 因此漏

现状：`key: str = ""  # facet key "facet.attribute"` 完全由模型自由生成。`consolidate.py` 的分组靠 exact key + head prefix。语料里真实出现过 `format.output` 和 `output.format` 两种写法指同一件事；`"Response must be in JSON format only."` 与 `"Only return JSON, no other format."` 今天合不了。

桶带来的改进是**具体的、可验的**：`bucket` 是 7 值闭枚举，flash 打这种字段的稳定性远高于自由字符串；分组身份从 `key` 变成 `(bucket, key)` 之后，`email.length` 与 `email.tone` 在落到 OUT vs STYLE 时不再互撞——今天它们共享 head prefix，会被 consolidate 分到同一组。

同时它开启一个今天**表达不出来的错误类别**：跨桶 merge 应当被机械拒绝。`merge_allowed()` 里一行 `len({t.bucket for t in targets if t.bucket}) > 1 → reject`，就把 `l-diff-001` 那个失败（English + firm tone 被融成一条）变成不可表示。今天的 schema 里没有任何字段能承载这个判断。

### 2.2 现状没有 polarity 字段，否定性只活在 text 里

224 条里约 40 条带否定（`不要解释`、`别列点`、`别光夸`、`No corporate jargon`、`do not shorten`）。今天它们与肯定规则在 schema 上完全同形，`consolidate` 无法识别「一条 avoid 和一条 require 指向同一 key」这种真冲突。

而且数据支持提案的一个具体设计选择：**这 40 条没有一条需要一个 `constraints` 桶**——极性作为 attribute 处理，每条都自然落进语义桶。这个「polarity 不是维度」的判断被实证确认了，值得单独记一笔，因为它是提案里少数被数据正面支持的结构主张之一。

### 2.3 现状无法表达也无法评测 atomisation

没有 `evidence_id`，就没有办法说「这 3 条来自同一句话，但生命周期独立」。后果有三个，都是当下真实存在的：

- consolidate 可以在提取两小时后把刚拆开的原子重新融回去，没有任何机制阻止。
- review UI 无法告诉用户「你说了一句话，它变成了 3 条规则」。
- bench 无法把 `l-diff-001` 这类 case 评成「是否产出 2 条」——现在的 gold 只能表达「产出 1 条」，也就是**评测框架把正确行为定义成了错误**。

### 2.4 `recall.py` 里 scope 只做过滤、不参与排序，「更窄的规则优先」根本不存在

现状 `_scope_ok` 是纯布尔过滤，排序只在超过 `RECALL_CAP = 32` 时才靠 `_key_hits_query` 切一刀。也就是说：`{task:"email"}` 的「邮件 120 词」和全局的「回答尽量详细」同时召回时，谁也不压谁，冲突留给 translator 在散文里自己化解。

有了 `(bucket, key)` 家族之后，shadowing 才有落点：同一 `(bucket, key)` 内，scope 严格更窄者压制更宽者。这是一个**确定性的、零 LLM 的**语义改进，且在任何 store 体量下都生效（不像现在的排序只在 >32 条时才启动）。

### 2.5 `salience` 一个字段扛了两件事

现状 `salience: int = 3  # extraction-layer score` 同时被当作「用户说得多明确」和「这条有多硬」在用，`SALIENCE_MIN = 3` 是写入闸门。提案的 polarity/binding 把「用户陈述的强制度」拆出来是对的：`salience` 是**我们对听清了没有的置信度**，`binding` 是**用户声明的强硬度**，两者不同源、不同用途。这个区分今天没有。

---

## 3. 有真问题的地方

### 3.1 三对边界是定义层面的重复，不是使用层面的模糊

见 §1.3(1)(2)(4)。区别在于：使用层面的模糊靠更多例子能缓解，定义层面的重复靠例子只会更糟。`task_goal` 里有 "critique" 且 `reasoning_policy` 里有 "critical vs supportive"，这不是标注者水平问题，是**同一个概念被写进了两个桶**。必须删字，不是加字。

### 3.2 覆盖失衡使 7 桶主张在现有全部证据上不可证伪

0 clean / 224。同时承载全部负载的三个桶，恰恰是相互边界最差的三个。这不构成「砍掉上半部分」的理由（数据是 delivery-heavy 的，属性使然），但它构成一条硬纪律：**在 672 条扩容语料里为 GOAL/DOM/REAS 设定最低配额之前，不得声称 7 桶设计已被验证。** 建议阈值：每桶 ≥15 条无歧义命中，否则该桶降级为「保留枚举值但不纳入任何评分维度」。

### 3.3 `domain_criteria` 与 anchor 的定位冲突（本节最重要）

**冲突是真的，而且是 P0。** `domain_criteria` 的描述包含「推荐目标须满足价格/位置/饮食限制」，而 `bench/gen/prefeval-notes.md:18` 明确记载 `lifestyle_dietary[0]`（严重麸质不耐受）是**作为负例专门采集的**；anchor §3 把这一整类划在 store 之外。提案的一句话把被拒绝的池子从正门请了回来。

三点让这件事比看起来更严重：

1. **桶名 + 例子就是可执行指令。** 它会落进 `extraction.py` 的 flash prompt，紧挨着 `extraction.py:28-30` 那一行禁令。一个叫 `domain_criteria`、描述里写着「饮食限制」的桶，会稳定地产出麸质条目，无论别处的段落怎么写。
2. **`noise-reject-content` 6 个 case 会有 5–6 个反转**，L 套件里唯一的内容守卫消失。`noise-reject-task` 守的是「一次性 vs 持久」，是另一个轴，补不上。
3. **这条线今天已经被悄悄越过了。** `l-rel-005`（「只在工作日安排会议」）的 gold 是 `contradict`，即它是合法存量 requirement；`l-rvk-004`（「通知必须 5 点前发」）同理。它们和「找一家无麸质餐厅」结构同形。所以：**采纳这个桶不会制造矛盾，它会让一个已存在的潜在矛盾显形；拒绝这个桶也修不好 `l-rel-005`。**

可用的分界（实测能复现现有全部 gold）：

> **work-rule test —— 三问全 yes 才存：**
> **① actor**：约束的是 agent 自己做/判断/产出的东西（可用的方法、必须走的步骤、必须下的判断、交回的产物），还是它只是找到并转述的外部对象的属性？
> **② source**：约束来自**项目/角色/工作种类**（用户个人情况变了它依然成立），还是来自**用户这个人**（健康、恐惧、喜好、所有物）？
> **③ durability**：跨未来同类任务成立，而非本次请求（`extraction.py:29-30` 已在执行）。

代入验证：麸质/恐高/黑胶/只看 4K → ①no ②no → reject ✓；「讨厌粉色装修」→ ①yes ②no → reject ✓（这条证明 ② 不可省）；「只在工作日安排会议」→ ①yes ②yes → store（现在**有理由**了，不再是碰巧通过）；「本项目不训练模型，只用 Flash API」→ ①yes ②yes → store（这是产品最有价值的真实场景：用户对 Claude Code 说了三遍还是收到 fine-tuning 方案，正是 anchor §8.8 定义的那个摩擦）；「推荐目标的价格/位置/饮食」→ reject，**从桶里删掉**。

**必须改名。** `domain_criteria` 这个词本身就在邀请「一个合格的餐厅长什么样」。改叫 `work_constraints`。

**两个前置条件，都是硬的：**

- **bench 缺正例半边。** 6 个 `noise-reject-content` 只测了拒绝侧；这条分界在没有配对的 work-constraint 正例类别（~6 条「不训练模型」形状）+ 2–3 条过 ① 挂 ② 的对抗例（`l-noisec-005` 是模板）之前不可证伪。
- **`scope` 今天是死的，而这个桶是第一个真正需要它的。** `server.py:140` 调 `translate(text, store.list())` **不传任何 context**，`recall._scope_ok` 对缺失维度从不排除，`schema.py:35` 的 `{app?, task?, lang?}` 里**没有 `project`**。也就是说一条「本项目不训练模型」会泄漏到每一个无关请求里。加 `project` 维度**并且**加一个填充它的 context 源，是前置条件不是后续项。

诚实地说清代价：采纳这条分界之后，`domain_criteria` 会瘦到 6 条命中里可能只剩 1–2 条（「用 TypeScript」），而「周二上午 10 点开会」按判据 D7 大概率移去 `execution_policy`。**这个桶很可能不该以「推荐条件」的名义存在，而该以「工作约束」的名义存在，且它在现有 bench 上几乎为空。**

### 3.4 其他结构问题（较小但确凿）

- **`strength` 撞名**：提案的枚举与现有整数计数器同名，而 `store.AUTO_RETIRE_AT = -2` 这条零 token 的机械退休规则挂在这个整数上，anchor 和 design doc 都用这个名字。
- **7 值 `status` 把召回谓词和审计混在一起**：`r.status == "active"` 出现在 `recall.recall`、`recall.style_block`、`consolidate.consolidation_ops`、`store.list/active`、`store.apply_ops`（3 处）——拆成 7 值意味着 9 个点各自要学会哪些值可召回。而 `conflicted` 根本不是生命周期状态，它现在已经是 op batch 上的一个 `flags` 条目。
- **`persistence` 冗余**：三个取值的输入（`salience` / `strength` / `scope`）都已存在；`ephemeral`/`session` 根本到不了 store（`EXTRACTION_SYSTEM` rule 1 已禁一次性指令）。在 append-only 日志里存一份派生值，`bump_strength` 每次都得记得重算，必然过期。
- **无处安放的两类**：交付路由（渠道/收件人/传输）和 artifact 内部技术约定（type hints）。见 §1.3(6)。

---

## 4. Migration 方案摘要

完整设计另附；此处只给决策与理由。

### 4.1 `bucket` 与 `key` 正交并存，`key` **不**变成 `bucket.attribute`

这是整个 migration 里最关键的一个否决，理由不在设计层面而在代码里：

**`key` 的 head 部分是承重的表层词汇，不只是 dedup 标签。** `recall._key_hits_query` 和 `signals._key_terms` 都把 head 拿去 `signals._KEY_LEXICON` 查表（`"email": ["email","mail","邮件"]`），再与用户的原始 query / message 做匹配。语料里真实的 key 是 artifact-first：`email.length` ×19、`report.format` ×15、`email.language` ×14。

`"email"`、`"code"`、`"报告"` 会出现在用户文本里；**`"output_contract"` 永远不会。** 把 `email.length` 改写成 `output_contract.length`，等于把 recall 的 tie-break 和 route-A screener 的 boost 一起清零，而且**是静默的**——没有任何测试会红，只有 store 超过 `RECALL_CAP` 之后质量悄悄下滑。

附带一条 dedup 上的反效果：`"邮件写短一点，别超过120词。"` 与 `"Emails must stay under 120 words."` 今天靠共同的 `email.length` 合并；在 `bucket.attribute` 下变成 `output_contract.length` vs `output_contract.email_length`，除非 attribute 命名也同步归一化，否则**合并更难了**。

结论：`bucket` 是新的兄弟字段，dedup 身份变成 `(bucket, key)`；`key` 只加一条 prompt 级软约束——head 必须是 artifact 或 task 名词，不能是属性（所以 `format.output` → `output.format`）。

### 4.2 命名冲突：整数 `strength` 保名，枚举叫 `binding`

方向就这一个，理由是磁盘迁移成本为零：反过来命名意味着历史记录里每个 `strength: 3` 都要永久 type-sniff。而且 "binding"（这条规则对 agent 有多约束）本来就比 "strength" 更准确，也不会被读成量级。

`binding` 大部分时候**不发射**：extraction 只发 `polarity`，`bindingness` 属性把 `require|prohibit → hard`、`prefer|avoid → soft`；只有用户措辞明确覆盖（「尽量」「if possible」「必须」）时模型才显式给 `binding`。这是 extraction 输出成本上最大的一个杠杆，而对约 90% 的条目零表达力损失。

四个字段各答各的问题、各由不同机制写入：

| 字段 | 含义 | 写入者 | token |
|---|---|---|---|
| `strength: int` | 被证据确认/反驳过几次 | `bump_strength`、`apply_ops("reinforce")` | 0（机械） |
| `binding` → `bindingness` | 对 agent 的约束强度 | extraction，仅非默认时 | ≈0 |
| `polarity` | require / prefer / avoid / prohibit | extraction，仅非 require 时 | ~2/op |
| `salience: int` | 写入时用户表达得多明确 | extraction（已有） | 不变 |

### 4.3 其余字段

新增 `bucket`（长名入盘、短码 `OUT`/`DELIV`/… 上线）、`polarity`、`binding`、`evidence_id`、`provenance`、`retire_reason`。`status` 保持二值，退休原因走 `retire_reason`；`persistence` 做成只读 property。

`evidence_id` 的定位必须写死在注释里：**它是 provenance，不是外键。** `store.apply_ops` 里任何地方都不得按 `evidence_id` 扇出——退休一个原子绝不能碰它的兄弟。它只有三个合法消费者：`merge_allowed` 的防重融守卫、review UI 的分组展示、bench 诊断。

### 4.4 向后兼容

`data/store.jsonl` 里现存 **v0 记录只有 `{id, text, status, created_at, updated_at}`**——没有 `key`、`kind`、`scope`、`strength`、`salience`。且 `bench/runner/run_extraction.py:45` 用 `Requirement(text=t)` 位置构造。所以：每个新字段必须有默认值，`from_dict` 每个新字段必须有 `""` 兜底，`bucket == ""` 在全链路上表现为通配（不过滤、不排序惩罚、不阻止 merge）。

三条防御：`from_dict` 里对字符串型 `strength` 做四行 coercion（吸收进 `binding` 而不是崩）；`_norm_bucket` **fail-open**（无法识别的桶降级为 `""` + 一条 flag，**绝不丢 op**）；`key` 与 `bucket` 独立失败（一个坏了另一个照常落盘）。

`kind == "style_rule"` 的条目**不带 bucket**，并在 `validate` 里强制。理由不是抽象层级而是收件人：桶约束下游 agent 的工作，style_rule 约束 MemTranslator 自己的改写。而且它们从不进 `recall.recall`（`recall.py:39` 过滤 kind）、从不进 `consolidate.buckets`（`consolidate.py:47` 同）——给它们加桶就是写了没人读的死字段，还会在有人放宽那个过滤时泄漏进分组。224 条里没有一条需要 `kind=style_rule`，这个群体确实很小。

### 4.5 成本

输入侧：索引行前缀从 `[12] (email.length) ` 变成 `[12] OUT/email.length `，约 +2 token/行；32 行 ≈ +85，48 行 ≈ +130。加上**一次性 ~230 token** 的桶定义块（7 条定义 + 8 组 worked triple），且它是静态 system 文本，完全可缓存。相对本来就 700–1500 token 的 STORE 块，增幅 <10%。

输出侧：`bucket` + `ev` + 条件性 `pol` ≈ **+13 token/op**（现状 45–60/op）。真正的增量来自 atomisation 提高 op 数——一句两原子从一个 op（~60）变成两个（~120），这比每 op 的增长大得多。`run_extraction` 的 `max_tokens` 1500 → 1800 留余量。

诚实的风险不是预算，是 **haiku 在多背一个字段之后 `key` 质量静默下滑**。缓解手段放在 parser 而不是 prompt：两个字段独立降级。

### 4.6 分期（每期的验收门）

| 期 | 内容 | 门 |
|---|---|---|
| 1 | schema 字段 + `from_dict` 兼容 + `validate`，无行为变化 | 全测试绿；`data/store.jsonl` 能载入 |
| 2 | `consolidate.buckets` 五级分组 + `merge_allowed` 守卫（此时还没有桶数据，专门验 legacy 回退路径） | L 的 consolidation 类别持平 |
| 3 | `recall._rank` + `_shadowed`，确定性零 LLM | T 持平；≤cap 路径未动，T 有任何移动即 bug |
| 4 | extraction prompt：桶块 + atomisation 规则 + `ev`。**同 PR 修 `l-diff-001` 的 gold** | L；重点看 `revoke`（0.50），atomisation 是它的直接解 |
| 5 | `scripts/backfill_buckets.py` 跑存量（48 条 ≈ 2 次 haiku call） | 重跑幂等为 no-op |
| 6（独立） | 桶进 `TRANSLATOR_SYSTEM` | 单独测 T，flag 门控，见 §5 |

分组顺序**刻意 key 优先**（exact key → `(bucket, key-head)` → key-head → bucket → 兜底池）：bucket 是模型赋值、跨轮不确定，先按 bucket 分组会把两条 bucket 恰好不一致的 `email.length` 拆开，相对今天是**退步**。

---

## 5. Translation IR：单独评估

**结论：不建 7-slot IR。现在不建，bench 扩容后也不建**，除非 Suite R 跑出明确指向 slot 缺失的新失败类（我判断不会——R 测的是 store lifecycle，读路径分解不在它的量纲里）。

依据是对 real translate path 的 24 次 haiku 实测（greedy，探针输出留在 scratchpad 的 `probe*.py` / `probe_out.json`）。

### 5.1 两个改变前提的实测事实

**事实 A：preserve-long 0.40 主要是 bench 标注缺陷。** `T-20260725-181137.json` 里 10 例失败 6 例，**6 例的 failure 全是同一条** `{"layer":"decision","why":"expected apply, got noop"}`——没有一例 mech 层 keyword 丢失，没有一例 judge 层 material-intact 失败。**payload 被改坏这件事从来没被测到过。**

原因在 case 里：失败的 6 例（t-long-005..010，全 `source: generated`），stored requirement 在用户自己的 input 里**已经逐字说过一遍**（005 的 stored "do not change any numbers or timestamps" vs input 里的 "Do not alter the timestamps, error codes, or UUID."，其余五例同构）。模型 noop 是因为**没有东西可加**。而通过的 4 例里 003/004 的 apply 其实是语义空转（把用户已说的话重说一遍）。**bench 在奖励冗余复述、惩罚诚实 noop。**

三条件对照（18 次调用）：

| 条件 | 设置 | 结果 |
|---|---|---|
| A | 原 requirement + 原长 input | 6/6 noop（复现 bench 失败） |
| C | 原 requirement + **剥掉 payload** 的短 input | **6/6 noop** ← 长度不是原因 |
| B | 换成 input 里没有的 requirement + 原长 input | 4/6 apply，**4/4 payload keyword 100% 存活** |

C 是决定性的。**「长 paste 导致保守 noop」这条因果链不成立。** `docs/2026-07-26-bench-scaleup-spec.md` 里「`preserve-long 0.40` 是活跃缺陷」这句按此需要改。

**事实 B：真正的长 paste 悬崖存在，位置在 3k–6k 字符，成因是 `max_tokens=1024`。** bench 最长的 preserve-long input 只有 619 字符，根本没进风险区。实测扫描：1,200 字符 → apply，2/2 blocks；2,946 → apply，5/5；**5,856 → noop，`parse_error=True`，0/10 blocks**。raw 输出在 3,392 字符处**从 payload 中间被截断**。成因直接确认：`src/memtranslator/llm.py:25` 的 `complete` 默认 `max_tokens=1024`，translate 没有覆盖它。同一输入提到 4096：apply，10/10 存活。

这是产品路径上一个真实 P1，且**用户侧完全静默**——热键按下去什么都没发生。

### 5.2 IR 修不好它瞄准的靶子

- **preserve-long**：走一遍 t-long-005，requirement 会打进 `execution_policy` slot，而那个 slot 里已经有语义相同的内容，patch 是 no-change，serialise 出来与今天一模一样。冲突不在「payload 有没有被保护」，在「requirement 已被满足」。
- **真实悬崖上 IR 帮倒忙**：additive rewrite 今天只输出 payload 一遍；IR 若把 payload 实体化进 slot 就要输出两遍。`max_tokens` 不变的前提下，悬崖从 ~3k 下移到 ~1.5k。**IR 会把这一类的真实失败率推高。**
- **P0（模型直接回答问题 / 为满足「别复述我的问题」从问题里删词）**：变体一 IR 防不住（末端仍是自由文本生成，答案照样能出现在 `goal` slot 里）；变体二看似该防住，但 `task_goal` 按定义就是**可写 slot**，裸问题整句都在 `goal` 里，删词发生在合法可写的 slot 内部。真正修好它的是 `preserves_request`（`SequenceMatcher`，`PRESERVE_MIN_RATIO = 0.85`，零 LLM、零 token、post-hoc），两个变体一起吃掉。**上了 IR 你也不会删掉它，所以 IR 在这条防线上净增益为 0。**

顺带纠正提案的一句措辞：「payload 是受保护 slot」听起来比现状强，其实**弱**——现状保护的是整个 request 的 85% 字符，是 payload 的超集。

### 5.3 IR 独有的新故障模式

只列今天不存在的：① **payload/instruction 边界判错且静默**——t-long-005/008/009/010 的用户指令夹在 payload 后面，003 在前面，007 是三明治；判错两个方向都坏（指令被吞进 protected slot 永不 patch，或 payload 漏进可写 slot 被静默改坏）。② **小而致命的删除穿过 0.85 阈值**——切成 slot 后坏的通常是一个小 slot（30 字符占 619 的 5%），而 `PRESERVE_MIN_RATIO` 设计上就要容忍这个量级。③ **不可分解的请求**（「帮我看看这个」+ 一坨 paste）逼 serialiser 给 `goal` 猜一个动词，直接违反 prompt rule 2「Never invent constraints」。④ **serialise 出来的文本不像用户写的**——slot 化重组天然产出模板腔，而 `style_rule` 机制正是从「用户把我们注入的约束重新措辞」学出来的，`STYLE_RULE_CAP=10` 装不下这个压力从偶发变常态。

**该承认的收益**：slot 归属让 `applied_ids` 变成机械可核验，也能给 `recall` 当 prefilter 取代 `_key_hits_query` 的前缀启发式。**但这些收益全部来自「bucket 作为 store 里的 schema 字段」，一条都不需要「把请求分解成 IR」。这是提案最需要拆开看的地方——它在借另一个改动的信用。**

### 5.4 成本与建议时机

预算基线（`docs/2026-07-25-v11-write-path-design.md:392`）：每轮 1 flash，in ≤2.4k / out ≤1.0k；实测 T 全套 latency median 2,962ms、p90 4,024ms。三次 call 直接出局（median ~9s）。一次 call 输出全部 slot + polished 是最差档：输出翻倍，`max_tokens=1024` 下悬崖对半砍；提到 4096 能救，但 output token 是 latency 主项（2,946 字符单次 apply 已 5,158ms），p90 会过 8s。

**唯一可行档是一次 call + payload 用 sentinel/span 替换**（模型输出 `payload_spans`，代码做替换）：输出 token 与 payload 大小解耦，payload 区域拿到 100% 字符保证。**但这一档根本没用到 7 个桶，它只需要一个二分——payload vs 非 payload。** 另外 6 个 slot 在 T/L/E 全部测量里没有任何一条失败可以归因，它们是纯成本。

**建议时机**，按 ROI 排序，前两步合计约两小时：

- **E0（零 LLM，先做）**：决定一个产品问题——stored requirement 已被用户请求逐字满足时，正确行为是 noop 还是冗余复述？我判断是 noop（anchor §2.2 的 noop-by-default 就是这个精神）。若认同，把 t-long-005..010 的 `expect_decision` 改成 `noop`，**preserve-long 0.40 → 1.00，零代码改动，T 总分 0.883 → 0.983**，因为今天的行为本来就是对的。无论怎么选，case 里都要加一条 `redundant: true/false` 标注。
- **E1（一行代码 + 一批新 case）**：`translate()` 显式传 `max_tokens`（4096 起）；给 T 加 `preserve-XL` 一档（3k/6k/12k 字符各 3 例，用现成的 `contains_all` 打首/中/尾三个 anchor）。**已测口径：5,856 字符今天必 FAIL，4096 下 10/10 通过。**
- **E2（只在 E1 之后仍有缺口时）**：单 call + sentinel，上线闸门先定死——`preserve-XL ≥ 0.9`，T 其余 5 类**一个都不掉**，apply-only median latency 涨幅 ≤20%（基线 3,206ms）。明确不加另外 6 个 slot。

---

## 6. 引用核查

**三篇全部未过所述的 ICML/ICLR/NeurIPS 门槛。**

| 论文 | 实际 venue | 真正支持的 | 不支持的 |
|---|---|---|---|
| *What Should We Engineer in Prompts? Training Humans in Requirement-Driven LLM Use* | **ACM TOCHI 2025 期刊**（arXiv 2409.08775；引用的 v2 已被 v3 2026-04-28 camera-ready 取代，DOI 10.1145/3731756） | 「requirement 是值得捕获的东西，且其质量重要」：30 人 RCT，ROPE 组 20% vs 对照 1%，前后提升 19.1%（Requirement Quality +25.4%，Output Quality +12.7%，均 p<0.05）；requirement 质量与输出质量 Spearman ρ=0.71 (GPT-4o) / 0.80 (o3-mini) | **完全不支持 taxonomy**。它没有任何 requirement 内容类型的分类，唯一的分类是从 requirements engineering 借来的 commission/omission **缺陷**二分——分的是 requirement 里的错误，不是 requirement 的种类。它也完全不谈跨 session 的持久化、存储、检索或组织；requirement 活在单个 prompt 里。**拿它论证 taxonomy 是过度解读。** |
| *Personalization of Large Language Models: A Survey* | **TMLR 期刊**（arXiv 2411.00027 v3；OpenReview `tf6A9EYMo6`） | 「style/relevance/accuracy 三轴切分用户偏好在文献里是既有框架」：Figure 4 / Table 1 的 Tone and Style / Relevance / Accuracy 三维，子面 Writing Style·Tone / Content·Contextual Relevance / Factual·User Data Accuracy | **不支持「分桶能改善检索或应用精度」**。该 taxonomy 被明确框定为 personalized text generation 的**评估标准/desiderata**（原文措辞是 "a robust taxonomy **for evaluating**"），是综述的概念提议——无实验、无 ablation、无任何证据表明按这三轴切分 store 能改善什么。全文 "memory" 只出现 11 次，不讨论 memory store 组织或分桶检索。 |
| *How Does Personalized Memory Shape LLM Behavior?* | **arXiv only，且是撤回的 ICLR 2026 投稿**（2601.16621 v1，2026-01-23；原题 OpenReview `jSt7oxzJxI`，2026-01-04 撤回后改题上传；配套 repo RPEval 9 stars，比 2k 的 fallback 门槛低三个数量级） | **强力支持前半句**：不适用的 memory 会实测降低意图理解。Ignore 类判别准确率 Qwen2.5-7B 0.06 / GPT-5 0.12 / GPT-4.1 0.28 / DeepSeek-V3 0.38 vs 人类 0.86（gap 55.8%）；多偏好设定下 gap 84.0–91.8%；Finding III 是**逆规模**——更强的基座模型更不会忽略无关偏好 | **不支持后半句「所以分桶能提升 requirement 适用性精度」，而且是被反驳。** ①Ignore/Support/Dominate 是**每个 (preference, query) 对在推理时的适用性判断**——同一条偏好对 A 查询是 Ignore、对 B 查询是 Dominate；它是待预测的标注，不是 store 的组织方案。②缓解手段 RP-Reasoner 是推理时的贝叶斯过程（反事实消元 + 意图先验 + rank-sum 融合，Macro-acc 相对提升 258%），**没有任何变体对 memory store 做分区、打标或分组，也没有这样的 ablation**。③论文含**直接反对存储侧预过滤**的证据：Appendix D.1 Table 9，用 all-MiniLM-L6-v2 相似度判适用性，Ignore 类 30%、Support 类 26%、总体 36%，对比 RP-Reasoner 0.77，结论是「仅靠语义相似度几乎无法有效过滤无关 memory」。**该论文的论点是适用性依赖上下文、必须逐查询推理**——这恰好切在任何「在存储时固定适用性」的方案的对立面。 |

**给引用的处置建议**：#1 只能支持「requirement 值得捕获」，不得出现在任何 taxonomy 论证里；#2 可作为「三轴切分是既有框架」的 framing 引用，须注明它是评估标准而非存储方案，且无实证；#3 可引用「不适用 memory 实测损害意图推断，且随模型能力恶化」，**不得**引用为分桶依据。三篇都不满足门槛这件事本身也要向 owner 明说（见 Q10）。

---

## 7. 建议的执行顺序

与正在进行的 bench 扩容（`docs/2026-07-26-bench-scaleup-spec.md`：12 scenario × 56 constraint = **672 条**，预算 6–8 个工作日人时）的衔接，答案是**先定 taxonomy，再生成 672——但只需要先定「定义与判据」这一层，代码 migration 可以并行**。

四条理由，都具体：

1. **672 条是唯一能验证 7 桶的机会，而它一旦手写完就不会重做。** 现在 GOAL/REAS 各 0 clean。如果 672 条按现有 bench 的分布长（delivery-heavy），扩容之后这两个桶**依然**是 0，7 桶主张永久不可证伪。所以 catalogue 的验收标准里必须写死每桶最低配额（建议 GOAL/DOM/REAS 各 ≥15 条无歧义），而配额只有在判据定稿后才写得出来。
2. **catalogue 的 constraint schema 会带 bucket 标签。** 672 条 constraint 是手写的，重新打标不是「跑个脚本」，是重新人工过一遍 + 双人签字。这件事只能做一次。
3. **污染风险是双向的，必须串行安排。** extraction prompt 的桶定义块要带 8 组 worked triple，而 `tests/test_no_bench_contamination.py` 双向检查（case 的 `distinctive` 哈希 grep `src/`，产品 prompt 的固定短语不得出现在 case 里）。2026-07-25 已经出过一次逐字泄漏（extraction prompt 的四个 exemplar 抄自 writer-zh），672 条的暴露面比 114 条大得多。**worked triple 必须独立撰写，且在 catalogue 定稿后过一遍双向 grep。**
4. **T 的基线现在是错的，不能在错基线上生成 672 条。** §5 的 E0 表明 preserve-long 0.40 有 60% 是标注缺陷，修完 T 总分从 0.883 到 0.983。在这个之前排的任何工程优先级都是按错数字排的。

具体顺序：

| 步 | 内容 | 谁挡谁 | 估时 |
|---|---|---|---|
| **A** | E0 + E1：preserve-long 6 例重标 + `redundant` 字段；`max_tokens` 显式传参 + `preserve-XL` 一档 9 例 | 挡住一切（T 基线） | ~2 小时 |
| **B** | 判据定稿：6 条 discriminator 写进桶定义；`task_goal`/`reasoning_policy` 二选一划掉 "critique"；`communication_style` 删掉 "avoid padding"；`domain_criteria` 收窄 + 改名（需 Q1–Q3 拍板） | 挡住 D 和 E | ~1 天，无代码 |
| **C** | migration 期 1–3（schema 字段 / consolidate 分组 / recall 排序）——**全部机械、零 LLM，可与 D 并行** | 不挡 | ~1–2 天 |
| **D** | 672 条 catalogue 撰写，schema 带 bucket 字段，验收含每桶配额；同时补 work-constraint 正例类别（~6 条）+ 2–3 条 ①yes②no 对抗例 | 被 B 挡 | 6–8 工作日 |
| **E** | migration 期 4（extraction prompt + `ev` + `l-diff-001` gold 修正）——worked triple 与 D 交叉查污染 | 被 B 和 D 挡 | ~1 天 |
| **F** | 期 5 backfill；期 6（IR）**仅在 E1 之后仍有缺口时**评估 | — | — |

关键并行点：**C 与 D 并行**（一个是代码、一个是人时，互不占资源），**E 必须在 D 之后**（污染检查），**B 必须在 D 之前**（配额与标签）。B 只有一天，且不写代码——用一天换 672 条的一次性正确，是这个排期里性价比最高的一格。

---

## 8. 需要 owner 拍板的问题

**Q1. `domain_criteria` 走哪条路？**
选项：(a) 原样采纳 → 产品变成通用 preference compiler；(b) 加 work-rule test（actor + source + durability）收窄并改名 `work_constraints`；(c) 整个桶不要。
**推荐 (b)。** 理由：(a) 会让 `noise-reject-content` 6 例反转 5–6 例，删掉套件里唯一的内容守卫，同时 anchor §8 已承认「Mem0/Zep 在 prompt 受限时可能追平数字，我们抓的是产品空缺与边界」——边界一没，剩下的差异化就没了；而且 `prefeval-notes.md:4` 记的 CC BY-NC 会从脚注变成阻塞项。(c) 会丢掉产品最有价值的真实场景（对 Claude Code 说三遍「本项目不训练模型」），并且**修不好** `l-rel-005`/`l-rvk-004` 这个已经存在的中间地带。(b) 保留全部现有负例、把 `l-rel-005` 从「碰巧通过」变成「有理由通过」。**若选 (a)，必须先修改 `position_anchor.md` §1/§3/§6，不能让一个 taxonomy 桶隐式修宪。**

**Q2. 提案里那句「推荐目标须满足价格/位置/饮食限制」删不删？**
**推荐删，且这是全提案里最该删的一句。** 它会进 flash prompt，而 flash 会照抄例子。

**Q3. `scope.project` 维度 + context 源，是 Q1(b) 的前置条件还是后续项？**
**推荐设为硬前置。** `server.py:140` 今天不传 context，`_scope_ok` 对缺失维度从不排除——一条「本项目不训练模型」会泄漏进每个无关请求。这不是理论风险，是当前代码的确定行为。在这条修好前，`work_constraints` 不上线。

**Q4. `strength` 撞名怎么解？**
**推荐：整数保名，枚举叫 `binding`，通过只读 property `bindingness` 暴露。** 反向命名要求历史记录永久 type-sniff，且 `AUTO_RETIRE_AT = -2` 挂在这个名字上、写进了 anchor 和 design doc。

**Q5. `status` 要不要扩成 7 值？**
**推荐不要。** 二值保留为 recall 谓词，退休原因走 `retire_reason`（纯审计，永不参与过滤）。理由是 `status == "active"` 有 9 个调用点，扩值意味着每个点各自要学会哪些值可召回。`conflicted` 根本不是生命周期状态，它已经是 op batch 上的 flag。

**Q6. `key` 要不要变成 `bucket.attribute`？**
**推荐不要，两个字段正交并存。** 这是有代码证据的否决：`key` 的 head 会被 `_KEY_LEXICON` 拿去和用户原文做匹配，`"email"` 匹配得上、`"output_contract"` 永远匹配不上；改了之后 recall tie-break 和 screener boost 静默归零，没有任何测试会红。

**Q7. `l-diff-001` 的 gold 改不改？**
**推荐改，且必须与 extraction prompt 同 PR。** 现在它期望把「English + firm tone」存成一条，而 taxonomy 说必须两条。不改的话，L 分数会惩罚正确的 atomisation。同时借这个机会把 atomisation 做成可评测维度（「是否产出 2 条」），今天的 gold 表达不了。

**Q8. preserve-long 那 6 例的正确行为是 noop 还是冗余复述？**
**推荐 noop。** 依据 anchor §2.2 的 noop-by-default，且复述会让用户觉得系统啰嗦。选 noop 的话零代码改动，preserve-long 0.40 → 1.00，T 0.883 → 0.983，因为今天的行为本来就对。若 owner 认为该 apply，那就把这 6 例的 requirement 换成 input 里没有的（条件 B 已验证换了之后模型会 apply 且 payload 完整）。**无论哪种，case 里都要加 `redundant` 标注**——否则半年后还会再踩一次。

**Q9. translation IR 什么时候再评估？**
**推荐：E0 + E1 之后重看，且只考虑 1 bit（payload sentinel），不考虑 7 slot。** 闸门定死：`preserve-XL ≥ 0.9`、T 其余 5 类一类都不掉、apply-only median latency 涨幅 ≤20%。理由是它瞄准的三个靶子，两个已被更便宜的手段解决，第三个它会恶化。

**Q10. 三篇论文都不过所述 venue 门槛（TOCHI 期刊 / TMLR 期刊 / 撤回的 ICLR 投稿 + 9-star repo），怎么处理？**
**推荐：降门槛与撤引用二选一，明确选一个。** 我的倾向是撤：#1 和 #3 被用来支持它们明确不支持的主张（#3 的相似度过滤 ablation 甚至是反证），换个引用救不回来；#2 可以保留为「三轴切分是既有框架」的 framing，但必须标注它是评估标准提议、无实验。若 owner 想保留三篇，那就把门槛条款改成「顶会/顶刊/高影响 preprint」并写清 #3 的撤回状态——**别让门槛条款和实际引用继续互相矛盾。**

**Q11. `task_goal` 和 `reasoning_policy` 在 0 clean 命中的情况下要不要进枚举？**
**推荐进，但禁止声称已验证。** 枚举值本身成本为零；空桶的代价是 prompt 里多两行定义（已计入那 230 token）。但在 672 条里它们各自拿到 ≥15 条无歧义命中之前，这两个桶不得进入任何评分维度、不得写进对外材料的「7 类 taxonomy」表述。现在的诚实说法是：**「一个 5 桶方案，外加两个待验证的桶。」**