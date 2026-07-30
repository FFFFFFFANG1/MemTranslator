# 项目状态与下一步（2026-07-29，写路径攻坚后更新）

三个宏观阶段对照：**① 确定软件层功能 → ② 完善 memory 机制 → ③ latency/cost/前端交互**。
当前位置：**① 已收口。② 收口（读 46/46、写 L 0.981、CRUD 大修落地）。
③ 已开工：prompt 瘦身与预筛已入账，E1 第三轮已跑，前端交互待 owner 裁定。**

## ① 软件层功能 —— 已收口

- 产品形态稳定并经受住了两代 bench：热键 → 输入框内改写 → 用户编辑 → 发送；
  改写只增不删；下游 agent 永不见记忆。
- 契约 owner 口径：**(任务, 偏好记忆) → 对当前任务最适配的 task requirement**，
  三个动词等级 noop / carry / **adapt**。adapt vs no-invention 冲突已裁定落地
  （commit `240e07c`，裁定记录见 git log 与 bench/README 计分节）。**① 无未决项。**

## ② memory 机制 —— 读路径章节关闭；写路径两大欠账已清（本次攻坚）

**尺子**：bench v2 robustness 43 check + perf 真实重放（canary 双头仪器）；
bench_archive 468 条语料作原料库，L 套件 54 case 是写路径单元裁判
（METRIC_VERSION 3）。

### 写路径攻坚记录（2026-07-29，commit `5bdee98`）

先量化后动手：把 12 集 archive 语料逐轮过 route-A 筛选（零 LLM），得到分语言
× 分 effect 的筛选召回表——**塌方根本不在模型，在机械筛选层**：

| 病 | 根因（全部实测） | 修法 | 前 → 后 |
|---|---|---|---|
| en 抽取塌方 | 英文句号不分句 + 80 字符素材掩码按中文校准，三句正常英文被当粘贴素材整体屏蔽（5 分规则句照样 mask） | `. ` 分句；语言归一权重（CJK×1、latin×0.5）用于掩码与截断 | en assert 筛选召回 **0.57 → 0.98** |
| 撤回漏记 | 引用式撤回只拿 WITHDRAW(+2) 差 1 分——被引用的规则文本没理由含规则设定措辞，它的词汇指向 store | **store 重叠 boost**（句子与已存条目共享内容词汇 +2）；`content_tokens` 一个定义三处共用（boost / referent 提示 / grounding 守卫） | retire 筛选召回 **0.59-0.64 → 0.98-1.00**；L revoke **0.50 → 1.00** |
| 撤回 op 不稳定 | flash 在 temp 0 下同输入翻硬币（contradict / retire+new / 空） | prompt 三分支（带替代→contradict 正向叙述；回默认/裸撤→retire）+ **机械 referent 预解析**：span 标注 `[shares vocabulary with entries [N]]`，模型从"全库找 referent"降为"验证候选" | 归一化探针 6/9 → **9/9**（3 轮） |

**裁判读数（全部最终代码）**：

- L 套件 **0.889 → 0.963**，revoke 0.50 → **1.00**；noise-reject 双 1.00
  （筛选放宽没有伤精度——distractor 误触发 0.17→0.32 的代价由抽取层的
  durability 过滤兜住）。剩余两败是已知旧账：l-diff-001（route-B 宽度绑定）、
  l-exp-001（原子化把双面规则拆两条，跑间方差）。
- perf 重放：**e-09 (en) 终态 11 active/0 retired → 23/13**；e-02 (en) 首测
  17/15；e-01 (zh 对照) 34/3 → 32/6 持平。**canary 零误杀**——守卫按
  content_tokens 收紧（功能词不再能搭桥）后反而更稳。
- 离线 416 绿（新增 7 个筛选回归测试）；污染守卫两次抓住我把语料措辞写进
  docstring，机制有效。

**revocation-shaped（读侧 43 中唯一红灯）的现状**：写侧正解已落地——撤回带
替代时 store 落的是正向规则 + supersede，该 store 形态在 e2e 里不再产生
（探针 9/9）。读侧 check 本身是固定 store 的回归尺，保留原样继续测；
它红不红只反映读路径对既有僵尸形态的容忍度，不再是写路径欠账。

