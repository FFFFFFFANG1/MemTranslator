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

**残余欠账（重排后）**：
1. noop bias ~27%（干净 prompt 下仍拒动）——本次 e-02 重放 noop 率 0.50
   仍可见；尺子在 perf 重放，下一主攻
2. route-B 宽度绑定（l-diff-001 形态：用户加的约束该 new-scoped 却
   contradict 进了老规则）
3. 跨语言存储：prompt 已钉死「用用户陈述规则的语言存」，未系统复测
4. consolidation：ACTIVE 分支死代码；只囤不并（e-01 终态 32 active 仍未并）
5. 卡8 母题：凭证据升宽（owner 已裁定语义，产品未实现）
6. 新观察：perf 重放 carry@alive 12/14，两个 miss 出现在 en store 长到
   18-23 条之后——写路径学得多了，稀释问题从理论变成实测（与 ③ 的 cap
   策略同题）

## ③ latency / cost / 前端 —— 有基线，未动工

注入体积随 store 线性涨（本次 e-09@24 条已 1900 chars），单次改写 1.6-2.5s。
en store 现在能长到 20+ 条，cap 策略/条目压缩从"将来"变成"下一个瓶颈"。
前端仍是 v0 FastAPI shell + hotkey。

## 建议的下一步（顺序）

1. **E1 舰队复跑**（en 三集 e-02/05/09 + zh 对照）：写路径修完后 STATE/CARRY
   频段应显著位移，这是攻坚成果的 suite 级确认（run 间噪声基线 0.03，
   位移 < 0.06 不入账）。
2. **noop bias 攻坚**（残余 #1）+ route-B 宽度绑定（#2）。
3. **进入 ③**：稀释已实测（残余 #6），cap/压缩实验接上。

## 基建备忘

- 本次全部落在 `5bdee98`（signals/extraction/server/providers + 7 测试 +
  3 份 L snapshot + perf_results）
- backlog 不变：E1 跨 run 塌陷闸、Ark 404 重试策略；21-28 桶 noop 88% 的
  旧复测项被本次重放覆盖（该桶本次 noop 8%，n 仍小）
