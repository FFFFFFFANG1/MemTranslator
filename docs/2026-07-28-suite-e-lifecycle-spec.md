# Suite E 生命周期化终版方案（2026-07-28）

> 取代 `2026-07-26-bench-scaleup-spec.md` 的「Suite R 是新套件」框架。owner 2026-07-27 裁定：
> **T/L 测功能，E 测性能；生命周期套件就是 Suite E 本身，不存在独立的 Suite R。**
> 人工标注预算硬顶 **10 条**，`双人签字` 与 `人工逐条` 全部作废，由图导出 + 生成式语料顶上。
>
> 本文由一次 8-agent 设计工作流产出（4 条并行设计 → 3 个对抗视角复核 → 合成），
> 合成体逐条标注了 **实测 / 建模 / 假设**。其中以下几条我在 dev 工作树上二次核过，属实：
> `signals._KEY_LEXICON` 只有 14 个词根；`translate._requirement_block` 只打印 `- [id] text`，
> scope 从不进 prompt；`consolidate.should_consolidate` 是 `active > 48 **或** adds >= 16`；
> persona 文件确实存了 `final`。
>
> 上游材料保留在 `2026-07-26-bench-scaleup-spec.md`：**§1 语料源裁定表逐字继承，一个字不改**
> （许可裁定不受这次方向翻转影响）。该文档其余部分以本文为准。

>
> **许可裁定（owner 2026-07-27）**：项目不商用，最终大概率 MIT。§4.7 那条「clean-room 论证需要
> 签字」不再阻塞，BY-SA 源解冻。注意两点仍然成立：(1) 生成管线本来就是 skeleton clean-room，
> repo 内零第三方原文，所以许可问题在设计上已经基本蒸发，这次放宽真正解锁的是**抓取阶段可以读
> NC 源**（AgentIF、CFBench 等），语料池变宽；(2) MIT 分发 + NC 语料逐字入库仍然冲突，所以
> 「不入原文、只入变异后的命题」这条工程约束不动——它同时还是反 backbone 记忆的手段。

---

以下所有代码事实我在 `dev` 工作树上逐条跑过或读过，标注为**实测**；模型化数字标注为**建模**；未核的标注为**假设**。

> ## ⚠️ M1 已跑，判决 FAIL —— 本文第 2 节的 M4/M5 暂停
>
> `docs/2026-07-28-m1-separation-result.md`。死条目陷阱有效（注入时泄漏 0.85），
> 但 `real - recency-32` 的 SUPPRESS 差是 **+0.00**，预注册门槛要 ≥ 0.15。
> 三处直接影响本文的修正：
> (1) **distinctive 码活不过改写**，`E-mech` band（权重 0.50、卖点是零 judge
> `not_contains(distinctive)`）建在不成立的前提上，必须改用语义对立对；
> (2) `_scope_ok` 的观测贡献实测为零——越界规则 60/60 进 prompt、0/60 被带出，
> scope 应退出计分或先修产品；
> (3) 「CARRY 对注入集合不敏感」是 n=6 的假象，n=60 实测 0.70/0.63/0.50 单调下降，
> 据此把 CARRY 权重压到 0.25 的决定要重做。
>
> M0/M2（harness 与图层）不受影响，仍可开工。

---

## 0. 两条与题面不符的实测，先说，因为它改变结论

**实测**（`bench/results/` 最新快照）：T 0.933（`T-20260727-152607`）、L **0.889**（`L-20260728-001140`）、E **0.703**（`E-20260728-002242`）。按现行 `WEIGHTS = {"T":0.4,"L":0.3,"E":0.3}`：overall = **0.851 ≥ 0.80**，且每 suite ≥ 0.70。**今天的 gate 是 PASS，不是 FAIL。**

这不是好消息，是最强的换 suite 论据：一个 8 persona × 3 规则、每 run 112 个判定点、`writer-zh` 单条 spread 0.583 的玩具 suite，已经把 gate 顶过线了。继续用它，下一次发布决策将由一个测不出生命周期的数做出。

**实测**：`bench/gen/` 只有 `judge-audit.md` / `prefeval-notes.md` / `prompts.md` 三个 md；全树无任何 harvest jsonl（`find . -name "*.jsonl"` 只命中 `data/store.jsonl`、`data/events.jsonl`、`bench/cases/{translate,extraction}/cases.jsonl`）。thin-bucket 文档自述的 189 条，落盘的只有文中引用的 17 句；四个胖桶为零。**语料在 L0（源许可裁定完成）与 L1 之间，实际存量按零估。** 两份设计对此的判断都成立，按「已提取 189 条」排期会低估一整个里程碑。

---