### 第二轮（同日，commit `9e0d1d5`）：E1 确认 + noop 归因 + 两个新修复

**E1 舰队复跑入账**（en 三集 + zh 对照，单跑，按 M7 分频段报出）：
- **STATE（写路径直接频段）：en 0.15-0.27 → 0.54 / 0.60 / 0.61**；
  SUPPRESS 四集全 1.00；en peak active 5-11 → 18-22。
- headline：e-02 0.419/0.418 → **0.513**、e-05 0.556/0.556 → **0.756**
  （两集基线纹丝不动，位移双双超 0.06 入账线）；e-09 0.537（追平其好跑，
  0.298 的链式塌陷未复现）；e-01 对照 0.578（噪声带内，zh 无回归）。
- **下一瓶颈实锤搬家**：real 臂 CARRY 0.00-0.10 vs oracle 臂 0.58-0.77——
  store 变大后读路径织入乏力，这是 ③ 开局的直接证据。

**noop bias ~27% 完成归因，欠账拆解**（逐 probe 真 store 诊断）：
- 残余 noop = (a) 类目桥接裁量题（"billing usage report" 算不算
  "product health report"——需 owner gold 才能计分）+ (b) store 污染
  诱发的瘫痪/误织。perf 的 noop 率指标本身无 applicability gold，
  27% 不能全记为病。
- (b) 的写侧根因当场抓到并修掉两个：**批次丢失 bug**（flash 把用户弯引号
  回显成直引号 → JSON 失效 → 整批正确 ops 被丢；parse_ops 现在带引号
  修复通道）；**task-spec 升格**（「写个X…别用nmap用socket超时3秒」被
  存成所有 Python 脚本的类级规则,污染读决策——rule 1 补判别，复现 3/3 干净）。

**route-B 宽度绑定半修复**：rule 3 补「新增约束落自己的 facet」后
l-diff-001 缺失的 scoped tone 规则已正确产出；语言并入长度规则的
spurious 半边仍在——prompt 一击已用，按两击纪律停手，留作回归尺。

**裁判终态**：L 套件两连跑 **0.963 / 0.981**（revoke 双 1.00、
noise-reject 双 1.00，l-sup-002 单次翻红复跑回绿属方差）；离线 418 绿。

**残余欠账（重排后）**：
1. **读路径织入 @ 大 store**（E1 实锤：real CARRY ≈ 0 vs oracle 0.58-0.77）
   ——③ 的 cap/压缩开局题,与稀释同题
2. l-diff-001 的 spurious 半边（异 facet 并入）——prompt 已停手，
   需要机制层方案（如 facet 一致性机械校验）
3. 类目桥接 noop 的计分 gold——owner 裁量题
4. 跨语言存储：prompt 已钉死「用用户陈述规则的语言存」，未系统复测
5. consolidation：只囤不并（本轮 adds 触发 5 次但 merge 产出少）
6. 卡8 母题：凭证据升宽（owner 已裁定语义，产品未实现）

## ③ latency / cost / 前端 —— 有基线，开局证据已到位

注入体积随 store 线性涨（e-09@24 条已 1900 chars），单次改写 1.6-2.5s。
E1 复跑给出关键新证据：**store 20+ 条时 real 臂 CARRY 掉到 ≈0 而 oracle
臂 0.58-0.77**——瓶颈已从"学不到"搬到"读不出"。cap 策略 / 条目压缩 /
recall 精度是 ③ 的头三个抓手,前端仍是 v0 FastAPI shell + hotkey。

### 第三轮（同日，commit `e32870c`）：CRUD 大修（owner 四项指令全落地）

owner 指令：结构化注入、注入 32→8、dedup/冲突消除前移写路径 CRUD
（改写模型只当最后防线）、**存储语言统一英文**（匹配/去重单语言化，
改写时再渲染回用户语言）。

- **结构化注入**：编号条目 + (applies / aspect / force) 类型字段——store
  本就有的元数据首次进 prompt；输出契约改编号引用。
