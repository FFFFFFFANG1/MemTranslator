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