## 1. Suite E 变成什么，高分能声称什么

Suite E 从「8 个 persona 各带 3 条规则的改写命中率」变成**生命周期回放套件**：12 条 episode，每条一份 40 项的 delivery-requirement catalogue 折进 ~65 轮真实形态的用户历史（其中 26 轮是请求与规则同处一个字符串的 carrier 轮），在 8 个 checkpoint 上以 chained / segment / oracle 三模式打分；任意前缀的 gold 由构造边 fold 出来，不二次手写；**headline 的主体是「用户撤销/改写之后，系统有没有停止应用旧规则」，不是「系统有没有应用规则」。**

高分能声称的：在一段 60+ 轮、活跃条目峰值越过 `RECALL_CAP=32` 的历史上，系统对 delivery requirement 的**失效传播**是正确的——被撤回、被推翻、被合并的规则不再进入改写；且这一半断言 **零 judge 在环、完全可复现**（`not_contains(distinctive)` 这类词法判据），一个从不 retire 的系统在同一套 case 上分数显著更低。这是可以不带星号引用的那句话。

高分**不能**声称的，四条，每条都有实测支撑：

1. **不能声称检索精度好。** `recall()` 在 pool>32 时靠 `_key_hits_query` 排序，而 `_KEY_LEXICON` **实测只有 14 个词根**（citation/code/comment/doc/email/explanation/format/language/length/meeting/report/research/style/tone）；中文请求上几乎恒不命中，剩下的就是 `created_at` 尾部 32 条。高分只说明「最近 32 条里没有僵尸」。
2. **不能声称 scope 过滤有效。** `translate.py:81` `_requirement_block` 实测只打印 `- [id] text`——**scope 字段从不进 prompt**。第三份审查实测越界规则被带进改写只有 1/6，且与 scope 是否写进措辞无关：那 1/6 是 translator 自己按话题词面过滤的结果，不是 `_scope_ok` 的功劳。
3. **不能声称 gold 无偏。** 10 个人工名额在结构上采不到「标注器系统性偏一个方向」这一类（§3）。残余偏差有方向、不进 CI、bootstrap 区间照样很窄。
4. **不能声称语料分布像真实用户。** 单句可以做到不可辨为合成；一**组** 480 条偏好像不像真实用户群，10 条人工看不出来，任何判别器也测不出来。

对外的一句话应当是：**"a lifecycle-replay benchmark whose retirement half is mechanically verifiable, with a stated and unmeasured annotation residual"**，不是 "validated"。

---

## 2. 里程碑

### M0 — harness 说真话（**纯工程，可立刻开工，零语料依赖**）

**交付**
- `run_e2e.py:55-67` 的 `_apply_ops` 删除，runner 改用 `memtranslator.store.Store` 本体，每 shard 一个私有路径。实测该函数**无 `merge` 分支、不写 `supersedes`、`Requirement(text=...)` 不带 key/scope/bucket/salience**——新 E 要给 `chain_fidelity` 和 merge 打分，沿用它等于在一个产品不存在的 store 上给产品打分。顺带白拿事件级 resume（`Store._append` 已是 append-only + `from_dict` 保留 `created_at`）。
- `run_e2e.py:86` 补 `context` 第三参（实测今天不传，`_scope_ok` 一次都没跑过）。
- `with_retry` 从 `parallel.py:75` 的 item 级下沉到 `llm.complete()` / `judge()` 调用级。35 次调用的 shard、单次失败率 2% 时整 shard 重跑概率 **51%**（建模）。
- `bench/runner/ratelimit.py`：judge 通道 token bucket + AIMD。理由是实测记录在案的——`parallel.py` 注释写着 judge 通道在**串行速度**下就返回过 429，而 per-call backoff 在 W 个 worker 下只让 1/W 退让，机制有效性随并发上升而下降。
- `report.py` 六处：`suite_score` 返回 `{headline: min(micro,macro), micro, macro, gap}`；`category_rates` → `strata_rates(by=mode|bucket|effect.op|episode)`（实测今天所有 persona 的 category 都是 `"persona"`，那一行等于把 suite 分打印两遍）；episode 级塌陷闸门（拿今天数据回测：`writer-zh` 的 rates `[0.17, 0.75, 0.67]` 会触发）；`write_snapshot` 的 `p.glob("*.json")` 改 `rglob` 并把相对路径喂进 hash（否则 episode 落进子目录后 `cases_hash` 静默变空）；`metric_version` 字段 + version 不匹配拒绝入 gate；`expected_shards` / `completed_shards` 完整性断言。
- `bench/.run/<run_id>/` 落 `$TMPDIR`。仓库在 `~/Library/Mobile Documents/`，`bench/runner/config.py:40` 已经记过一次 iCloud 静默藏文件；408 个高频追加的小文件不能放同步目录。

