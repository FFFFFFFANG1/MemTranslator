# 项目状态与下一步（2026-07-29）

三个宏观阶段对照：**① 确定软件层功能 → ② 完善 memory 机制 → ③ latency/cost/前端交互**。
当前位置：**① 基本收口（剩一个契约决定），② 进行中（读路径已过硬，写路径是弱侧），③ 已有基线数据、未动工。**

## ① 软件层功能 —— 基本完成

- 产品形态稳定并经受住了两代 bench：热键 → 输入框内改写 → 用户编辑 → 发送；
  改写只增不删；下游 agent 永不见记忆。
- 契约本周收拢成 owner 口径：**(任务, 偏好记忆) → 对当前任务最适配的 task
  requirement**，三个动词等级 noop / carry / **adapt**。adapt（要求实例化）
  已实测存在（robustness instantiation 5/5，对比归因判定）。
- **唯一未决**：adapt 与 Suite T `AUTO_NO_INVENTION`（改写不得引入无出处约束）
  的契约冲突——tier-2 实例化会被 T 扣分。需要 owner 拍：放开"意图内展开"豁免，
  或维持严格 no-invention。这决定 ADAPT 频段进不进计分。

## ② memory 机制 —— 当前主战场，约半程

**先修好了尺子**（这是本周的主要工作量）：
- bench v2：robustness 8 族 40 check（0.975）+ perf 真实重放（canary 双头仪器：
  稀释曲线 + 误杀检测）。oracle-first 审计纪律把答案缺陷 0.544→0.077。
- bench_archive：校准过的 468 条语料、图层、审计链，作原料库。

**已修的机制**（均经回归验证）：
- 读路径：recall 换 BM25、scope 进 prompt（E 0.703→0.786）
- 写路径：deixis 误杀三层修复（prompt 逃生口 + grounding 护栏 + 脚手架词表），
  同一 bug 两条死路都由 perf canary 抓获；L 保持 0.889，diff-supersede 1.00

**读路径现状：过硬。** carry@alive 全尺寸满分（store 4→36），措辞/顺序不变性、
稀释、注入防御、跨语言读取全绿。

**写路径现状：弱侧，按优先级排的欠账：**
1. 冲突诱发 noop（robustness 唯一红灯）：两条冲突偏好并存时拒动而非从新
2. noop bias ~27%（干净 prompt 下仍拒动）——读写之间的决策层
3. en-persona 抽取塌方：同长历史只学到 10–11 条 vs 中文 34–36 条
4. 撤回漏记（~31%）/ L revoke 0.50——僵尸的源头
5. 跨语言存储（中文规则存成英文转述）
6. consolidation：ACTIVE 分支死代码；只囤不并（无 widen/merge 动力）
7. 卡8 母题：凭证据升宽（owner 已裁定语义，产品未实现）

## ③ latency / cost / 前端 —— 有基线，未动工

perf 套件已在产出曲线：注入体积随 store 线性涨（82→2361 chars），单次改写
1.4–3.5s。热键场景对延迟敏感，这两条是 ③ 的头两个抓手（cap 策略/条目压缩；
prompt 瘦身）。前端仍是 v0 FastAPI shell + hotkey，交互优化未开始。

## 建议的下一步（顺序）

1. **②-读的收尾**：修 conflict→noop 与 noop bias（都是 translate prompt 层，
   用 robustness 套件小步迭代，便宜）
2. **契约拍板**：adapt vs no-invention（10 分钟的决定，解锁 ADAPT 频段与 T 判据）
3. **②-写的攻坚**：en 抽取塌方 + 撤回漏记（最难，perf 重放 + L revoke 是现成尺子）
4. **进入 ③**：以本周 perf 曲线为基线做 cap/压缩实验；前端交互随后

## 基建备忘

- 全部推送至 origin/dev（tag `checkpoint-20260729-deixis-fix`）；测试 408 绿
- state.json 合并写入、perf 时间戳存档已修
- backlog：E1 跨 run 塌陷闸、Ark 404 重试策略、21-28 桶 noop 88% 待复测（n=2）

## 契约裁定（owner，2026-07-29，本 session 收尾）

**adapt vs no-invention：全面放开。** 任何已存规则都允许"意图内展开"——改写可以
引入规则文本之外的具体内容，只要满足蕴含关系：**遵守展开后约束的输出必然也遵守
原规则**。具体规则（数字上限、具名格式）同样适用，不做分层限制。

落地清单（下一 session 执行）：
1. `TRANSLATOR_SYSTEM` 规则 2 改写：no-invention 松弛为 no-*ungrounded*-invention
   ——新增约束必须蕴含-有出处（specializes a stored requirement），
   无出处约束仍然禁止。
