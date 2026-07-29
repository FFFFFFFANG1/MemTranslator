# 项目状态与下一步（2026-07-29，写路径攻坚后更新）

三个宏观阶段对照：**① 确定软件层功能 → ② 完善 memory 机制 → ③ latency/cost/前端交互**。
当前位置：**① 已收口。② 读路径章节关闭、写路径两大欠账（en 塌方 + 撤回漏记）已清，
残余欠账见下。③ 已有基线数据、未动工。**

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

## 建议的下一步

**进入 ③**,从读路径织入 @ 大 store 开刀（残余 #1）：recall 精度实验
（BM25 排序质量 vs cap 32 的取舍）、注入条目压缩、延迟预算。尺子现成：
E1 real vs oracle 的 CARRY 差距、perf 稀释曲线。

## 基建备忘

- 本 session 两个 commit：`5bdee98`（筛选层机制修 + 撤回归一化）、
  `9e0d1d5`（parse 修复 + durability/breadth prompt + E1/L 证据）
- 可视化机制报告（框图/流程图/数据）已发布为 Artifact，随攻坚数据更新
- backlog：E1 跨 run 塌陷闸、Ark 404 重试策略；21-28 桶 noop 88% 旧复测
  项被 perf 重放覆盖（该桶本次 noop 8%，n 仍小）