**验收**：8 个现有 persona 在新 harness 上重跑，E 与今天 0.703 差 ≤ 0.05；`tests/test_gold_matches_store.py` 的 10k fuzz 绿。**注意这条测试必须写成同态不是同一**——实测 `schema.py:16` `STATUSES = ("active","retired")` 二值，gold 的四种失效原因要先投影为 `retired` 再断言；且必须覆盖 `store.py:17` `AUTO_RETIRE_AT = -2` 这条 gold 日志里没有对应事件的第二条退役路径。

**人工**：无。

---

### M1 — 预注册的分离度实验（**纯工程，可立刻开工；这是整个计划的 go/no-go**）

第三份审查是唯一带实测的，它的三个数字直接决定 480 条语料值不值得写。在写第一条语料之前把它做成正式实验。

**交付**：3 个 facet × 4 个臂（真系统 / null-dump / **recency-32** / flat-dump）× 每格 20 个 probe ≈ 240 次 haiku 调用。测四个量：
- 死条目泄漏率（注入已失效规则时被带进改写的比例）——审查实测 0.83–1.0（n=6）
- 越界泄漏率——实测 0.17
- dilution 斜率（8/30/52 条注入下的 CARRY）——实测 6/6、5/6、5/6
- 真系统 vs **recency-32** 在 SUPPRESS 上的差（不是 null-dump：实测 `Requirement.strength` 初始恒 1、`run_e2e._apply_ops` 的 reinforce 根本不 bump strength，spec 的「按 strength 取前 32」排的是常量，真正威胁 suite 的 trivial baseline 是 recency-32）

**验收（预注册，不达标就停）**：死条目泄漏 ≥ 0.60，且真系统与 recency-32 在模拟 cp-06 密度下 SUPPRESS 差 ≥ 0.15。达标才继续。

**不达标怎么办**：说明这套 suite 在当前产品形态下分不开系统，480 条语料买不到区分度。届时的正确动作是缩小语料、把预算全部挪去堆失效事件与死条目 probe，或者先修产品（scope 进 prompt、recall 排序）再谈 bench。**这一步花几美元一小时，能在花掉几周之前证伪整个计划。**

**人工**：无。

---

### M2 — 图层（**纯工程，可立刻开工，零语料**）

**交付**：`bench/graph/{schema,relate,derive,invariants}.py`。采纳第一份设计的 `relate()` / `scope_relate()` 代数，但改三处，全是审查落地的：

1. **scope 六维禁止缺省。** 每维必须显式给值或字面量 `ANY`。原设计里 `None` = 全集是 LLM 信息不足时的默认落点，而漏填在 `relate()` 上是**有方向的偏差**：漏一边 → `B_EXCEPTS_A`（谁都不死，僵尸留在 gold 里，反向奖励一个从不 retire 的系统）；两边都漏 → 伪 `CONTRADICTS`（跨语言规则互杀）。且 I1/I2/I3/I7 对后者**全部隐形**。改成必填之后，漏填从不可见变成可比对的事件。
2. **key 注册表不按 bucket 分区。** 原设计「每 bucket ~15 个 key」把 bucket 判错强制变成 key 分区错，而 `relate()` 第一行 `if a.key != b.key: return INDEPENDENT` 直接删边——`docs/2026-07-26-taxonomy-verdict.md` 实测 bucket 歧义 **23%（51/224）**，其中 55% 集中在 deliverables↔output_contract 一对边界上。key 注册表必须与 bucket 正交。
3. **放弃「三路独立导出」这个说法。** 只有两层：`D_plan`（构造边 fold，构造性为真）+ coords 上的机械不变量。原设计的 `d_coords` 伪代码里 `u.kind ∈ {assert, withdraw, scope_shift}` **本身就是 retire-vs-contradict 的答案**，withdraw 分支还直接拿到 `u.key`/`u.scope`——在 L 今天卡在 0.50 的那一类上，它是计划的第二份拷贝。`D_text` 保留，但**降级为语料真实度探针，只报不进 gold**（理由见 §4.6）。

不变量：I1（CONTRADICTS 两端不同时 active）、I2（三级链传递闭包）、I3（PARTIAL_CONFLICT 构建期拒绝）、I5（单调性）、I8（可达性）、I9（role 由度数导出）。