2. Suite T `AUTO_NO_INVENTION` 判据改三元：逐字有出处 / 蕴含有出处 / 无出处，
   前两者过。**metric_version 随之 bump**（T 历史分数不可比）。
3. ADAPT 频段从 report-only 进入 robustness 计分（instantiation 族已就位）。
4. 风险记录：可预测性是 position anchor 第一优先级，全面放开后同请求同库的
   改写方差可能上升——robustness invariance 族是哨兵，若 equiv-group 开始失败，
   回到分层方案。

### 落地执行记录（2026-07-29，裁定后 session）

1. ✅ `TRANSLATOR_SYSTEM` 规则 2 改写：invent 禁令松弛为「新增必须有出处，
   出处不要求逐字——允许 specialize（蕴含式展开），无出处仍禁止」。
2. ✅ Suite T `AUTO_NO_INVENTION` 改三元（(a) 逐字有出处 / (b) 蕴含有出处 /
   (c) 无出处，a+b 过）；`bench_archive` METRIC_VERSION 2→3；make_audit
   增加 v2 措辞映射，旧 snapshot 仍可复审。注意：archive 已封存，T 不重跑，
   新判据对未来 T 运行生效。
3. ✅ ADAPT 计分口径写进 bench/README 计分节（instantiation 族本就在
   state.json 计分，此处消掉 report-only 的暧昧，正式背书）。
4. ✅ 方差哨兵（invariance equiv-group，失败即回退分层）记入 bench/README。

回归：离线测试 408 绿；robustness 全量 39/40 = 0.975，与放开前基线持平——
唯一红灯仍是 conflict-en-latest-tone（欠账 #1 的冲突诱发 noop，非本次引入），
invariance 9/9（方差哨兵绿）、instantiation 5/5。松弛规则 2 未引起任何回退。

### 续：欠账 #1（冲突诱发 noop）修复（同 session）

- 根因：recall 本就按 created_at 升序排（[recall.py:41]），但 prompt 从未告知
  模型列表顺序的时间含义，也没有冲突处理规则——两条活冲突偏好并存时模型走
  noop 兜底。
- 修法（都在 translate prompt 层）：新增规则 8（越靠后越新；冲突从新弃旧、
  绝不双注入、绝不因冲突 noop）+ user prompt 标注 "oldest first"。
- 修后全量暴露一个新边缘行为：idempotence 场景偶发 apply 但产物与输入逐字
  相同。产品层加机械护栏：polished == 输入 → 降级 noop（reason
  `rewrite_unchanged`），附离线测试。
- 结果：**robustness 40/40 = 1.000（首次全绿）**，离线 409 绿。
  按 README 纪律，全 1.0 = 该给套件升难度了（Critic 加 trace，不删旧），
  尤其 conflict 族该扩：en/zh 混合冲突、三条链式取代、scope 限定冲突。
- 欠账重排：#1 已清；#2 noop bias 的尺子在 perf 重放（robustness
  noop_both_ways 全绿测不出 27% 偏置），归入写路径攻坚一并做。

### 续 2：conflict 升难度（同 session）——新增一个真红灯

按"全 1.0 = 测试太弱"纪律给 conflict 族加了三个 check：链式取代（120→90→60，
必须只注入 60）✓、跨语言冲突（zh 旧正式 × en 新 casual）✓、**撤回式新规则 ✗**。

**revocation-shaped（新的已知红灯，42/43 = 0.977）**：库存两条活规则
「周报每条要附数据支撑」+「周报别再要求数据支撑了，列清楚要点就行」，任务
「把这周的工作整理成周报」→ 模型稳定 noop（3 次重放一字不差），丢掉了新规则的
正半句「列清楚要点」。调查记录：
- 说辞是"用户没提供实际工作内容"——事后合理化：同样引用缺席材料的 zombie
  check（新规则正面开头）一直过。真实触发模式是**否定开头的规则文本**让 flash
  把整对规则读成"话题已取消"。
- 两次 prompt 修补（规则 8 撤回条款、规则 1 缺材料不 noop 条款）都没翻红，
  模型说辞不变。已停手，避免向 bench case 过拟合。两条款保留：语义正确、
  noop_both_ways 全绿无副作用。
- **定性：这是写路径欠账 #4（撤回漏记 31%）的读侧影子。** 正解是写路径把撤回
  话语规范化成正面规则并 supersede 旧条（diff-supersede 已 1.00——写路径抓到
  就不存在此场景）；读路径对 zombie 库的这层防御在 flash 上有真实上限。
  写路径攻坚时以此 check 为读侧回归尺。