- **注入预筛 INJECT_CAP=8**：BM25 双侧词根桥（zh 查询 × en 规则零表面
  重叠,「会议纪要」和 "meeting minutes" 共享 root:meeting）+ 新近平局 +
  同 key 保新守卫。依据：全场景同时应织入最大 3 条；32 条平铺注入曾致
  决策瘫痪（该动 5/5 拒动）而 context 仅 ~1.1k tok——是选择难度不是长度。
- **scopes.py**：受控 scope 词表（仅拼写级归一,blog≠article 类目保持
  独立）,写入/匹配/展示三处生效。
- **consolidation 实战化**：冲突消除成为规则 2（同面向不相容 → 从新弃旧,
  写入时 retire）；content_tokens 重叠聚类跨 key/bucket 抓近重复
  （实测三胞胎邮件维护窗口规则对 key 分组不可见）；触发收紧 48/16→24/8。
- **bench 升难**：dilution +2（40 干扰且适用规则最老——选择器+新近陷阱
  合一；en 规则 × zh 任务 × 40 干扰复合）,noop_both_ways +1（40 干扰
  无适用 → 必须 noop）。

**裁判终态（全部真模型）**：
- **robustness 46/46 全绿——conflict-revocation-shaped（此前唯一读侧
  红灯）首次转绿**（结构化字段做到了两轮 prompt 修补没做到的事）。
  跨语言复合 check 首跑抓出 BM25 语言盲区,词根桥修复后族内 5/5。
- L 套件 0.981（英文存储口径；revoke 1.00、noise-reject 双 1.00,
  仅剩 l-diff-001 已知半红）。
- perf 重放 **carry@alive 9/9 全尺寸**（此前 12/14,两个大 store miss
  消失）,canary 零误杀,e-02 19/11、e-01 32/2。
- 离线 425 绿（scopes/跨 key 聚类/保新守卫/编号引用新测试）。

### ③ 开局（同日，commit `38b69cf` + E1 第三轮）

- **prompt 瘦身 30%**（1007→830 tok，全部规则语义保留）：robustness
  **46/46 = 1.000** 满分验收；读路径延迟中位 **1.53s**（此前 1.6-2.5s 带），
  曾 5/5 拒动的 32 条 store nginx probe 现稳定 APPLY。
- **E1 第三轮**（四集，单跑，CRUD 大修后）：

| ep | 基线两跑 | 第二轮 | 第三轮 | real CARRY j/m（二→三） | STATE |
|---|---|---|---|---|---|
| e-02 | .419/.418 | .513 | .499 | .00/.00→.00/.29 | .54→.50 |
| e-05 | .556/.556 | .756 | .614 | .67/.00→.33/.50 | .60→.51 |
| e-09 | .535/.298 | .537 | **.722** | .00/.00→**.53/.75** | .61→.64 |
| e-01 | .565/.520 | .578 | **.663** | .10/.10→.36/.40 | .63→.63 |

  headline 四集均值 0.596→0.625（+0.029，低于 0.06 单跑入账线——headline
  平）。**但分频段方向一致且全员**：real 臂 CARRY-mech 0.00-0.10 →
  **0.29-0.75 四集全升**——"读不出"的欠账实质性位移；e-09 real 反超
  oracle 臂（0.53 vs 0.50），e-01 noop 0.33→0.17。real vs oracle 差距
  分集分化（e-02 仍 0.00 vs 0.73）。
- **consolidation 首次实战**：adds/ACTIVE 触发合计 17 次、产出 op
  （ACTIVE 分支史上首次在 11/12 集以外常态触发——死代码欠账消解）。
  **新观察（下一步 #1）**：e-05 peak active 19→11、STATE 0.60→0.51,
  e-02 STATE 亦小降——嫌疑是 merge 改写文本时**丢数字锚**（STATE 按
  distinctive 子串对齐）与冲突消除过杀。修法候选：CONSOLIDATE prompt
  加「合并文本必须保留全部数字上限与具名格式」+ merge 前后 distinctive
  存续机械校验。