**新增两条，替代被证伪的 I4/I6**：
- **I10 语义近邻闸**：同 episode 内两条 constraint 的内容词 Jaccard ≥ 阈值但 `relate()` 判 INDEPENDENT → 构建期报错。原 I4「DUPLICATES 必须被 merge」是循环定义：DUPLICATES 只在 `a.key == b.key` 时产出，而「未声明的重复对」的成因恰恰是 key 被劈开，劈开的同时边就没了。这条抓的是 I4 结构上抓不到的那类，代价为零。
- **I11 陷阱可达性闸**（**这是第三份审查最有价值的一条，两份设计都没有**）：每个 `must_not_fire` 陷阱必须是「一个 recency-32 baseline 在该 probe 上真的会注入」的条目，否则拒收。死条目按构造一定比后继老，cap 按 `created_at` 砍尾巴——审查按密度表模拟出 cp-06/07/08 上 null 臂只注入 23%/37%/43% 的死条目，其余 57–77% 的陷阱断言对一个零生命周期逻辑的系统白送满分。这条闸把 intro→death→probe 的间距变成 episode 编排的硬约束。

**删掉的断言**（因为 bench key 空间与产品 key 空间不通约——`EXTRACTION_SYSTEM` 规则 4 让 SUT 自由发明 key，是开放词表）：I6 与 lint 3 的「陷阱与 must_fire 共享 key 前缀」改为共享 **distinctive token 家族**；`must_fire` 的「模拟 recall() 可满足性」lint 删除（lint 在 gold key 上模拟，运行时跑的是 SUT key，是两次不同的函数应用，保证是空的）。对齐一律走 distinctive 子串，永不走 key。

**验收**：`relate()` property test；`scope_compatible` 投影 ↔ `recall._scope_ok` 的六维封闭词表笛卡尔积穷举等价；I10/I11 在 8 个人为植入缺陷上全抓。

**人工**：无。

---

### M3 — 标注校准（**唯一的人工触点，10 条**）

见 §3。**验收**：owner 的 10 条读法规则写进 annotation prompt 后重跑标注，图上 `CONTRADICTS`/`DUPLICATES` 边的翻转率落盘；> 10% 则声明前一版标注作废（这是预期结果，不是故障）。

---

### M4 — pilot episode e-01（端到端一条）

**交付**：L1→L4 全链走通一条 episode。语料方向翻转成**先建图、从边生成文本**（两份设计共有的最强主张，保留）：源句 → SKELETONISE（廉价 LLM）→ skeleton（结构化命题）→ 字段级变异 → UTTER（skeleton + persona card + incident hook）→ utterance。generator **物理上看不到源句**，这同时解决许可（版权保护表达不保护命题，repo 内零第三方原文）与反 backbone 记忆（变异发生在字段上，先于生成）。判据从 skeleton 自动导出，spec 的 P5「人工逐条写判据」消失。

采纳第二份设计的三处结构：`C` carrier 轮（请求与规则是同一个字符串——今天 persona 文件把 `task` 和 `natural_correction` 拆成两个字段，实测 `run_e2e.py:86` 只把 `task` 喂 translate，真实使用里最高频的形态从未被测过）；**episode 文件只写 `diff_plan` 不写 `final`**（今天的 persona 文件存了 `final`，那是把 SUT 的输出当成了常量，是直接的正确性 bug）；second-half 切点由固定的 `E2E_SECOND_HALF_FROM=9` 改成按 constraint 成熟度（`flushes_since_intro ≥ 1`）。

**验收**：lint 全绿含 I10/I11；`oracle-ceiling ≥ 0.9`；真系统 vs recency-32 的 SUPPRESS 差复现 M1 实测值 ±0.05；cp-00（~6 条规则密度）的 `E0` band 与今天 0.703 差 ≤ 0.10（差得多说明 harness 或生成器错了，不是产品错了）。

**人工**：无（10 条已在 M3 花完）。

---

### M5 — 放量到 12 episode

**规模决定，与两份设计都不同**：12 episode × **40** 条 catalogue = **480 条**，不是 672。三条理由：

- 672 是按旧 spec 的**人时**定价的（「多写 8 个 scenario ≈ 450 条双人复核」），人时不再是约束，定价失效。
- M1 实测 dilution ≈ 0（52 条注入与 8 条注入几乎一样准），CARRY 对语料规模不敏感；边际收益集中在失效事件与死条目 probe 上，不在 constraint 条数上。
- 12 个簇保住（CI 以 scenario 聚类，8 个簇会明显变差）。

