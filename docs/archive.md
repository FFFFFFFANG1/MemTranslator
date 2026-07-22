# Archive：2026-07-21 ~ 07-22 第一轮建设记录

> **本文档只做记录。文中记载的所有做法都与项目定位（[position_anchor.md](../position_anchor.md)）有偏差，不作为任何后续工作的依据。** 2026-07-23 起项目清空重建，一切从 anchor 从零搭建；本文之外的旧文档与 pilot 代码已全部从工作树删除，仅存于 git history。

## 恢复点（git history，永久可考古）

| 内容 | 位置 |
|---|---|
| 清理前 dev 完整快照（全部旧文档 + pilot + proto） | `ddaf46a` |
| pilot harness 最后完整版（含 B2 结果与实例数据） | `cab2cce` |
| Typeless 逆向分析权威版（151 行，含 §8 本地 app 逆向一手证据） | **research 分支**（`fc1d530`，siriux 2026-07-22 有意移置，保留不动） |
| anchor 入 main | `d129816` |
| refactor plan（初版 `83a3da0`，修正版 `bebf6d5`，已被本次清零决定取代） | main history |

## 时间线与决策链

1. **07-21**：立项。idea.md（position 文稿）→ diagnosis.md 判「两周 PrefEval pilot 定生死」→ pilot plan（四臂 × 两档下游，G1–G3 预注册判据）+ baseline plan（Mem0/Graphiti 六臂，B0–B4）。同日建成 proto（memory store + 2-call write path + typeless 式 demo）与 pilot harness。
2. **07-22 晨**：pilot 跑了 B2 dry-run（20 正例 + 5 负例）。同日 FFFFFFFANG1 在 main 立 position_anchor.md：产品优先、PrefEval 主体是 content preference 不作主 bench、只做 delivery/requirement preference。
3. **07-22 晚**：拍板 D1 取消全量 run、D2 删除 pilot/、D3 直接改 dev。refactor plan 原定「冻结 banner + 复盘 memo + TODO 重写」多文档方案。
4. **07-23**：siriux 裁定改为清零方案——记录归并进本文一份，其余全删，从 0 重建。refactor plan 随之作废。

## Pilot 数字（B2 dry-run，n 小，不可再生的一手记录）

正例 20 条（PrefEval，content preference 为主），四臂 = A0 无记忆 / A1 system 注入 / A2 user 注入 / A3 translator：

- **adherence**：A3 75%（强下游）/ 70%（弱），注入臂 100% / 80–85%，A0 20% / 5%。配对差 A3−注入（强下游）= −25pp，95% CI [−45, −5]。
- **FAR（负例 5 条）**：A3 20%，注入臂 40–60%，A0 0%；P(noop|neg) = 4/5。
- **下游 input token（均值/实例）**：A3 58/39，注入 302–326/221–246（约 1/5）。
- **translator 行为**：P(apply|pos) = 14/20；parse error 0；保真 judge 判核心任务改变 0、越权加需求 0。

当时的解读：按旧判据 G1 趋向 NO-GO；按 anchor 视角是战场选错（content-pref 的 adherence 不是我们的指标），而负例纪律与 token 成本是产品面亮点。样本过小，仅方向性参考。

## 被清理文档一览（一行一档，全文见 `ddaf46a`）

- `docs/idea.md` — 原始 position 文稿（memory 监督信号、CRUD 七情形、query-time translation 设想）
- `docs/diagnosis.md` — 新颖性/评测诊断，结论「两周 pilot 定生死」（已被 anchor 推翻）
- `docs/2026-07-21-pilot-plan.md` — PrefEval 四臂 pilot 实施 plan（Tasks 0–13，G1–G3 预注册）
- `docs/2026-07-21-baseline-plan.md` — Mem0/Graphiti 六臂对照方案（B0–B4，未执行到 B3+）
- `docs/prefeval-notes.md` — PrefEval 数据布局核验（V1–V5 假设逐条核验结果）
- `docs/longmemeval-pref-probe.md` — LongMemEval preference 类目抽查笔记（副战场，已取消）
- `docs/baseline-b0-memo.md` — B0 环境冒烟记录（mem0ai / graphiti-core 安装与配置定案）
- `docs/pilot-results-b2-dryrun.md`、`docs/pilot-results-b2-neg.md` — B2 数字原表（要点已录入上节）
- `docs/memory-design.md` — memory 层设计 v0：MemoryEntry schema、append-only 状态机、批式 extract + 单次 consolidate 的 2-call write path、0 生成式 call read path、预算核算
- `docs/hms-mandol-notes.md` — HMS / Mandol 代码深读与借鉴决策（wrong-case dump、match-judge confidence 等）
- `docs/2026-07-22-refactor-plan.md` — 被本次清零取代的 refactor plan（拍板记录 D1–D3 在其 §1）
- `TODO.md` — 旧任务清单（v0=pilot 的旧版本术语）
- `pilot/` — 全部 harness 代码、测试与实例数据

## 旧 proto 沉淀的产品决策（记录，不预设后续沿用）

- typeless 式人在环：polished input 落回输入框可编辑再发；编辑 diff 本身是反馈信号
- default profile fallback：空态不接受 no-op，出厂条目 + learned 条目分层
- translator / write path 全部 flash 档（haiku）；下游任意强模型
