# 项目状态与下一步（2026-07-29，session 收口版）

三个宏观阶段对照：**① 确定软件层功能 → ② 完善 memory 机制 → ③ latency/cost/前端交互**。
当前位置：**① 已收口（契约裁定并落地），② 读路径章节关闭、写路径攻坚是下一主战场，③ 已有基线数据、未动工。**

## ① 软件层功能 —— 已收口

- 产品形态稳定并经受住了两代 bench：热键 → 输入框内改写 → 用户编辑 → 发送；
  改写只增不删；下游 agent 永不见记忆。
- 契约 owner 口径：**(任务, 偏好记忆) → 对当前任务最适配的 task requirement**，
  三个动词等级 noop / carry / **adapt**。adapt（要求实例化）已实测存在
  （robustness instantiation 5/5，对比归因判定）。
- adapt vs no-invention 的最后一个契约冲突已由 owner 裁定并全部落地
  （见文末裁定记录）。**① 无未决项。**

## ② memory 机制 —— 读路径章节关闭，写路径是主战场

**尺子**：
- bench v2：robustness 8 族 **43 check（0.977）** + perf 真实重放（canary
  双头仪器：稀释曲线 + 误杀检测）。oracle-first 审计纪律把答案缺陷 0.544→0.077。
- bench_archive：校准过的 468 条语料、图层、审计链，作原料库。
  METRIC_VERSION 3（T 判据三元化后与 v2 分数不可比）。

**读路径现状：章节关闭。** carry@alive 全尺寸满分（store 4→36），措辞/顺序
不变性、稀释、注入防御、跨语言读取、冲突从新、幂等全绿。本 session 清掉了
冲突诱发 noop（欠账原 #1），随后升难度又抓到一个**已知红灯**：

- **revocation-shaped（43 中唯一红灯）**：否定开头的撤回式规则（「周报别再
  要求数据支撑了，列清楚要点就行」与旧规则并存）→ flash 稳定 noop，丢掉
  正半句。三次重放说辞一字不差（"缺工作内容"，事后合理化——正面开头的同形态
  zombie check 一直过）。两次 prompt 修补无效后停手，避免向 bench 过拟合。
  **定性：写路径撤回漏记的读侧影子**——写路径把撤回规范化成正面规则并
  supersede（diff-supersede 已 1.00），此场景即不存在。留作写路径攻坚的
  读侧回归尺。

**写路径现状：弱侧，按优先级排的欠账（重排后）：**
1. en-persona 抽取塌方：同长历史只学到 10–11 条 vs 中文 34–36 条
2. 撤回漏记（~31%）/ L revoke 0.50——僵尸的源头，也是 revocation-shaped
   红灯的正解所在
3. noop bias ~27%（干净 prompt 下仍拒动）——尺子在 perf 重放
   （robustness noop_both_ways 全绿测不出它），随写路径攻坚一并做
4. 跨语言存储（中文规则存成英文转述）
5. consolidation：ACTIVE 分支死代码；只囤不并（无 widen/merge 动力）
6. 卡8 母题：凭证据升宽（owner 已裁定语义，产品未实现）

## ③ latency / cost / 前端 —— 有基线，未动工

perf 套件已在产出曲线：注入体积随 store 线性涨（82→2361 chars），单次改写
1.4–3.5s。热键场景对延迟敏感，这两条是 ③ 的头两个抓手（cap 策略/条目压缩；
prompt 瘦身）。前端仍是 v0 FastAPI shell + hotkey，交互优化未开始。

## 建议的下一步（顺序）

1. **②-写的攻坚**（下个 session 开新篇）：en 抽取塌方 + 撤回漏记。现成的尺子：
   perf 重放、L revoke、revocation-shaped check（读侧回归）。
2. **进入 ③**：以本周 perf 曲线为基线做 cap/压缩实验；前端交互随后。

## 基建备忘

- 全部推送至 origin/dev：`240e07c`（契约落地）→ `2c57f2b`（欠账 #1 清）→
  `b04a8ca`（conflict 升难度）；离线测试 409 绿
- state.json 合并写入、perf 时间戳存档已修
- backlog：E1 跨 run 塌陷闸、Ark 404 重试策略、21-28 桶 noop 88% 待复测（n=2）

## 契约裁定（owner，2026-07-29）——已全部落地

**adapt vs no-invention：全面放开。** 任何已存规则都允许"意图内展开"——改写可以
引入规则文本之外的具体内容，只要满足蕴含关系：**遵守展开后约束的输出必然也遵守
原规则**。具体规则（数字上限、具名格式）同样适用，不做分层限制。

落地执行记录（同日，commit `240e07c`）：
1. ✅ `TRANSLATOR_SYSTEM` 规则 2：invent 禁令松弛为「新增必须有出处，出处不
   要求逐字——允许 specialize（蕴含式展开），无出处仍禁止」。
2. ✅ Suite T `AUTO_NO_INVENTION` 改三元（逐字有出处 / 蕴含有出处 / 无出处，
   前两者过）；`bench_archive` METRIC_VERSION 2→3；make_audit 加 v2 措辞映射，
   旧 snapshot 仍可复审。archive 已封存不重跑，新判据对未来 T 运行生效。
3. ✅ ADAPT 计分口径 + 方差哨兵（invariance equiv-group，失败即回退分层）
   写进 bench/README 计分节。
4. ✅ 回归：robustness 与放开前基线持平，invariance 9/9——放开未推高方差。

## 本 session 读路径修复记录（细节在 git log）

- **冲突诱发 noop**（`2c57f2b`）：根因是 recall 本就按 created_at 升序排，但
  prompt 从未告知模型顺序的时间含义、也无冲突规则。补规则 8（越靠后越新；
  冲突从新弃旧、绝不双注入、绝不因冲突 noop）+ user prompt 标注 "oldest
  first"。conflict 全绿，robustness 一度 40/40 首次全绿。
- **无变化 apply 护栏**（同 commit）：idempotence 场景偶发 apply 且产物与输入
  逐字相同——产品层机械降级为 noop（reason `rewrite_unchanged`），附离线测试。
- **conflict 升难度**（`b04a8ca`）：+3 check——链式取代（120→90→60）✓、
  跨语言冲突（zh 旧正式 × en 新 casual）✓、撤回式 ✗（即上述已知红灯）。
  终态 **42/43 = 0.977**。