**同时更正 spec 的 cp 表**：实测 `consolidate.py::should_consolidate` 是 `len(active) > 48` **或** `adds_since >= 16`。任何密集引入的 episode 上 `CONSOLIDATE_ADDS=16` 必然先触发并重置计数，**`CONSOLIDATE_ACTIVE=48` 这条分支在实践中永不作为触发原因**。spec 把 cp-06 设计成「consolidation 首次在密集 store 上触发」是错的。处置：不再追 49 active，密度目标只保「峰值 active 越过 `RECALL_CAP=32`」（40 条 catalogue 分级失效后峰值 34–38，够）；每次 consolidation 记录**哪个触发器命中**，并把「ACTIVE 分支从未命中」作为一条产品发现报出来。另：`Pipeline.maybe_flush` 实测**不调 consolidation**，harness 必须自己按 daemon 方式驱动。

失效原因配额按比例上调：每 episode ≥ 20 条失效（50%，spec 是 34%），因为失效事件是唯一有区分度的资源。

**验收**：12 条全过 lint；`peak_active_observed` 每条必报（一个只学到 20 条规则的 SUT 永远越不过 32，suite 会静默退化成稀疏 store 测试而分数看起来还不错——这是最隐蔽的失效模式）；许可 lint 全绿 + `bench/NOTICE` 由 provenance 并集生成。

**人工**：无。

---

### M6 — 两次全量跑，**不设 gate**

**交付**：`E-mech` / `E-judge` 双 band（第三份设计的方案，采纳）+ 四个对照臂（`null-dump`、**`recency-32`（新增，替代 null-dump 成为主要 trivial baseline）**、`flat-dump`、`oracle-ceiling`）+ scenario 聚类 bootstrap CI + 实测 ICC + `may_carry` 占比 + judge parse-flag 分层率。

**分数结构的两处决定**：
- `episode_score = 0.25·CARRY + 0.45·SUPPRESS + 0.30·STATE`，不是原设计的 `0.6·CARRY + 0.4·SUPPRESS`。理由是 M1 的实测：CARRY 对注入集合几乎不敏感（6/6、5/6、5/6），把 0.6 权重打在一个不区分系统的量上，等于把全部区分度压进 0.4。SUPPRESS 与 STATE 是实测有区分度的两个量（null 臂 `zombie_rate = 1.0`）。
- **gate 只压 `E-mech`**，`E-judge` 报出不入 gate。`E-mech` = 全部零 judge 在环的断言：`not_contains(distinctive)` 的 SUPPRESS 半边、`preserves_request_ratio` 闸、对齐的 1–2 级。这样权重可以上到 0.50 而可验证性不下降。
- **`carry@valid` 与 `carry@cap` 分开报**，不合成一个数（`RECALL_CAP=32` 之上的选择质量是产品策略，不是 ground truth；混在一起时 E 的天花板被机械压到 1.0 以下且不可解释）。

**验收**：headline CI 半宽 ≤ 0.08，否则如实报出并明确不设 gate。**此前 E 不产生任何可引用的分数。**

---

### M7 — 定线

权重改 **T .25 / L .25 / E .50**（T 每类别 n=10、`p=0.5` 时 Wilson 半宽 ±0.26，扛不起 70% 的 gate 权重）；阈值由 owner 拍并写进 `bench/README.md`。8 份旧 E 快照移入 `bench/results/archive/`。

---

## 3. 10 个人工标注花在哪，以及答案与 LLM 冲突时怎么办

**先把不可回避的算术说清楚。** 10 条随机样本全对，按 rule of three 只能把语料错误率的 95% 上界压到 **30%**；20 条压到 14%，30 条压到 9.5%。而 headline 要报的是半宽 ±0.057 的三位有效数字。**10 条预算下，"校准" 和 "给出错误率上界" 只能二选一，不能两个都要。**

**决定：10 条全部前置，全部用于校准，放弃从人工得到统计上界。** 上界这件事诚实地记为「未测量」，不用「LLM 判过了」盖过去。理由：事后名额修不了一个系统性跑偏的标注器，而标偏的标注器会浪费掉全部 480 条。

**决定：不按 VOI/分歧队列选。** 第一份设计的 `voi()` 排序被两份审查独立打穿，且论证成立：升级队列以「分歧」为筛选条件，而系统性偏差按构造产生**一致**。最清楚的例子是可验证的机械链条——skeletoniser 把一条 Google Python 规则读成全局规则（丢掉 `code_lang: python`）→ 生成的话语里本来就没有限定语 → 回读闸两边字段都缺、相等、PASS → D_text 读散文也读不出 → **三路一致，自动接受**。`voi()` 的定义域是 flag 而不是 constraint，一致区（约 80% 的分数质量）在结构上采不到。而 `voi` 里动态范围最大的两项 `cluster_size` × `blast` 都是**生成计划的属性**，不是标注风险的属性：`blast ≈ 20` 的早死条目正是链上条目，链上条目是被数值 regex 与序列化回环检查最密的一类，`p_wrong` 最低。VOI 排序实际上把名额花在最容易的条目上。

