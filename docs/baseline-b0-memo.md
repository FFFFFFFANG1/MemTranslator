# Baseline B0 冒烟 memo

> 2026-07-22 执行（baseline plan §5 B0）。冒烟脚本：`pilot/scripts/smoke_baselines.py`（可重复执行）。判定：**B0 通过（带条件）**——两个系统在无 docker、无新 key 的前提下全部跑通；Graphiti 的公平接入形态上升为 B1 首要设计项。

## 配置定案

| 系统 | 版本（锁定） | 存储 | 内部 LLM | embedding | 结果 |
|---|---|---|---|---|---|
| Mem0 OSS | mem0ai **2.0.12** | qdrant 本地磁盘（内置，无服务） | **anthropic claude-haiku-4-5**（可用 ✓） | openai text-embedding-3-small | **PASS**：3 条偏好 add + search 回读命中 |
| Graphiti | graphiti-core **0.29.2** | **FalkorDBLite 0.10.0 嵌入式**（`redislite.async_falkordb_client.AsyncFalkorDB`，进程内 redis-server，无 docker） | openai **gpt-4.1-mini**（见发现 2） | openai 默认 | **PASS（管线）**：add/search 通；偏好抽取稀疏（见发现 4） |

统一内部 LLM 为 haiku 的目标达成一半：Mem0 ✓；Graphiti 的 anthropic client 未试（0.29 的 AnthropicClient 存在，B1 时试，失败则保持 gpt-4.1-mini 并在论文注明——两系统内部模型不同属 baseline 原生形态差异，记账时分开列）。

## 发现（按重要性）

1. **kuzu 后端不可用**：graphiti 0.29.2 的 kuzu 路径带 DeprecationWarning（"upstream Kuzu project no longer maintained, migrate to Neo4j or FalkorDB"），且 FTS extension 不加载、`build_indices_and_constraints` 对 kuzu 是 no-op、FTS 索引 DDL 定义了却无人调用——三个叠加导致 search 必然崩。**结论：kuzu 不用**；FalkorDBLite 是无 docker 的正解。
2. **Graphiti 默认 LLMConfig 静默失败**：不显式传 `LLMConfig(model=...)` 时（model=None），实体抽取 LLM 调用返回 200 但产出零节点零边、无任何报错。**必须显式配置模型**（冒烟脚本已固化 gpt-4.1-mini）。
3. **Mem0 2.0 API 漂移**：`search()` 的 entity 参数改为 `filters={"user_id": ...}`（顶层 `user_id=` 抛 ValueError）；`add()` 顶层仍接受。且 Mem0 把第一人称偏好改写为第三人称事实存储（"User has a severe gluten intolerance…"）——注入下游时的格式以其原生输出为准。
4. **Graphiti 对孤立偏好陈述产出稀疏图**（论文素材级发现）：3 条偏好 message-type 灌入，只有含具体名词的一条（"boutique hotels vs large chains"）抽出 3 节点 2 边并可被默认 edge search 检索；语义抽象的两条（gluten 忌口、low-impact 运动）只得孤立 `user` 节点、零边，默认检索**不可见**。含义：(a) B1 接入必须用官方推荐的对话流形态灌入（PrefEval 的多轮对话，而非偏好单句）+ 检索配置含 episode/node 层，否则 baseline 是 strawman；(b) 图记忆对偏好类内容的结构性覆盖缺口本身是 translator 路线的论据，正式实验里用"召回命中率"指标量化。
5. 写入延迟：Mem0 ~3.5s/条（haiku），Graphiti 5–17s/条（抽取+嵌入+去重检索）。全量跑批的时间预算按 baseline 臂 ×3 预留（plan §6 风险项证实）。
6. FalkorDBLite 的进程退出会打一串 `__del__`/GC 噪音（无害）；graphiti `close()` 对 lite 的 async 接口不完全兼容（脚本已兜底）。

## B1 待办移交

- BaselineMemory adapter：Mem0 用 `filters` API；Graphiti 封装 AsyncFalkorDB + 显式 LLMConfig + FTS 兜底；
- Graphiti 接入形态实验：对话流灌入 vs 偏好单句灌入，检索配置 edge vs edge+episode——各跑 10 条定形态；
- Graphiti 内部 LLM 换 anthropic haiku 试点。
