# HMS 与 Mandol 代码深读：可借鉴点

> 2026-07-21。方法：两个 agent 分别通读 repo 代码（非 README），我抽查核验了四处关键引用（HMS 的 ledger dataclass 与 consolidation 纪律原文、Mandol 的 emotional prompt 原文与 main 分支无 smart-search 的负向论断），全部吻合。文件行号均可在 clone 后复核。

- HMS = [Shadow-Weave/HMS](https://github.com/Shadow-Weave/HMS)（Holographic Memory System，LongMemEval 长期记忆 QA 框架，arXiv "coming soon"）
- Mandol = [AgentCombo/Mandol](https://github.com/AgentCombo/Mandol)（[arXiv 2606.29778](https://arxiv.org/abs/2606.29778)，cs.DB；注意 main 分支重构中，论文结果对应 paper-repro 分支——**README 宣传的 Smart Quantitative Retrieval 在 main 上没有实现**，`smart_search` 的 import 源 `dev.*` 包不存在）

## HMS：answer 前的证据组织

核心主张与我们同构但位置相反：我们在 **query 前**编译 requirement，它在 **answer 前**组织 evidence。

值得借鉴的机制：

1. **Evidence ledger 是纯规则构建、零 LLM**（`lab/evaluation/benchmarks/longmemeval/longmemeval_benchmark.py:555-631`）：recall top-180 → 数值/日期 regex + 与问题词重叠计分 → 去重 → top-45 行，每行 `occurred | mentioned | doc | type | text`，附 ≤18 条逐字 chunk 引文。产品化为 `vendor_sdk/.../organizer.py` 的独立 organize 阶段。对我们：read path 给 translator 的 memory 视图可以同样确定性重组（provenance quote 随行携带），零成本零延迟。
2. **"Self-evolution" 的诚实实现**：judge 判错 case 全量落盘（问题/gold/生成答案/judge 理由/检索快照，`benchmark_runner.py:1140-1157`）→ 人工归纳出 4 条静态 control 指令 → 关键词门控按需注入（不是每次全量）。版本号 V2.6→V2.20 暗示人工迭代十几轮。对我们：pilot 就该内建 wrong-case dump（query、召回 memory、patch、判定），translator 的改写规范当作可版本化 controls 迭代。
3. **Consolidation prompt 纪律**（`core/dataplane/hms_api/engine/consolidation/prompts.py:7-25`）：NO COMPUTATION（"2 只狗"+"有只狗叫 Rex"≠"3 只"——禁止 LLM 推导）、SAME FACET → UPDATE NOT CREATE（按具体 facet 判同而非 topic）、PRESERVE HISTORY（保守删除）。**前两条已并入我们 consolidate.py 的 SYSTEM prompt**；第三条我们由 append-only 结构性保证。
4. **双时间戳的信任分层**：`occurred_*`（事件时间）由 LLM 抽取，`mentioned_at`（何时说的）由代码赋值不信 LLM。我们的 `Provenance.at` 已是代码赋值，同思路。
5. **Directives**（用户手写硬规则，`engine/reflect/prompts.py:36-96`）：prompt 顶部 MANDATORY 段 + 末尾 REMINDER 双注入。这是 HMS 里最接近我们 requirement 记忆的东西，但完全人工维护、不自动提取——"自动抽取 + 只存 requirement + query 时编译"的组合在 HMS 不存在，是我们的差异化空间。其注入格式对 translator patch 措辞有参考价值。
6. 工程细节：不同 tag 的记忆绝不进同一次 LLM call（隔离硬规则）；批失败自适应二分重试到单条 + `consolidation_failed_at` 毒丸标记（比整批放弃细腻，我们 §3.4 的"整批 DROP"未来可升级为此）。

## Mandol：分层图记忆（含偏好层）

与我们最相关的部分是 emotional memory（用户偏好层），结论是**反面参照**：

1. **偏好层是 session 级摘要，不是逐条记忆**（`application/reducers/summary_prompts.py:106-133` + `summary_map_reducer.py`）：每 session 用 map-reduce 生成一个 emotional summary unit（六个 `List[str]` 字段），跨 session 不合并。prompt 里写了 "Distinguish between stated preferences and inferred patterns"，但结构上不落地（输出扁平 string list）。
2. **且默认检索路径根本不查偏好层**（`services/_retrieval.py:62-86`：holistic_retrieve 的四组不含 emotional，只能显式 `retrieve_by_view(view="emotional")`）——"偏好当摘要存"的方案在集成端被边缘化。这是我们"逐条状态机 + read path 必经"设计动机的最好实证反例，论文竞品分析可直接引用行号。
3. **写路径成本反面教材**：每 session = 4 类摘要 map×chunk + reduce 锦标赛 + insight + global merge + 4 次抽取 + 每实体/事件一次 match-judge + 若干 description merge——数十次 call 起步，与我们固定 ≤2 次形成量级差，是论文最硬的成本对比点。

值得正面借鉴的机制：

4. **Match-judge 协议**（`prompts/entity_match_judge.py` + `cross_session_coref_manager.py:904-982`）：LLM 从编号候选列表输出 `matched_index + confidence`（而非自由文本重述），`confidence ≥ 0.7` 才合并，LLM 失败降级纯向量最近邻（0.45）。我们 consolidation 判 REINFORCE-vs-ADD 可照搬：编号候选 + 阈值 + 确定性兜底。
5. **`should_wait` 延迟判界**（`session_manager.py:23-87`）：批尾信息不足时显式输出"等待"而非硬切，上一批 reasoning 截 300 token 携带进下一批。我们 session 结束触发暂无此问题；若未来做 per-turn 触发，这是现成解法。
6. **边属性 provenance**（`domain/coref_graph_constants.py:74-81`）：`mention_text`（逐字 span）+ `session_id` + `confidence` + 合并前原貌（`original_description/original_source_uid`）。与我们 provenance+quote 同构；"合并时保留 pre-merge 原貌"我们由 append-only 链保证（旧条目完整保留，supersedes 一跳可回溯）。
7. **杂项**：<100 向量 brute-force、过阈值才升 FAISS（`adaptive_vector_index.py`——我们 top-8 规模根本不需要 ANN 的量化证据）；≤2 条新事实纯字符串拼接、>2 条才 LLM 合并（降本路径）；单行可 grep 的运行时状态输出（`docs/memory-monitor-design.md`，pilot 长跑监控可抄）；中英混合 token 估算启发式 `chinese*0.6 + ascii*0.3`（零依赖）。

## 已落进原型的改动

- consolidate.py SYSTEM prompt：+ facet 匹配规则、+ 禁止推导/合成规则（HMS 纪律 1、5 的 requirement 场景变体）。

## 后续候选（未做，按优先级）

1. pilot 加 wrong-case dump（HMS 模式，Task 10 实现时并入）。
2. consolidation 输出加 confidence 字段 + 阈值（Mandol match-judge 协议），作为 §6-2 重复检测漏召的缓解。
3. read path 的 memory 视图确定性重组（HMS ledger 模式），translator prompt 变大后再考虑。