**10 条怎么分配：不是 10 个条目标签，是 10 个用来钉死 3 条读法规则的边界样例。** 每条规则的 fan-out 是几百条，且规则生效与否可以事后机械验证（重跑标注，看图上的边翻转多少）。分配依据是三个**已测量**的风险轴，不是我的直觉：

| 名额 | 轴 | 测量依据 |
|---|---|---|
| **4** | deliverables ↔ output_contract 边界 | `taxonomy-verdict.md` 实测 bucket 歧义 23%（51/224），其中 55% 集中在这一对 |
| **3** | retire vs contradict（「以后 X 就不用了」有无替代值） | L 的 `revoke` 实测 **0.50**（`L-20260728-001140`），全 suite 最低类别；且它是整张生命周期图唯一的承重判断 |
| **3** | scope 宽度：global `{}` vs 具名 scope | 三份审查独立指出 scope 欠标是唯一有方向且对所有导出隐形的偏差；episode 设计自报 55% 节点会落到 global |

owner 看到的是决策卡，不是 JSON：一句用户话式 + 两种读法 + 「选 B 会改变 N 条同型条目、M 条断言」。答案落成一条可写进 prompt 的规则 + few-shot exemplar。

**冲突时的预注册处置**（不留裁量空间）：

1. **owner 与标注器在 ≤3/10 上不同** → 正常。把 3 条规则写进 annotation prompt，全量重跑标注，落盘边翻转率，继续。
2. **在 4–6/10 上不同** → 前一版标注**整体作废**，重跑；并且**该轴的 per-bucket / per-op 子分不发布**，只发 headline。不追加人工名额。
3. **在 ≥7/10 上不同** → 该轴判定为「LLM 不可学」。具体动作是**把该轴从计分里拿掉**，而不是硬标：bucket 轴不可学 → key 注册表不按 bucket 分区（M2 已经这么做了）、不出 per-bucket 子分；retire/contradict 轴不可学 → 这两类事件的 gold 降级为**构造性 gold**（生成时就决定，不假装是导出的），与 assert 类分开出分，不混进同一个 headline；scope 轴不可学 → 全部 constraint 标 global，scope 维度退出 STATE 断言，只做 BEHAVIOUR 观测。
4. **传播回验**：重跑标注后，如果 owner 的规则在其所属簇内被 `D_text` 反对 > 20%，**不回滚、不弃簇**（原设计的「回滚进 E-amb」会让人工杠杆自锁：owner 被叫来仲裁的前提往往就是与 D_text 不合，站 plan 一侧必然触发 >20%，站 D_text 一侧只是复述 D_text——两个稳定输出都是「无变化」或「弃簇」）。改为：以 owner 的规则为准，把 `D_text` 的反对率作为**语料歧义度的观测量**公布，不作为仲裁者。

---

## 4. 审查落地、而设计没有答案的问题

### 4.1 CARRY 对系统几乎不敏感（**最重的一条**）

实测（n=6/格，temperature 0）：注入 8 / 30 / 52 条时目标规则被带出 6/6、5/6、5/6。任何把规则装进 store 的臂拿同样的分。**缓解**：权重改成 CARRY 0.25（§M6），且 M1 用更大 n 重测并预注册。**接受的限制**：如果 M1 复现这个结果，那么 480 条语料在读路径上买到的区分度接近零，E 的全部信号来自 SUPPRESS + STATE；这一点必须写进发布材料，不能让 headline 暗示「记住并应用规则」被测过了。

### 4.2 flat-dump 是 oracle 不是 baseline

它有完美 store，所以 CARRY 更高、死条目一条没有故 SUPPRESS 免费满分、STATE=1.0、QUIET=1.0，唯一可能扣分的「活但越界」实测泄漏率 1/6。它在每个分量上都 ≥ 真系统。**缓解**：不再把它当 baseline；把 spec §4.5 的 go/no-go 换成 `recency-32` 臂（同一个学到的 store、绕过 recall 排序、只取最新 32 条）。**接受的限制**：「recall() 的选择逻辑有没有用」这个问题，在 `_KEY_LEXICON` 只有 14 个词根的前提下，这套 suite 结构上答不了——扩词表去覆盖 bench 的 key 就是 owner 明令禁止的 bench overfitting。实测 pool=52 时 `recall()` 输出与「最新 32 条」重合 30/32（94%）。这条只报不判。

### 4.3 系统性标注偏差产生一致，10 条名额采不到