- 前端 v0 盘点：FastAPI 全 API + 636 行 web shell + macOS axtext 热键
  守护（就地替换,无反馈 UI）。交互议程（owner 决策项）：改写预览/确认 vs
  直接替换；命中规则的可见性（信任与纠错入口）；撤回入口（Cmd+Z 语义）；
  store 管理界面（查看/编辑/退役规则）。

### ③ 第二批（2026-07-30，commit `bb1c15d`）：三项剩余全落地

1. **consolidation 锚保留**：prompt 条款 + 零 LLM 校验（merge 产物丢任何
   数字锚 → 整个丢弃,源条目保活;数字不同的"合并"本就是冲突该走从新弃旧）。
   E1 round-4 在动机集上验证：e-05 STATE 0.51→0.57、peak active 11→15。
2. **edits 线协议（延迟档）+ 尺寸路由**：模型只发插入增量,产品机械拼接;
   锚必须唯一逐字、引用/粘贴区内禁止插入、任何缺陷降级 noop。实测长粘贴
   **2437→1123ms（−54%）**,18 次调用零 splice 失败。**全量启用曾把
   injection 族打到 1/4**（edits 模式在攻击相邻短任务上比 full 的谨慎
   noop 更敢动,一次 prompt 修补无效）——按纪律停手改机械路由：
   <200 tok 走 full（46/46 已入账行为）,长输入走 edits（收益主场）。
   路由版 robustness **46/46 = 1.000**。
3. **E1 round-4**：headline 均值 0.614 vs round-3 0.625,单跑噪声内持平。
   CRUD 时代的频段声称凑齐两跑,**口径修正（2026-07-30）：逐集
   CARRY-mech 分母只有 2-12 个判定点,区间（r3 0.29-0.75 / r4
   0.00-0.60）不能当分数读——正确声称用合并判定点：real 臂
   CARRY-mech 合并 1/31 (0.03) → r3 16/31 (0.52) / r4 12/31 (0.39)**,
   两跑一致量级位移,入账。单集 headline 方差仍大（e-09 .722→.644）,
   维持"单跑只入频段方向"纪律。

### 记分呈现裁定（owner，2026-07-30）

**对 owner 汇报只报两个数,其余全部降为诊断视图**：
1. **per-task 完美率**：该提的记忆全提、不该提的全没提的任务占比
   （零判定点任务不计入分母）；
2. **per-memory 命中率**（=CARRY）：该被提到的记忆里实际被提到的比例。

已实现进 `run_episodes.py` 头两行输出与 snapshot 的 `owner_metrics` 字段。
现状（real 臂,r3/r4 两跑）：per-task **0.38 / 0.39**,per-memory
**0.35 / 0.29**。频段/套件分数继续采集,仅作追因用。

## 建议的下一步

1. 前端交互（owner 四项裁定后动工：预览/确认、命中规则可见性、撤销、
   store 管理界面）。
2. injection 族补长输入攻击 check（edits 路径的对抗覆盖目前偏薄）。
3. e-01 zh 存量 store 的 STATE 波动观察（.63→.56,单跑,下轮复跑看）。

## 基建备忘

- 本 session commit 链：`5bdee98`（筛选层机制）→ `9e0d1d5`（parse 修复+
  durability）→ `e32870c`（CRUD 大修）→ `38b69cf`（prompt 瘦身）
- 可视化机制报告（框图/流程图/数据）已发布为 Artifact，随攻坚数据更新
- backlog：E1 跨 run 塌陷闸、Ark 404 重试策略；21-28 桶 noop 88% 旧复测
  项被 perf 重放覆盖（该桶本次 noop 8%，n 仍小）

## 第五轮（2026-07-30 下午）：oracle 提分攻坚（owner 指令：0.9+，先审 ground truth）

审计口径：4 集（e-01/02/05/09）全部 probe 轮 should_fire 判定点逐点重放
gold store → translate() → judge。起点 **0.54**（29/54）。

### Ground-truth 审计结论（先于一切修改）

