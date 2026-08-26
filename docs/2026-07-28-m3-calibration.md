# M3 标注校准：10 张决策卡与三条落地规则（2026-07-28）

预算按 spec §3 分配：4 张 deliverables↔output_contract、3 张 retire vs
contradict、3 张 scope 宽度。每张卡是一句用户话式 + 两种读法；owner 的答案折成
**可写进 prompt 的规则**，全量重跑标注，翻转率落盘在本文末尾。10 条全部前置用于
校准，**放弃统计上界**——语料错误率的上界诚实记为「未测量」，这是 spec §3 算过的
算术，不是偷懒。

## 一、10 张卡与裁定

### deliverables ↔ output_contract（争议实测集中地：660 条里 123 条 bucket
分歧票落在这条边上，53%）

| # | 用户话式 | 裁定 |
|---|---|---|
| 1 | 报告里的数字都要带单位 | **output_contract** |
| 2 | commit 有 breaking change 要带 BREAKING CHANGE 尾注 | **output_contract** |
| 3 | 复杂的操作要加几行注释说明 | **deliverables** |
| 4 | 长文档开头要有目录 | **deliverables** |

**B 规则（写进标注 prompt）**：判别器 = **合规动作是否新增一个可分离的内容块**。
新增本来不存在的块（注释、目录、总结节）→ 问题 3 命中 → deliverables；给已存在的
信息加标记/换渲染（数字的单位、diff 已体现的 breaking 尾注、大小写、标点）→
问题 3 不命中，落到问题 4 → output_contract。

### retire vs contradict（L 的 revoke 类实测 0.50，全 suite 最低）

| # | 用户话式（存量规则） | 裁定 |
|---|---|---|
| 5 | 「之前说的邮件120词那条不用了」（邮件≤120词） | **retire** |
| 6 | 「邮件别管字数了，想写多长写多长」（邮件≤120词） | **retire** |
| 7 | 「周报别用 bullet 了」，没说改用什么（周报用 bullet） | **contradict** |

**R 规则**：判别器 = **终态是否仍需要主动行为**。回到无约束默认——哪怕说得很用力
（「想写多长写多长」）——都是 retire，强调式的默认不是新值；留下持续禁令
（「别用 bullet」= prohibit bullet）是一条极性翻转的新规则 → contradict，
后继条目落库。

### scope 宽度（三份对抗审查都指过：scope 欠标是唯一有方向且对导出隐形的偏差）

| # | 用户话式 | 裁定 |
|---|---|---|
| 8 | 给房东的邮件不超过120词 | **实例级保留，不一步升类**（见下） |
| 9 | python 的注释用英文写 | **code_lang=python**；owner 强调更该重点覆盖的是「注释用英文」（无限定→全局）这种形态 |
| 10 | 汇报里数字要带单位 | **task=report** |

**S 规则**：说了产品能表达的限定词（task/code_lang/nat_lang/app）就**照说的标**，
没说就全局，**永不发明用户没说的 scope**。产品表达不了的限定（具体收件人、具体
文档）**留在规则文本里，维度全 ANY，不升类**。

**卡 8 的完整裁定（owner 原话的引申，超出了标注规则的范围）**：升宽不是标注问题
是 **CRUD 问题**——同型第二条证据出现时（「给教授的邮件也≤120词」），应当作为
**同一条 memory 的更新**合并，合并后的宽度是**覆盖两个实例的最小泛化**（「给具体
个人的邮件」），仍然不是 task=email。两个落点：

1. 产品现在没有这个行为（consolidation 只 merge 等价对，没有 widen-on-evidence）。
   **记为产品向 issue，套件 v1 不把 widen 当 gold 断言**。
2. **M5 的候选 episode 母题**：同型实例两次出现 → 观察 SUT 合并/泛化行为。这是
   writer-zh 写窄病的正面测法，恰好是 4c 两版都修不对的那件事的测量面。

**语料配额修正（owner 卡 9 的批注）**：无限定词、意图全局的形态要**加重配额**——
标 scope 的能力要先在「不该标的别标」上测住，才谈得上「该标的标对」。

## 二、对失效话语形态的绑定（写进 build_episode）

R 规则同时钉死了 episode 里失效事件的**话语形态与 effect 类型的对应**，作者不得
混用：

- `retire` effect 的话语必须是裸撤回/回默认形态（「那条不用了」「别管 X 了随意」）
- `contradict` effect 的话语必须带新值（「改成 X」）或持续禁令（「别用 X 了」）

## 三、重标结果（翻转率）

同 seed 重跑骨架化（900 → 662 过闸）+ 校准后标注（659 atoms）。与校准前
catalogue 按骨架指纹对齐到 403 条（骨架化在 temp 0 下仍有措辞抖动，未对齐的
~250 条不进翻转率统计，但两版都是全量重标）：

| 字段 | 翻转 | 率 |
|---|---|---|
| bucket | 93/403 | **23.1%** |
| key | 139/403 | 34.5% |
| scope | 113/403 | **28.0%** |

其中 deliverables↔output_contract 方向翻转 19 条，两个方向都有——B 规则不是
把一侧倒进另一侧，是换了判别器（「Keep a Changelog format」现在判 deliverables
因为它强制的是 changelog 的内容块清单；「short summary」判 output_contract
因为压的是已有信息的长度）。

scope 翻转的主体是**去 scope 化**：326 scoped → 202 scoped（全局 334 → 449），
与 S 规则「永不发明用户没说的 scope」方向一致。

**按预注册处置规则执行**：

1. 翻转率 > 10% → **校准前的那版标注（含用它建的第一版 e-01）整体作废**。
   这是 spec §3 写明的预期结果，不是故障。
2. bucket 轴 23% 的漂移意味着 per-bucket 子分在这版语料上不可发布——headline
   不受影响（计分不走 bucket），bucket 只影响 consolidation 分组与诊断分层。
3. key 34.5% 的翻转率偏高，主要是校准 prompt 拉长后 key 选择的注意力被稀释；
   key 不进计分（对齐走 distinctive），影响限于 I10/关系代数的边密度，
   在 e-01 的 lint 上未见新增违例。记录，不处置。