**接受的限制，不编替代品。** canary 也救不了：原设计的 canary 是往**已标好的 coords** 上事后施加损坏，损坏后 coords 与「从未损坏的 skeleton 生成的那句话」必然不一致，D_text 一读就炸；而真实错误是 coords 先错、话语**从错的 coords 生成**、二者完美一致。两个分布不相交，`f/s` 不是任何量的估计。**保留 canary，但改注入位置到 SKELETONISE 之前**（损坏「解读」而非「坐标」），并明说测出来的 s 预计远低于 0.9——那个数本身才是有价值的产出。发布时的表述是「已抽样校准，残余偏差未测量」。

### 4.4 scope 对 SUT 不可见

`translate.py:81` 实测只打印 text。**接受的限制 + 一条降级**：六维 scope 砍到四维（`app`, `task`, `code_lang`, `nat_lang`），`recipient` / `artifact` 不做；scope 只参与 gold 的 activation 推导与 BEHAVIOUR 观测，**不进 STATE 断言、不进 gate**。产品的 `scope.lang` 被自然语言与编程语言重载（`{"lang":"python"}` 与 `same_language` checker 共用一个字段）**作为产品 issue 单独提**，不在 bench 里绕。

### 4.5 产品状态机的分辨率低于图

实测：`STATUSES` 二值，`scope_dead` 完全不可观测；`merge` 只把 `supersedes` 指向 `targets[0].id`，3→1 的 merge 结构上最多表达 1/3 个指针；`apply_ops` **没有任何 op 能把 retired 翻回 active**（un-retire 只有 `server.py` 的手动 HTTP API）。**接受的限制**：`chain_fidelity` 对 merge 的上限写进分数定义，不当产品错误计分；`scope_dead` 不作为独立 STATE 类计分；**revival 整类从 suite 里删掉**——原 spec「两种产品行为都记通过、分开统计」的中立立场是假的，只有一支可达。

### 4.6 D_text 是 SUT 的一次重新实现

它的任务（读长 transcript 前缀 + 打乱条目，判定每条是否仍有效）正是 MemTranslator 存在的理由。**处置**：D_text **不作为 gold 来源**，只作为语料歧义度的观测量报出；随之**删掉「歧义率目标带 8–15%，低于 8% 判定语料过净」这条控制回路**——若分歧由 reader 能力主导，这条规则会驱使语料人为变脏去满足一个模型本来就会产出的数字。**接受的限制**：「生成的撤回语句是否比真人干净」目前**有方向、无刻度**，PRISM `open_feedback`（CC BY 4.0）真实语句做改写锚是唯一的缓解。

### 4.7 skeleton clean-room 的许可论证是推断

「命题不受版权保护，repo 内零第三方原文即可满足 CC-BY 署名」——这是法律判断，**需要 owner 签字，我不替你认定**。签字前：BY-SA 源（Wikipedia 占 thin-bucket 已提取的 23%，44/189）全部标 `copyleft_derived=true` 并冻结在 pilot 之外，先只用 Apache-2.0 / MIT / CC-BY / public-domain 跑通管线。

### 4.8 judge 到两个协议改动

（a）**judge 必须退出 store 循环**——今天 `run_e2e.py:96-101` 是 judge 判 miss → 追加纠正信号 → 影响 store，纠正信号是反应式的；gold-by-fold 要求日志作者写定，所以纠正信号必须脚本化。这改变了 E 测的东西（反应式 → 脚本式模拟用户），**跨版本 E 分数不可直接比较**，snapshot 里打 `protocol_version`。
（b）`providers.py:107` 实测显式滤掉 `style_rule` op。第二份设计里 15% 配额的 `reword` diff 档因此**无法计分**——要么放宽 bench 契约，要么这一档改 report-only 并把配额挪给 `add_constraint`。**需要 owner 拍一下，别默认。**

---

## 5. 成本与墙钟（一次全量）

推荐并发：**`--product-workers 8 --judge-workers 6`，两阶段 pipelined。**

| 项 | 调用数 | 金额 | 依据 |
|---|---|---|---|
| SUT（claude-haiku-4-5） | ~2,256 | **$8.3** | 建模 |
| judge（deepseek-v4-pro） | ~7,800 | **$0.9** | 假设费率 |
| **合计** | **~10,056** | **≈ $9.2**（judge 费率差 5 倍 → $13） | |

墙钟：product 串行 ~132 min、judge 串行 ~260 min；8/6 并发 + 25% judge cache 命中 → **pipelined ≈ 40 分钟**（建模）。最长单 shard（一条 chained episode，judge 已解耦）≈ 123 秒，这是不可压缩的关键路径。
冒烟档（3 episode × chained ×1，state 只判 cp-04/cp-08）：~110 SUT + ~450 judge ≈ **$0.5 / ~7 分钟**，可挂 commit。