25 个 miss 逐条定性后确认 **5 处 gold 缺陷**，全部修正并留档：
1. `e01-c16` pylint 规则 scope 少标 `code_lang=python`，在 Go 任务上算
   should_fire（工具语义上不可能满足）→ scope 收窄 + s40 除名。
2. `e02-c01`「keep it friendly and welcoming」对话原文明确限定
   client-facing 摘要场景，catalogue scope 却是 ANY → 与 c00（stop being
   polite）在内部邮件轮同场竞争，模型按注入内容翻旧条被冤判 → scope
   改 `task=report`。
3. `e-02 s59` 期待 11 句上限被织入，但同轮 active 还有更新且更专属的
   「postmortem 至少 17 句」（seq 46 > 42）→ 不可满足对，s59 除名。
4. `e-09 s24/s28` 期待「标题别全大写」，但更强的活规则「no headings」被
   正确携带后该期待不可证伪 → 两轮除名。
5. `e01-c21` 节点三向自相矛盾（clause 至少13词 / text 8-13词 / coords
   cmp=max）且 clause 缺宾语 → clause 改自含语义「生成的每个句子至少13个词」。

另修 runner：**gold store 补写侧镜像的冲突消除**（同 (key,scope) 只留最新，
无 key 不参与）——此前 oracle 臂会把产品写路径本应 retire 的矛盾对
（polite vs friendly）原样递给模型。offline fixture 的同 key 偷懒元数据
一并修正（432 全绿）。

### 机制归因与修法

选择层（13/25 miss 是 top-8 预筛砍掉 gold）：**逐点排名取证显示漏选规则
BM25 全部 0 分**——风格/格式类规则与任务文本零词面重叠，排序退化为
recency 抽签。零 LLM 变体上限 0.80（contract-lane），**flash 预选器也是
0.80**（111 轮实测）——选择盲区与织入盲区同源。结论：cap=8 的代价是
固定的 ~0.20 选择损失，文本手段修不动。

织入层（prompt 两击 + 两个机械修复）：
1. prompt 击一：完整性条款（数字上限类最易丢，逐条全织、数字保真）+
   极性保真（avoid/prohibit 必须以禁止形式织入）。
2. prompt 击二：冗余不豁免 + 规则多不是 noop 理由。
3. 机械：`rewrite_dropped_user_text`（full 线保真守卫杀掉合格改写）时
   **降级重试一次 edits 线**——插入式输出构造上保住原文；仅限 full 已判
   apply 的场景，noop 不重试（保住 injection 已入账行为）。
4. 机械：**攻击形态预检**（_ATTACK_PAT）——prompt 击一曾把
   embedded-instruction check 打回 45/46（完整性压过攻击邻近谨慎，两击已
   用尽），改为零 LLM 元指令模式守卫直接 noop；744 个 episode 轮零误伤。

### 数字（owner 口径）

| 配置 | per-task 完美率 | per-memory 命中率 |
|---|---|---|
| oracle @ 注入 cap=8（现行产品配置） | 24/39 = **0.62** | 33/50 = **0.66** |
| oracle @ 全量注入（≈21-33 条结构化） | 33/39 = **0.85** | 43/50 = **0.86** |

（起点 0.54 → 全量注入 0.86；剩余 7 个 miss 是 flash 织入优先级硬尾巴：
verb-buried 类抽象规则 0/4、KPI 前瞻补充、多码规则丢一条、1 轮 noop 抖动。）

门禁：robustness **46/46**（含 injection 回归修复）、offline pytest
432、污染守卫通过。

### 待 owner 裁定

0.9+ 在 cap=8 下不可达（选择上限 0.80 × 织入 ≈0.86 ⇒ ~0.7 天花板）。
全量注入下 0.86，且"32 条弄糊涂"的旧现象在结构化注入+完整性 prompt 下
已基本消失（仅剩偶发 noop 抖动，均值 25 条 ≈ 1k tok）。**建议：读路径
注入上限从 8 回调到全量 active（或 24），选择预筛保留为安全阀**——
需要 owner 对 7-29 "降到 8 条" 裁定的更新授权。