**假设，逐条**：12 episode × 65 轮 × 40 条 catalogue × 8 cp × 3 probe；每 chained pass = 24 translate + 8 extraction + 3 consolidate = 35 SUT 调用；chained/segment/oracle 各 ×2。单次 SUT $0.0037 = 今天实测 $0.85/432 次（$0.00197）× 1.9，1.9 倍来自两个产品常量而非猜测——translate prompt 挂 `RECALL_CAP=32` 条召回（今天 3 条）、extraction prompt 挂 40 行编号 index（今天 3 行，`INDEX_ROW_TOKENS=20`）。延迟假设 haiku 3.5s / judge 2.0s，**一次也没实测过，首跑必须开 per-call 计时回填**。DeepSeek-v4-pro 在 Ark 上的费率**未核实**。judge workers=6 是从被证过的 4 外推的，首跑按 4→6→8 爬并把每档 429 率写进 snapshot。

结论：**钱不是约束，墙钟和 429 是。** 最高杠杆的优化不是加并发而是加机械判据——judge 串行秒数是产品侧的 2 倍，每省一次 judge 调用省 2 秒瓶颈资源。

---

## 6. 今天的资产去留

| 资产 | 处置 |
|---|---|
| **114 个 T/L case** | **一条不删，原样保留**，retag `tier: unit`，权重 T 0.4→0.25、L 0.3→0.25。T 是唯一有人工抽检背书的判据（29/30，`bench/gen/judge-audit.md`）；`preserve-long 0.70` 是活跃缺陷，E 不覆盖。L 的 `revoke 0.50` 是新 E 的靶子，也是 §3 里 3 个人工名额的依据，必须留着做纵向对照。**L 不扩容**。 |
| **8 个 persona 文件** | **保留，改名 `E0`（不是 `E-legacy`）**，独立 suite id、独立 results 前缀、不进 gate，继续挂 commit hook——它是今天唯一能在 8 分钟内跑完的端到端检查。24 条规则（8×3）进 catalogue 作 `first_seq ≤ 6`。**必须保住的纵向锚点**：`E-repaired 0.841` vs `E-chained 0.727` 这一对，是本项目唯一的 chained/repaired 对照，作为 M4 的验收基线。今天的 112 判定点/run 与 `writer-zh` spread 0.583 作为新 suite 必须打下去的靶子并列在报告里。 |
| **`parallel.py`** | 保留骨架，三处改：`weight` 参数 + LPT 降序（408 个 shard 里 24 个比其余长 8–20 倍，按文件序提交会让尾部只剩 1 个 worker）；去掉 item 级 `with_retry`；`run_id` 进 checkpoint 路径（今天只按 `item.id` 判重，改了 case 再跑会静默混两个版本的结果）。 |
| **`checkers.py`** | 保留 3 个，扩 `regex_present/absent`、`preserves_request_ratio`、`numeral_present`。全部作用在**改写后的请求**上——spec §4.2 那处纠错（`max_line_length` / `serial_comma` / IFBench `format:*` 是在校验产出的制品，属范畴错误）**逐字保留**，这是全份 spec 最有价值的一处。 |
| **`retry.py` / `judge.py` / `providers.py`** | 保留，按 M0 改造。窄 context judge（2026-07-24 已落地：同一对样本全 context 判 [T,F,T]、窄 context 判 [T,T,T]）逐字保留。 |
| **`run_e2e.py`** | 从 gate 上退位，改为只驱动 `E0`。新 gate 走 `bench/runner/run_episodes.py`。其中 `_apply_ops`（M0 已删）与 `_reset_to_gold`（升级为 segment/oracle 的 gold_state 注入）是仅有的两处逻辑继承。 |
| **`report.py`** | 保留 `latest()` 的精确后缀匹配（那个 bug 修过了，别退化），其余按 M0 重写。 |
| **`docs/2026-07-26-bench-scaleup-spec.md` §1 语料源裁定表** | **逐字继承，一个字不改。** 许可裁定不受这次方向翻转的任何一条影响，而它是「能不能开源商用」的硬约束；机器管线大规模摄取之后，一条许可错在 480 条规模上是全 repo 问题。thin-bucket §1 的两桶裁定表同级继承。 |
| **spec 里作废的** | P5（人工逐条写判据）、P7（双人签字）、lint 规则 9、人工审核 checklist 第 5 条、§6「6–8 个工作日人时」一行、cp 表（按 `CONSOLIDATE_ADDS` 先触发重算）、`conflicts_with` 字段（由 `relate()` 导出）、`role` 字段（由图度数导出）、`must_carry` 的「模拟 recall 可满足性」lint、revival 整类、Suite R 这个名字。 |
