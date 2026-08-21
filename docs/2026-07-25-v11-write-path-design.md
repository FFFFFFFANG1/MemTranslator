# MemTranslator v1.1 写路径最终设计

> 代码引用均对照工作树 `/Users/siriux/Library/Mobile Documents/com~apple~CloudDocs/Documents/Codes/Projects/MemTranslator`（branch `dev`）核过。四份审计的 blocker/major 全部处置在 §9，被拒绝的 minor 同表列出理由。
>
> **2026-08-11 决策更新：** 本文原先的“禁止 embedding”约束已撤销。现在允许 BM25 与本地轻量 embedding 融合生成候选；embedding 模型必须可在 CPU 或集成显卡运行，不能要求独立 GPU，也不能把外部 embedding API 作为默认依赖。相似度只负责候选排序，最终生命周期动作仍由 consolidation 判断。

---

## 0. 一句话总览 + 变更清单

v1.1 把 `reinforce` 从"给整数加一"改成"在规则下挂一条用户原话的 evidence 子行"，把候选生成从"整库进 prompt"改成 BM25F 短名单 + 强制 abstain，把规则措辞的唯一改写权收归 consolidation 的 `widen` op，并给每一处 prompt 装上硬 token packer——单轮生成调用从"最多 2 次、约 14k token"降为"最多 1 次写调用、总计 ≤9.2k token"。

| # | 改什么 | 为什么 | 痛点 |
|---|---|---|---|
| C1 | `reinforce` 落一条 `kind="evidence"` 子行（用户逐字原话），只 `strength += 1`，结构上不能改父规则的 `text`/`key`/`scope`/`breadth` | `store.py:82` 现在是 `req.strength += 1` 且仅此一句：同一规则下两个不同类别的证据被压成一个整数，面板无法解释"为什么被强化"，consolidation 无法判断规则的真实覆盖面 | P3 / P1 |
| C2 | `new`/`contradict`/`widen` 强制携带 `category_phrase`，落为 `breadth`；新增 `breadth_state ∈ unknown\|named\|global`，只有 `global` 允许 `covers()` 短路，且学习产生的规则永不出生为 `global` | v1 规则的类别面完全隐含在自由文本里，代码无法判断"这条是否比证据窄" | P3 |
| C3 | divergence 由代码判定（`div_tokens` + `covers`），模型给的 relation 一律忽略；`unresolved_distinct_divergence` 在 sweep 时从活子行重算，不落盘计数器 | 让机制读用户词汇而不是模型词汇；计数器与活行漂移是 v1.1 初稿的已知 bug | P3 / P4 |
| C4 | 新增 `widen` op（仅存在于 consolidation），`verify_widen` 四条机械门；落地时给被覆盖的子行打 `resolved_by` | v1 只能用 `contradict` 表达加宽，而 `contradict` 在 `store.py:96` 会继承旧 scope，加宽后仍被 scope 过滤 | P3 |
| C5 | 候选生成：`index.py`（BM25F，stdlib，~120 行）+ `candidates.py`；`extraction.py` 的 `STORE:` 块变 `CANDIDATES:`；relation head 强制 abstain（无候选达标必须回 `new`） | v1 把整库塞进 prompt 让模型同时做检索+配对+判断，且 prompt 是 `O(store)`，~100 条时单块就 ~4.5k token | P2 / 约束 2 |
| C6 | `retire` 拆成 `revoke{durable\|one_off\|unclear}` + `revive`；`durable` 立即 suspend，硬退休需 3 个 shadow hit 或面板确认；`unclear` 不计入任何退休路径 | v1 的二元 retire 无法表达"这一次不要"，而模型的 abstain token 不该有删除权 | P3 / P4 |
| C7 | `transition(id, to, *, reason)` 成为唯一 status 写入口，返回 `(ok, reason)` 从不抛；`Store.update` / `bump_strength` 全部改为委派 | `apply_ops` 是刻意 total 的（LLM 的 op batch 不得能崩库）；panel PATCH 与 `bump_strength` 现在能绕过任何新状态机 | P4 |
| C8 | `Pipeline` 加 `threading.RLock`，队列在 apply 成功后才清；consolidation 移出同一轮（`consolidate_due` 标志，下一次 flush 单独跑） | `server.py:87-90` 把 flush 和 consolidation 塞在同一次 submit 里；FastAPI 的同步 handler 真并发，阈值触发的新计数器会被双计 | 约束 2 / P4 |
| C9 | 每个 prompt 块加硬 packer（`CANDIDATES_CAP_TOK` / `SIGNALS_CAP_TOK` / `CONSOLIDATE_INPUT_CAP_TOK`），route-B 只送 `user_added` delta + 200 字上下文 | route-B triple 在 `extraction.py:89-93` 是 `json.dumps` 全文，无任何上界；初稿的预算表把它记成常数 | 约束 2 |
| C10 | 计数器变更走紧凑 delta 行 `{"id","op":"counters",...}`，不再整行快照；面板默认过滤 evidence 行 | `RECALL_CAP=32` 条整行快照/flush 只为改一个整数，会淹掉单文件 JSONL 的可读性 | 约束 3 |
| C11 | prompt 与 lexicon 去污染：`extraction.py:45-49` 的四个 exemplar 全换成语料外的杜撰类别 + CI n-gram 门；`signals.py` 的 lexicon 逐条审计并删掉那句假的 provenance 注释 | 现网 prompt 里 `这种长文档` / `emails I ask you to draft` / `调研类问题` / `landlord` 四个字符串全部逐字来自 bench；`_META_PAT` 在 `0f87ea8` 加入的中文词条条条命中语料、英文孪生词条零命中 | 约束 4 |
| C12 | Suite E 的 `run_e2e.py:55-66` 影子 store 删除，改驱动真实 `Store`+`Pipeline`+consolidation；Suite L 的 `run_case` 建临时 `Store` | 现在的 E 从未测过产品写路径（它是写路径的第二份实现）；L 的 provider 拿到的是裸 list，候选生成无处可跑 | 全部 |

被砍掉的（相对 v1.1 初稿）：`split`、`provisional` 状态与 TTL 衰减、recall 侧的 breadth 过滤及其"provisional 放宽"、`valid_from`、第二个 JSONL 文件、evidence 回填脚本、`REVIVE_SIM` 机械复活、`WIDEN_COOLDOWN_S`、mutual-BM25 近重复 bucket、abstain 门的 `median(idf)` 那一条。

---

## 1. Data model

文件：`src/memtranslator/schema.py`

```python
SCHEMA_VERSION = 2
STATUSES  = ("active", "suspended", "retired")          # v1: ("active","retired")
KINDS     = ("requirement", "style_rule", "evidence")
RELATIONS = ("founding", "founding_retro", "support",
             "divergent", "deviation", "revoke", "unclear")
BREADTH_STATES = ("unknown", "named", "global")
```

`Requirement` 新增字段，全部有默认值：

| 字段 | 默认 | 谁写 | 含义 |
|---|---|---|---|
| `schema_version` | `2` | `_append` | 混版写入检测（见下） |
| `parent_id` | `None` | `add_evidence` | 仅 evidence 行 |
| `relation` | `""` | 代码（永不由模型给） | 见 `RELATIONS` |
| `resolved_by` | `None` | `widen`/`merge` 落地时 | 该子行的分歧已被这次加宽吸收 |
| `breadth` | `""` | `new`/`contradict`/`widen` | 用户逐字类别短语 |
| `breadth_state` | `"unknown"` | 代码推导 | `named`=有已验证短语；`global`=显式全局，只能由人在面板设定 |
| `needs_widen` | `False` | sweep（沿边触发） | |
| `widen_attempts` | `0` | consolidation | |
| `widen_attempted_at_flags` | `0` | consolidation | 上次尝试时的分歧集势 |
| `widen_stalled` | `False` | consolidation | 放弃是一个状态，不是重试 |
| `hit_count` | `0` | flush 批量落盘 | 被注入次数 |
| `shadow_hits` | `0` | flush 批量落盘 | suspended 期间"本来会被注入"的次数 |
| `deviation_count` | `0` | sweep | 仅 `one_off` 累加 |
| `deviation_anchor_hits` / `deviation_anchor_at` | `0` / `0.0` | sweep | 双窗口起点（注入数 + 墙钟） |
| `valid_to` | `None` | `transition` | |
| `superseded_by` | `None` | `contradict`/`merge`/`widen` | |
| `retire_reason` | `None` | `transition` | `user_revoke\|behavioral_revoke\|contradicted\|merged\|widened\|auto_strength\|manual` |
| `flush_id` | `""` | `_append` | 同一次 flush 产生的所有行同号，重放可检测 |

刻意不存的：`breadth_flags`。分歧集势在 sweep 时从 `children(id)` 里 `resolved_by is None` 的活子行重算——持久计数器和活行会漂移（子行被淘汰后计数器仍武装着触发器），这是初稿的真实缺陷。

evidence 子行是同一个 `data/store.jsonl` 里的普通 `Requirement`：`text` = 用户逐字片段（存 ≤200 字，prompt 里另行截断）、`key`/`breadth` 从父行拷贝、`scope={}`、`kind="evidence"`、`relation` 由代码赋值。一个文件、一个 loader、一条备份路径、git 可 diff。

### 向后兼容（v0/v1 行）

- `from_dict` 现在对 `text`/`id` 也是 `.get()`（v1 是 `d["text"]` / `d["id"]` 直接下标，初稿把它当成已验证的兼容性证明，不准确）；缺 `text` 的行跳过并计数。整行解析包在 per-line `try/except` 里，一条畸形行不再让 `store.py:27` 拖垮整库。
- 未知 `kind` 跳过并计数（v1.2 前向兼容）。
- 载入时两处纯计算回填，不重写文件、无迁移脚本：`valid_to = updated_at if status=="retired" else None`；`superseded_by` **仅在键缺失时**沿 `supersedes` 链推导——否则推导会覆盖 step 3 和 `merge` 显式写入的值。
- 混版写入防护：`to_dict` 是显式枚举字段的，任何跑 v1 代码的进程（`bump_strength`、panel PATCH、滚动升级中的旧 server、`src/memtranslator/hotkey/` 守护进程）碰一条 v1.1 行都会追加一个丢掉新字段的快照，last-record-wins 会静默把 `parent_id` 抹成 `None`——一条 evidence 子行就此变成孤儿规则并进入 recall。防护两条：(a) `Store.__init__` 发现文件里出现 `schema_version > SCHEMA_VERSION` 时以只读模式打开并在面板挂横幅（不硬拒绝——降级时硬拒绝等于把产品砖化）；(b) `_append` 从该 id 的上一条原始 dict 里 carry-forward 未知键。
- 不做 evidence 回填。历史 reinforce 已经销毁了原话，合成引文等于在"用来让 provenance 可信"的面板里放伪造 provenance。**升级后既有窄规则需要一条 founding 子行加两条分歧兄弟证据才能触发加宽**——`new` 现在会写 founding 子行，所以升级前就存在的规则实际需要 **3 轮** post-upgrade 兄弟证据（初稿的 release note 写的是 2 轮，算错了）。这句话进 release note。

### Store 接口

```python
rules(self)                      # active 且 kind != "evidence"（= 升级前 active() 的语义）
children(self, id)               # 该父行的全部子行（含 retired）
add_evidence(self, parent, quote, category_phrase, relation, *, flush_id)
transition(self, id, to, *, reason) -> tuple[bool, str]     # 唯一 status 写入口，从不抛
transition_or_raise(self, ...)   # 只给 panel / 直接 API 调用者
compact(self)                    # 不在 v1.1（见 §8）
```

`active()` 保留原名，现在排除 `kind=="evidence"`——`recall.py:38`、`consolidate.py:47`、`pipeline.py:45` 三处调用点行为不变。第四处 `server.py:111` 是 `store.list()` 不是 `active()`，会被 evidence 行灌爆，单独在 N8 处理。

`transition` 返回 `(ok, reason)` 而不是抛异常：`apply_ops` 是刻意 total 的（"an op batch from an LLM must not be able to crash the store"），一个模型对 active 行发 `revive` 就抛会在批中途炸掉，而 `pipeline.py:46` 已经在 `apply_ops` 之前清了队列——付了 flash 钱、半提交、剩余信号永久丢失，且 `server.py:86-92` 只 catch `LLMUnavailable`，异常会变成 500。非法边写进 `skipped` 并计数。

### config.py 新增旋钮（每条给出推导，均不来自 bench case）

| 旋钮 | 值 | 推导 |
|---|---|---|
| `CANDIDATES_CAP_TOK` | 1200 | prompt 预算（§7）。这是 `CAND_CAP` 的来源，不是反过来 |
| `CAND_CAP` | 16 | 1200 tok ÷ 每行渲染开销（纯规则行 ~30 tok，带证据行 ~110 tok，按 3 行带证据摊）≈ 16 |
| `SIGNALS_CAP_TOK` | 1200 | 同上 |
| `EVIDENCE_CAP` | 12 | 每规则活子行上界，纯库卫生；`0` = kill switch |
| evidence 渲染条数 | 无常数 | 由 packer 决定：按分歧度排序填到 `CANDIDATES_CAP_TOK` 用尽为止。初稿的 `EVIDENCE_SHOWN=2` 恰好等于 writer-zh 复现所需条数，解耦掉 |
| `DF_GATE_MIN` | 4 | df 噪声过滤是大 N 统计量，兄弟数 <4 时它恒为假（见 §3） |
| `BREADTH_FLAGS_FOR_WIDEN` | 2 | 区分"复述了规则"与"把规则用到第二个类别"的最小计数，定义上的下限 |
| `WIDEN_MAX_ATTEMPTS` | 2 | 两次机械拒绝后转 `widen_stalled` 交人 |
| `REVOKE_CONFIRM_SHADOW_HITS` | 3 | 三次"这条本来会被注入但用户没要回来" |
| `DEVIATION_STREAK` | 3 | 三次一次性 = 一个模式 |
| `DEVIATION_WINDOW_HITS` / `_S` | 10 / 14d | 双窗口取先到者：纯注入计数对低频规则永不关闭 |
| `REL_MIN` | 0.25 | 信号至少占该规则自身词汇质量的四分之一 |
| `TOP_RATIO` | 0.5 | BM25 分数跨语料不可比，比上榜首是唯一站得住的绝对切分 |
| `DF_FLOOR_RATIO` / `MIN_TERMS` | 0.3N / 2 | 一个稀有 bigram 是巧合 |
| `RETRO_SPANS` | 50 | 规则出生时回溯配对的历史 span 条数 |
| `RETRIEVAL_FIRST` / `EVIDENCE_CAP=0` | True / — | kill switch，见 §7 |

---

## 2. Write flow

触发不变：`BATCH_N=8` 或 `FLUSH_IDLE_S=30min`。整批静默仍然 0 调用。整段 check-drain-call-apply-sweep 在 `Pipeline` 的 `threading.RLock` 内（FastAPI 的同步 handler 跑在 AnyIO 线程池里，`/api/events/submit` 真并发；两次 submit 撞进同一个 in-flight flash 调用会跑两次抽取、双计 `deviation_count`，v1 能吸收是因为 `reinforce` 只是加一，v1.1 吸收不了）。

| # | 步骤 | 成本 |
|---|---|---|
| 0 | route-A 筛选、route-B span 归因（`signals.py`；lexicon 审计后会变，不是"untouched"） | 0 token |
| 0.5 | 若 `consolidate_due`：只跑 consolidation，本轮不跑 relation head，队列原样保留 | **flash（本轮唯一）** |
| 1 | 候选生成 `build_candidates`（`candidates.py` + `index.py`） | 0 token |
| 2 | relation head，一次 flash | **flash（本轮唯一）** |
| 3 | quote 验证、relation 赋值、子行写入、计数器 | 0 token |
| 4 | lifecycle sweep（revoke 确认、deviation streak、`needs_widen` 沿边武装） | 0 token |
| 5 | consolidation 触发检查 → 置 `consolidate_due`，**不在本轮执行** | 0 token |

一轮永远只含一次写路径生成调用。队列在 `apply_ops` 成功返回后才清；失败时快照恢复。若 `pending_count() >= 2 * BATCH_N`，抽取优先、consolidation 继续延后（防止队列在长期 consolidation 中饿死）。

### Step 1 — 候选生成

`build_candidates(index, store, a_spans, b_triples) -> (list[Requirement], debug)`

- `len(store.rules()) <= CAND_CAP` → 原样返回全部，不打分不过滤。这是审计一致要求的修正：v1 的失效模式是模型从 N 行里挑错行；一个前置词法过滤会造出一个全新的失效模式——正确的行根本到不了模型，而 head 此时又被明确指示回答 `new`。给定 `RECALL_CAP=32` 与 `CONSOLIDATE_ACTIVE=48`，真实库大多落在 5–40 区间，检索只在它划算的地方启动。
- 超过 cap：每信号 BM25F top-6，并入 exact-key 闭包与 facet-prefix 闭包，无条件并入所有处于 revoke 窗口的 `suspended` 规则和所有过分数门的 `retired` 规则（用户改主意时应当走到 `revive` 而不是造重复），过 abstain 门，去重，截 16，编号 `[1]..[M]`。
- 第二返回值是每信号 debug（`score`/`rel`/`dropped_because`），写 `data/candidates.jsonl`——**不写 `events.jsonl`**：`_learn_from_submit`（`server.py:71`）和 `submit_event`（`server.py:166`）每次 submit 各做一次 `events.read_all()` 全量解析，热路径上再加一类高频行不合适。这个日志是唯一能在不调 LLM 的前提下诊断误配对的东西。

### Step 2 — relation head（一次 flash）

`CANDIDATES:` 块，每行带状态，证据按 packer 预算填：

```
[3] (doc.toc, active, hits 4, breadth "指南") 指南开头应包含目录
      · ev(divergent): "年度总结也放个目录吧"
      · ev(founding): "这种…（略）"
[7] (email.length, suspended, revoke pending 1/3) 邮件控制在 120 词内
```

信号块统一编号 `A1..An` / `B1..Bm`。route-B 只送 `attribute_diff` 已经算出的 `user_added` 片段 + 每侧 200 字上下文，不送 `raw`/`polished`/`final` 全文。

Op 词表：`new | reinforce | contradict | revoke | revive | style_rule | noop`。`widen` **不在**这个词表里——`parse_ops` 改签名 `parse_ops(raw, existing, *, allowed: frozenset[str])`，抽取路径与 consolidation 路径各自白名单，否则抽取模型吐一个 `widen` 就绕过了只在 consolidation 路径运行的 `verify_widen`。

Prompt 相对 v1 的变化：

1. 每个 op 必须带 `span`（`A3`/`B1`），`parse_ops` 像校验 `target` 一样校验它在范围内。没有这个绑定，`verify_quote(quote, signal_text)` 无法实现——op JSON 里根本没有它来自哪个 span 的信息，而"在全部 span 里搜这句引文"等于没有守卫（从 span 3 摘的话能验证挂在 span 1 上的 reinforce）。
2. `reinforce` 必带 `quote`（≤80 字）与 `category_phrase`（用户命名的类别名词短语，无则 `""`）。明确告诉模型：*reinforce 是把证据归档到规则下，它永远不修改规则*。模型在这里不做任何 breadth 判断。
3. `new` / `contradict` 也必带 `quote` 与 `category_phrase`。这是初稿最致命的漏洞：初稿只给 `reinforce` 加了这两个字段，于是每条学到的规则出生时 `breadth=""`，`covers()` 短路成"无限定规则"，所有子行都是 `support`，`needs_widen` 永不触发——机制在它唯一存在意义的那类规则上恒为惰性。
4. `retire` → `revoke`，必带 `durability: durable|one_off|unclear`。
5. `noop` 强制：每个提交的 span 必须恰好被一个 op 认领。静默丢弃变成可审计的弃权。
6. 输出契约里 `quote` ≤80 字；`max_tokens` 从 1500 提到 2000；`parse_ops` 在 `JSONDecodeError` 时不再整批丢弃（`extraction.py:113-114` 现在返回 `[], ["unparseable"]`），改为从截断数组里抢救出所有闭合的顶层对象。八个各带 200 字 CJK 引文的 op 约 1900 token，撞 1500 上限就是整批静默丢失。
7. `noop`/`revoke`/`revive` 豁免 salience 门（`extraction.py:121-123` 的 `it.get("salience", 0)` 会让缺 salience 的 op 在到达 flag 路径之前就被 `continue` 掉，"可审计弃权"会静默不存在）。

### Step 3 — 落库（全 0 token）

`verify_quote(quote, span)`：NFKC 归一后的子串匹配，**只对该 op 声明的那个 span**；route-B 的 span 只暴露 `user_added` delta，不暴露 `polished`——`polished` 是我们自己注入的措辞，允许模型对着它取证等于把我们的词汇当成用户的话归档，`div_tokens` 随后读到的就是我们自己的词汇。

- `reinforce` → 父行 `strength += 1`；`add_evidence(...)`。函数从已载入的父行拷贝 `text`/`key`/`scope`/`breadth`，结构上无法修改规则。relation 由代码算（§3）。引文验证失败：仍加 `strength`，**不写子行**，写一条显式 flag 并计数——fail-open 写一条空 text 子行会让 `div_tokens` 恒为 ∅、`covers()` 恒真，等于悄悄退回 v1 行为且无任何信号。
- `new` → 建规则 + 一条 `relation="founding"` 的子行（引文已验证）；随后一次 0-token 的回溯 pass（§3 e）。
- `contradict` → 旧行 `transition(retired, reason="contradicted")` + `valid_to` + `superseded_by`；新行 `supersedes`；**子行改挂新行**（每条一次 append），证据不因它所支持的那次 supersede 而变孤儿。
- `revoke{durable}` → `transition(suspended, reason="user_revoke")`、`valid_to=now`、写 `relation="revoke"` 子行、面板出确认卡。立即离开 recall，用户可见行为即时生效。
- `revoke{one_off}` → 无状态变更；写 `relation="deviation"` 子行；`deviation_count += 1`，起始时记双锚点。
- `revoke{unclear}` → 只写 `relation="unclear"` 子行，**不计入任何退休路径**。初稿把"三次 unclear 自动退休"当成让弃权安全的不对称性来卖，这两句话互相矛盾：`unclear` 是模型的弃权 token，head 又被告知弃权是安全的，于是它会成为一切歧义 span 的默认落点，三次耸肩就能杀掉一条用户仍然想要的规则。
- `revive` → `transition(active)`、`valid_to=None`、revoke 计数清零。
- `add_evidence` 对 `(parent_id, normalized(quote))` 去重（重放/重试路径真实存在：`bench/runner/retry.py` 整单元重跑，`server.py:86-92` 下次 submit 重试 flush）。
- 每次 `_append` 内部调 `index.remove(id)` 再 `index.upsert(req)`——索引维护挂在 `Store._append` 这个唯一漏斗上，而不是挂在写路径 step 3 上。否则从 `POST /api/requirements` 手工录入的规则永远进不了索引 → 得分 0 → head 被指示回答 `new` → 保证生成用户自己规则的重复项。`upsert` 必须先摘旧 posting，否则同一 id 的重复 upsert 会把每个重复词的 `df` 计两次。

### Step 4 — lifecycle sweep（0 token，按 `flush_id` 幂等）

- suspended 规则：`shadow_hits >= REVOKE_CONFIRM_SHADOW_HITS` → `transition(retired, reason="user_revoke")`。
- `deviation_count >= DEVIATION_STREAK` 且双窗口未过期 → `transition(suspended, reason="behavioral_revoke")` + 面板卡；窗口任一过期则整条 streak 归零。**行为撤销永远不直接硬退休**，只能 suspend + 交人。
- 从活子行重算未解决分歧集势；`> widen_attempted_at_flags` 且 `not widen_stalled` → `needs_widen = True`。沿边武装，不是沿电平。
- `hit_count` / `shadow_hits` 在内存累积、每 flush 每规则落一条 delta 行，不是每次注入落一次整行快照。

---

## 3. P3 的结构性修复

### 来源说明（先把话说清楚）

初稿写的"Observed for real"不成立。该失败案例是 Suite E persona `bench/cases/personas/writer-zh.json` 的 round 2 / 6 / 8：round 2 的任务是 `实验室入组指南` 且 `natural_correction: "这种长文档开头给我加个目录"`，round 6 是 `年度工作总结文档`，round 8 是 `文献综述文档`。`目录` 在八个 persona 里只出现在这一个，L 的 54 个 case 里零出现。所以这是 1/8 个 suite 的诊断案例，最多值 Suite E 的 0.125。

evidence-under-rule 这个机制的正当性因此**不建立在这个案例上**，而建立在一条与 bench 无关的产品性质上：`store.py:82` 把每一次 reinforce 压成 `req.strength += 1`，于是面板永远无法向用户解释一条规则为什么被强化，consolidation 也永远无法对一条规则的真实覆盖面做任何推理。这是 provenance / 可检查性要求（约束 5），零 bench 输入即成立。writer-zh 从 v1.1 的验收数字里整体 hold out，单独作为诊断报告。

### 五个机制，只有最后一个需要模型

**(a) reinforce 路径上规则措辞不可达。** `add_evidence` 拷贝父行字段；`text`/`key`/`scope`/`breadth` 在该代码路径中不能变。规则措辞只在两处改：`contradict` 与 consolidation 的 `widen`。

**(b) 兄弟证据的原话留存且可检索。** 子行文本以 `children` 字段并入**父行**的 BM25F 文档，写侧 boost 0.35、读侧 0。R6 之后，ToC 规则的文档里含 年度/总结/文档 的 bigram，R8 的文献综述轮因此检索到同一条规则，而不是分叉出三条近重复窄规则。

关键修正（overfit 审计实测）：`self_score` 只算 `text`+`key`+`scope` 三个字段，**不含 `children`**。否则子行同时进分子和分母，而分母涨得更快——实测 22 条规则库、query = `写一份组会分享用的文献综述文档，开头放目录。`，doc = `指南开头应包含目录`：无子行 rel = 0.250，加两条子行后 rel = 0.209，直接被 `REL_MIN=0.25` 滤掉。P3 的检索机制会打死 P2 的 abstain 门。fixture 里加一条断言：*给规则挂一条子行，绝不能降低该子行本身能匹配的 query 对该规则的 rel*。

**(c) 分歧由代码判定，忽略模型标签。**

```
div_tokens(child, rule, siblings) =
    tokens(child.breadth)                                if child.breadth
    else novel_content_tokens(child.text vs rule.text),
         若 len(siblings) >= DF_GATE_MIN(4)：再过 df 门 df(t, siblings)*2 < len(siblings)

covers(rule, ev_toks) = True  当 rule.breadth_state == "global"
                             或 ev_toks ⊆ tokens(rule.breadth ∪ rule.text)
                             或 Jaccard ≥ 0.5
```

三处相对初稿的修正：

- `breadth_state` 三态。`""` 在初稿里同时表示"用户没命名类别"（常见情形，也正是窄规则的情形）和"这条规则是全局的"。现在 `unknown` 走 `else` 分支，只有 `global` 短路，且学习产生的规则永不出生为 `global`。
- df 门只在 `len(siblings) >= 4` 时启用。初稿的 `df(t, siblings)*2 < len(siblings)` 在 `len==0` 时对每个 token 恒为 `0 < 0` = False → `div_tokens = ∅` → `∅ ⊆ rule_toks` → `support`；在 `len==1` 时要求 `df==0`。这是把大 N 噪声过滤器套在 N≤3 的问题上，而 P3 只活在这个区间。
- `siblings` 集合排除被测子行自身。

**(d) `new` 写 founding 子行 + 回溯配对（e），保证首次 reinforce 时 `siblings` 非空。**

**(e) 规则出生时的 0-token 回溯。** 证据子行只能挂在父规则下，所以任何早于规则出生的兄弟信号在初稿里被永久丢弃——而"哪个兄弟当奠基者"不是随机的：`screen_message`（`signals.py:230-243`）对 `_KEY_LEXICON` 命中 +2，而该 lexicon 只覆盖 14 个 facet，于是系统系统性地偏向在 lexicon 覆盖的类别上建规则，然后再需要从中加宽出来。修法：`apply_ops` 执行 `new` 时，对最近 `RETRO_SPANS=50` 条已提交过的 span 跑一次 BM25F，过同一 abstain 门的挂为 `relation="founding_retro"` 子行。全是用户逐字原文，不是 §1 拒绝的合成引文回填。

（审计另建议再存一个"被筛掉的 1–2 分 span 环形缓冲"用于出生时重放——拒绝，理由见 §9 P5b。）

**(f) consolidation 是唯一的加宽者，标志强制入场。** `should_consolidate` 加第三条：存在 `needs_widen=True` 且 `not widen_stalled` 的规则。这一条必须有——`buckets()`（`consolidate.py:52`）只返回 ≥2 的组，一条孤立的窄规则永远组不成 bucket，标志会被搁死在安静的库里。被标记的规则作为单元素 bucket 进入，按 packer 预算渲染其活子行（分歧度高的优先）。

### `verify_widen`（重新设计）

初稿的门是"`tokens(new_breadth ∪ new_text)` 覆盖活分歧子行分歧 token 的并集"。这个门**拒绝一切真实的加宽**：正确的加宽用一个上位短语替换那些类别词，按构造就不含它们。"这类长文档开头都要有目录"的 CJK bigram 与 {年度,度总,总结} / {文献,献综,综述} 交集为空，Jaccard ≈ 0。唯一能过的是枚举式析取"指南、年度总结、文献综述开头都要有目录"——那不是加宽，第四个兄弟到来时还会再触发。反过来在宽松读法下这个门又是单调偏向过度泛化的：越全局越容易覆盖 token 并集。

v1.1 的门（对**实际展示给模型的那批子行**判定，不对全部——初稿让模型为它没看见的类别负责）：

1. `proposal.breadth != ""` 且非纯停用词 —— 类别槽必须保留，直接封死"跳到全局规则"。
2. 谓词保留：旧规则中非 breadth 的实义 token ⊆ 新文本 token（目录 / TL;DR 必须还在）。
3. 词汇锚定：`proposal.breadth` 的实义字符中，≥ `BREADTH_ANCHOR_MIN=0.6` 的比例、且其中心词（中文取末位 bigram，拉丁取末位非停用 token）必须出现在 {旧规则 text+breadth} ∪ {展示子行 text+breadth} 的并集词汇里。加宽短语必须由用户自己的词汇拼出来，不能凭空发明。
4. 反枚举：展示子行的 breadth 短语最多只能有 1 条逐字出现在提案 breadth 里。
5. `proposal.text != old.text`。

对真实案例检验：提案 breadth `这类长文档` 的实义字 {这,类,长,文,档} 中 4/5 在 founding 子行"这种长文档…"里锚定（`类` 不在），比例 0.8 ≥ 0.6；中心 bigram `文档` 在并集里 → (3) PASS。谓词 `目录` 保留 → (2) PASS。breadth 非空 → (1) PASS。未逐字含 ≥2 个子行 breadth → (4) PASS。落地。反例"所有回答开头都要有目录"：中心 bigram `回答` 不在并集 → 拒绝。

诚实地说：(3) 是启发式，中心词规则是语言相关的，会误拒某些合法措辞。可接受，因为被拒绝的加宽是安全的——子行原地不动，`needs_widen` 沿边解除，新的分歧证据到来时重新武装。

**加宽落地后为什么不会成环。** 初稿说"加宽后子行不再 divergent"——按纯词法这是假的：`年度总结` 在词法上仍然不被 `这类长文档` 覆盖。真正的机制是**记录而非重算**：`widen` 落地时给所有展示过的分歧子行打 `resolved_by=<新规则 id>`，sweep 重算集势时只数 `resolved_by is None` 的活子行。加宽之后到来的、确实属于新类别的证据仍可再次 divergent 并重新武装标志——重试由证据驱动，不由时钟驱动。初稿的 `WIDEN_COOLDOWN_S=6h` 因此整个删掉（墙钟窗口对爆发式用户和闲置用户差 3000 倍，而且每个 E persona 秒级跑完，冷却期在 bench 里按构造永不过期）。拒绝/弃权两次后 `widen_stalled=True`，停止武装，面板出卡。放弃是一个状态，不是重试。

### 复现：writer-zh ToC（诊断，不计入验收）

| 轮 | 发生 | 状态 |
|---|---|---|
| R2 | `new` 存下窄规则 `指南开头应包含目录`，`breadth="指南"`（用户原话命名的类别），founding 子行 `"这种长文档开头给我加个目录"` | 集势 0 |
| R2+ | 回溯 pass 扫最近 50 条 span，无更早兄弟 | — |
| R6 | 年度总结轮。head 回 `reinforce [n]`，`quote`/`category_phrase="年度总结"` 均通过验证。代码算 `div_tokens = tokens("年度总结")`，`covers` 假 → `relation="divergent"` | 集势 1 |
| R8 | 文献综述轮，同上，token 集与 R6 不同 → 第二个 distinct 分歧集 | 集势 2 ≥ 2 → `needs_widen=True` |
| 下一次 flush | `consolidate_due` 置位 | — |
| 再下一次 flush | consolidation 单独成轮，单元素 bucket 携全部活子行；模型给 `widen [k] → text "这类长文档开头都要有目录", breadth "这类长文档"`；`verify_widen` 五条全过；窄规则 `transition(retired, reason="widened")`，宽规则带 `supersedes` 写入且**清掉继承的 scope**（`contradict` 在 `store.py:96` 用 `op.get("scope") or dict(old.scope)` 继承旧 scope，加宽后仍被 recall 的 scope 过滤打回原形——所以 `widen` 是 `apply_ops` 的独立分支，不是 `contradict` 的别名），子行改挂并打 `resolved_by` | 集势归 0 |

不可复发的理由：原始的吞噬需要兄弟证据在到达时就被销毁。现在它按构造留存、由代码机械检测、唯一剩下的模型依赖是**措辞**，而措辞的退化是优雅的——坏提案被代码拒绝，弃权让子行原地等下一轮，误标 relation 只延迟修复不销毁任何东西。

诚实成本，与初稿一致：这是延迟修复而不是即时修复。第二条分歧子行到加宽落地之间，注入的仍是窄措辞。这个窗口是唯一需要打点的东西。加上 O7 的观察——writer-zh 的两条兄弟恰在 round 6/8，而 `E2E_SECOND_HALF_FROM = 9`，`BREADTH_FLAGS_FOR_WIDEN=2` 会让加宽正好落在第一个计分轮之前——所以 `{2, 3}` 的敏感性跑必须**预注册**并两个数都报，不能只报赢的那个。

### 新场景：审计者提出的 S-B（引文重复，跨同语言近义词）

R3 "调研类的回答要给出处" → 规则 `research.citation`，breadth `调研类`。R8 "这种技术方案文档也要标来源"。

- `出处` 与 `来源` 是近义词，CJK bigram 交集为零；`调研` 与 `技术方案文档` 同理。BM25F 得分 ~0，`MIN_TERMS=2` 的地板过不去，R8 的信号检索不到任何候选，head **正确地遵守指令**回答 `new`。于是 `research.citation` 与 `doc.citation` 并存。
- 初稿在这里会死：`buckets()`（`consolidate.py:53-58`）在 exact key 之后按 facet **prefix** 分组（`research` vs `doc`），两条永不相遇；两边各自积累子行，各自集势 ≤1，谁也不加宽。而初稿提出的"mutual BM25 `rel >= 0.6`"补救是循环论证——同一个刚刚检索失败的词法度量，用一个比已经漏掉它的 0.25 更高的阈值。实测 bench 自己的 gold 重复对：中英对 rel = 0.000/0.000，同语言改写对 0.422/0.393、0.426/0.475，0.6 什么都不触发，它是死代码，而第一个去看这个分数的人一定会把它调低——正是设计承诺不跑的调参循环。
- v1.1 的两条 0-token 修法：
  1. `buckets()` 增加按 facet **attribute** 分组（`key.split(".",1)[1]` → `citation`），`research.citation` 与 `doc.citation` 落进同一 bucket，走到 `merge`。
  2. `needs_widen` 在 attribute 组上计算：共享 attribute 的多条规则，其未解决分歧集势求并再计数。被拆开的证据流仍能触发标志。
- 走一遍：R3 建 `research.citation` + founding 子行；R8 建 `doc.citation` + founding 子行；下一次 consolidation，attribute bucket 把两条一起呈现，模型 `merge` 成一条，两边子行全部改挂幸存者，幸存者继承 `max` 集势（merge 不得洗掉待处理的 breadth 压力）。若模型判定两条确实是不同规则而不合并，两条继续各自积累，attribute 组的集势并集在第三条证据到来时触发加宽。
- 残留：跨语言重复（中文信号 vs 英文规则）会让 BM25 返回 0，attribute bucket 也依赖两边 `key` 的 attribute 恰好一致。新设计用本地轻量 embedding 补足这一召回缺口，再通过 RRF 与 BM25 融合；模型只产生候选，不能直接触发合并或退休。

S-C（`代码回答不要写解释` 下挂 `调研回答也别铺垫那么多` 与 `邮件直接说结论`）是子行真正异质的情形，正确行为是弃权。弃权后 `needs_widen` 沿边解除，两次后 `widen_stalled=True` 进面板，带着互相矛盾的引文交给人——这正是 human-in-the-loop 存在的意义，也是拒绝 `split` 的理由（§5）。

---

## 4. P2：配对与强制 abstain

### 候选生成

v1 是 `_index_block(store.active())`——整库进 prompt，让模型同时做检索、配对和判断。这同时是一个扩展性 bug：`INDEX_ROW_TOKENS=20` 截到 80 字，~100 条时 STORE 块本身就 ~4.5k token。

v1.1 用手写 BM25F（stdlib，~120 行，k1=1.2 / b=0.75 的 Robertson 默认值，引用而非调参）：字段 `text`（boost 1.0）、`key` 展开（2.0）、`scope`（1.0）、`children`（写侧 0.35 / 读侧 0）。Tokenizer：NFKC，拉丁词小写并把词干与表面形式**并列**加入，CJK 字符 bigram（Lucene CJK analyzer 的做法，不引 jieba、不引词典）。不设停用词表：idf 已经压住 的/了/the，而手写停用词表正是 bench 词汇可能渗入的地方。

### 强制 abstain

给 head 的原话：*CANDIDATES 是一个词法短名单，不是全库；如果没有候选表达 SAME facet，你必须回答 `new`，若其中没有任何持久规则则回答 `noop`。* 弃权是强制而非许可。

阈值三条（比初稿少一条）：

1. `rel = score / self_score(doc) >= REL_MIN(0.25)`，无量纲、语料内；`self_score` 不含 `children` 字段（§3 b）。承重门。
2. `score >= TOP_RATIO(0.5) * best_score`，该信号命中表内的比上榜首。BM25 分数跨语料不可比，比值是唯一站得住的绝对切分。
3. 地板：≥2 个不同命中词且 `df <= 0.3N`。一个稀有 bigram 是巧合。

**删掉初稿的第 (1) 条 `score >= median(idf)`。** 它的闭式推导是对的（tf=1、dl=avgdl 时 `(k1+1)/(1+k1)` 抵消），但统计量本身是退化的：实测同一 22 条规则库，vocab 160 词、df 直方图 `{1:139, 2:15, 3:1, 4:2}`，87% 是 hapax，于是 `median(idf) == max(idf)`。这个门的实际语义不是"匹配上一个典型词不算匹配"，而是"匹配上库里最稀有的词之一、且刚好压线"。规则库就是短的、近乎不相交的文档集合，这个退化是结构性的而非采样偶然；更糟的是它随重复项累积而不受控地松动（每个重复项把词推到 df≥2、拉低中位数），同一个信号会因为无关的库增长而时过时不过。审计建议改成"df≥2 词上的分位数"——不采纳，理由是剩下三条全是语料内比值、不需要任何 df 统计量，少一个旋钮胜过修一个旋钮。realized 的 `rel`/`df`/命中数分布每 flush 记一条到 `data/candidates.jsonl`，漂移可见。

### 阈值为什么不是 bench 拟合的

三条都是排序策略，以散文形式写在 `config.py` 里现有那句 "engineering constants, not tuned against eval data" 旁边，且**不允许因为 Suite L 或 E 的分数变动**，只允许因为陈述过的产品论证变动。每一次丢弃都带 `rel` 记录，决定由人审计而不是由指标审计。

但"不调参的承诺是一个控制手段，不是一个正当性论证"——这句审计意见是对的。所以 ship 步骤 2 的门不是 L，而是一个一等公民 fixture：`tests/fixtures/retrieval/`，80 条从产品推理写出来的合成规则 + 40 对手工标注的正确/错误配对（混合脚本、近义误配、跨语言），先于任何 L 跑提交，打印 `rel` / `df` / 子行数分布。

同时必须说清楚 `CAND_CAP=16` 的两个后果：

- **它是从 packer 推导的**（`CANDIDATES_CAP_TOK=1200` ÷ 每行渲染开销），不是选出来的。
- **它让整个 §4 在两个验收 suite 上都是惰性的**。E 的 persona 各带 3 条 gold requirement，16 轮下来的学习库很少接近 16 行；L 最大的 `existing` 是 5（`l-ddp-002` / `l-ddp-005`）。于是 `build_candidates` 对两个 suite 的每一个 case 都走"不足 cap，原样返回"分支，与 v1 的 `_index_block(store.active())` 字节等价。这意味着 ship 步骤 2 之后测到的 L 变化**只能归因于 prompt 变更**，与检索无关。这句话写进 ship note，避免把 prompt 改进读成检索验证。

### 已知残留

跨语言配对不再完全依赖 `_KEY_LEXICON`。BM25 与 key/scope 元数据保留可解释的词法召回，本地轻量 embedding 提供跨语言和改写召回，两路用 RRF 融合。lexicon 仍只允许因产品推理增长；dense 分数不设直接写库阈值，也不替代 consolidation 的关系判断。

（顺带：overfit 审计核对过 `_KEY_LEXICON` 的 14 个 facet 本身是否是 bench 的镜像——不是，bench 用到的 `notification`/`deploy`/`test`/`log`/`backup`/`indentation` 全不在表里。有问题的是 `_META_PAT` 和 `_RULE_PAT`，见 §9 O2。）

---

## 5. Consolidation

一次 flash，次数不变，但**不与 relation head 同轮**（§2 step 0.5）。

触发：`len(store.rules()) > 48`（注意是 `rules()` 不是 `active()`——evidence 行不得撑大这个计数），或 `adds_since >= 16`，或存在 `needs_widen` 且 `not widen_stalled` 的规则。无墙钟冷却。输入由 packer 截到 `CONSOLIDATE_INPUT_CAP_TOK = 3000`，溢出的 bucket 顺延下一轮。

Bucket 来源：exact facet key（不变）、同 facet prefix（不变）、facet **attribute**（新，§3 S-B）、unkeyed 组（不变）、`needs_widen` 单元素（新，携活子行）。mutual-BM25 近重复 bucket **删除**（§3 S-B 的实测）。

因为新增来源，bucket 不再互斥。`consolidate.py:77-82` 把各组拼进 `numbered` 再建 `pos = {r.id: n}`，同一 id 出现在两组时会被打印两次却只有一个编号映射回去，`merge [3] & [7]` 两个都指向同一 id 时能过 `store.py:113` 的 `len(targets) >= 2`，产出一条 `supersedes` 自己的幸存者。修：`numbered` 先按 id 去重再编号，bucket 渲染成去重后编号的集合，`merge` 在 `target_ids` 去重后不足 2 个时拒绝。

`consolidation_ops` 签名改成 `consolidation_ops(store)`（现在是 `consolidation_ops(store.active())`，拿到的是扁平 list，`active()` 排除 evidence 之后它结构上无法渲染子行）。连带 `bench/runner/providers.py:134-136` 的 `V1Provider.consolidate(existing)` 必须持有真实 Store——这条写进 ship 步骤，不是"以后再说"。

### widen

Prompt：*这是一条规则和归档在它下面的全部证据；如果证据跨越了措辞没有命名的类别，用能覆盖全部证据的最窄措辞重写规则，优先使用用户自己的类别词；绝不跳到全局规则；如果证据之间没有共同的更宽类别，什么都不要输出——弃权是正确的。* 随后 `verify_widen`（§3）机械判定，只对展示过的子行负责。被拒的 op 记 flag，绝不靠猜修补。`widen` 是 `apply_ops` 的独立分支（scope 清空理由见 §3）。

### split

不建。它需要一条真正新的落库路径（一退休两新增，子行按模型给的编号切分），是本设计里性价比最差的一项，且创造了一种全新的撕碎正确规则的方式。子行真正互相矛盾的规则会被弃权、`widen_stalled`、带着互相矛盾的引文出现在面板上。等真实库出现两规则纠缠的案例再说。

### merge

不变，加两条：所有目标的子行全部改挂幸存者；幸存者继承 `max(集势)`，merge 不能洗掉待处理的 breadth 压力。

### retire

consolidation 可以退休无支撑的规则（高 `hit_count`、零 support 子行、多 deviation），但对有 ≥2 条活 support 子行的规则，**除非给出 `superseded_by`，否则拒绝**。这是对综述里 blind-eviction 陷阱的直接防守。显式 consolidation retire 时子行转 `retired`（惰性、仍在文件里、仍可读）；**`bump_strength` 的自动退休绝不退休子行**——否则一条被误应用打到 `strength <= -2` 的窄规则会连带销毁它累积的分歧证据，正是从后门重新引入的 blind eviction。

### 子行淘汰

到 `EVIDENCE_CAP=12` 时，退休与父行 BM25 相似度**最高**的那条（最冗余的复述），绝不退休最老的——按年龄淘汰会系统性地丢掉机制赖以运行的分歧兄弟。对称地，当分歧子行多于 prompt 容量时，展示**得分最低**的那些：规则措辞覆盖得最少的证据。

### style_rule 治理

不变。

---

## 6. Recall 变更

```python
def recall(reqs, *, query="", context=None, index=None) -> list[Requirement]
```

- 池：`status == "active"` 且 `kind == "requirement"` 且 `valid_to is None`。suspended 规则在 durable revoke 落地那一刻离开 recall，同时 `shadow_hits += 1`（0 token，两阶段撤销的时钟）。
- 子行永不进 recall（`recall.py:39` 现有的 `kind` 过滤已经排除，零 diff），永不进 translator prompt。它们只通过 `hit_count` 和折进写侧索引的词汇影响 recall。
- 硬 scope 过滤不变，仍是过滤器而非打分项（绝不因信息缺失而排除）。
- `RECALL_CAP=32` 以下全量注入、不排序，与 v1 字节一致。融合打分对常见情形是惰性的，不会静默改变小库行为。
- 超过 cap：融合打分，仍然 0 LLM：

```
0.50 * bm25 / max(bm25 over pool)      # 比上榜首，无量纲，READ_BOOSTS（children 权重 0）
+ 0.15 * 0.5 ** (age_days / 30)
+ 0.20 * salience / 5
+ 0.15 * hit_count / (hit_count + 3)
```

初稿用 `bm25/(bm25 + median_idf)` 作饱和项——`median(idf)` 退化（§4），改成比上本次 query 的榜首。

`_key_hits_query`（`recall.py:24`）的处置必须说清楚，初稿的两句话不能同时成立（"保留旧路径所以 `tests/test_recall.py` 不动" vs "删掉 `_key_hits_query` 换成融合打分"）：**`index is None` 时融合式退化为 key-hit + recency（即 v1 的排序），`index` 存在时用完整融合式**。`translate()` 增加 `index=` 形参，`server.py` 显式传 `store.index`，所以超 cap 分支永远不会静默变成纯 recency。`_key_hits_query` 保留为退化分支的实现，`tests/test_recall.py` 不动。

`hit_count` 的接线在初稿里根本不存在：`translate()`（`translate.py:84`）内部算出 `known` 然后丢弃，返回的是 `applied_ids` 而不是 `recalled_ids`，`on_recall_hit` 没有任何调用者；`bench/runner/run_e2e.py:86` 更是拿裸 list 调 `_polish`，bench 下 `hit_count` 永远是 0，deviation 窗口永不过期，机制在本该测它的 suite 里不可测。修：`translate()` 返回 `recalled_ids`；`server.py` 转给 `pipeline.note_recall_hits(...)`；重写后的 `run_persona` 同样。

**不建：recall 侧的任何 breadth 过滤。** 初稿曾把"对确认规则强制 breadth 过滤、对 provisional 放宽"当作 P3 修复的快速一半。它不可能是：cap 以下没有任何东西可放宽，而且观察到的失败从来不是 recall 漏掉——窄文本 `指南开头应包含目录` 每轮都在被注入，是 composer 拒绝把它用到文献综述上。放宽不会改写那段文本，但会引入一条全新的、能丢掉正确规则的排除路径，用一个过度应用/过度排除的新失效模式换一个该代码路径产不出的收益。整条砍掉；`widen` 是唯一诚实的 P3 机制。

---

## 7. Call 与 token 预算表（重新核算）

估算器：`est_tokens(s) = 0.6 * len(CJK chars) + len(other) / 4`，与四份审计共用的 ~0.56 tok/char 校准一致（v1 的 `EXTRACTION_SYSTEM` 实测 3621 字 ≈ 1000 tok）。`tests/test_budget.py` 用真实 tokenizer 校一次上界并留 15% headroom，之后对拼装出的最坏 prompt 断言。

| 阶段 | calls | in | out | 说明 |
|---|---|---|---|---|
| translate（每轮） | 1 flash | ≤2.4k | ≤1.0k | system 290 + `style_block` ≤250 + 32×45 = 1440 + 用户文本 ≤400；`llm.complete` 默认 `max_tokens=1024` |
| 候选生成 | 0 | — | — | BM25F + KV 闭包，无持久化、无重建 |
| relation head（每 flush） | 1 flash | ≤3.8k | ≤2.0k | system ≤1300（三分 revoke rubric + 强制 abstain + `noop`/`quote`/`category_phrase`/`span`/`revive`，测试断言）+ `CANDIDATES_CAP_TOK` 1200 + `SIGNALS_CAP_TOK` 1200 + 脚手架 ~100 |
| apply + sweep | 0 | — | — | 引文验证、relation 赋值、计数器、状态迁移 |
| consolidation（独立轮） | 1 flash | ≤3.35k | ≤1.2k | system ≤350 + `CONSOLIDATE_INPUT_CAP_TOK` 3000 |
| **最坏轮 A：translate + flush** | **2 flash（写路径 1）** | **≤6.2k** | **≤3.0k** | **≤9.2k < 10k** |
| **最坏轮 B：translate + consolidation** | **2 flash（写路径 1）** | **≤5.75k** | **≤2.2k** | **≤7.95k < 10k** |

四处相对初稿的实质修正：

1. **translate 计入。** 初稿表格第一行写 "per user round (translate + send) | 0 calls"，而 `translate.py:81` 是一次 flash 调用。约束 2 对调用数限定的是写路径，对 token 上限限定的是"round total"，无限定词。计进来。
2. **consolidation 与 flush 不同轮。** `server.py:87-90` 现在是 `maybe_flush` 成功后立刻 `should_consolidate` + `run_consolidation`，这正是最坏情形可加的原因。改成置 `consolidate_due`，下一次 `maybe_flush` 入口单独跑。这一条同时把 A1、A4、A5 从 blocker 降为已解决。
3. **route-B 有界。** `extraction.py:89-93` 现在 `json.dumps` 全量 `raw`/`polished`/`final`，`server.py:80-85` 喂的是完整原文；route-A 有 `_SPAN_BUDGET=600`，route-B 一个上界都没有。一次用户往 composer 里贴 2000 字简报再编辑重写，就是一个 ~6000 字的 triple ≈ 3400 tok，而 `BATCH_N=8` 允许八个。改成只送 `attribute_diff` 已算出的 `user_added` span + 200 字上下文，整块过 `SIGNALS_CAP_TOK` packer。
4. **evidence 渲染计价。** 初稿把 `EVIDENCE_SHOWN=2` × ≤200 字引文记成 0；实际是 269 tok/行 × 16 = 4304。现在渲染条数不是常数，是 packer 的输出：按分歧度排序填到 `CANDIDATES_CAP_TOK` 用尽，每条 prompt 内引文截到 `INDEX_ROW_TOKENS*4=80` 字（落盘的子行保留完整 200 字——面板和 `verify_widen` 读的是库不是 prompt）。
5. **输出上限。** `max_tokens` 1500 → 2000，且 `parse_ops` 从截断数组抢救闭合对象，截断不再是整批静默丢失。

摊薄：稳态下每轮 ≤0.25 次写调用。早期学习期 consolidation 更频繁（加宽落地后子行被打 `resolved_by`，同一条规则不会再触发，无加宽循环），随后收敛回 v1 的频率。

相对 v1 变的是斜率不是次数：v1 的抽取 prompt 是 `O(store)`，~100 条时越界；v1.1 在候选 cap 以上保持平坦。生成式调用仍只走 writer/translator 通道；候选检索允许增加本地轻量 embedding 运行时，但必须支持 CPU 或集成显卡，且不得要求独立 GPU 或远程 API。

Kill switch：`EVIDENCE_CAP = 0` 停止子行写入，`needs_widen` 永不触发，库内容与调用画像回退到 v1，无需回滚代码。`RETRIEVAL_FIRST = False` 让 `build_candidates` 直接返回 `store.rules()`，即 v1 的整库索引——L 和 E 可以在同一个二进制里做 A/B 而不是跨分支，鉴于 E 有 ±0.2 的运行方差，这一点很重要。

---

## 8. 明确不做的事

- **重型或远程 embedding 基建。** 不引入要求独立 GPU 的模型，也不把外部 embedding API、常驻向量数据库作为默认依赖。允许 CPU/集成显卡可运行的本地轻量模型参与候选排序。
- **`split`。** §5。复杂度最高、证据最少，且新增一种撕碎正确规则的方式。
- **`provisional` 出生状态 + TTL 衰减。** 它的注入方式与 `active` 完全相同，买到的是一个 UI 徽章而不是精度，同时引入了微缩版的 blind statistical eviction：一条正确但少用的规则（季报格式）在第二次确认之前就衰减掉了。`SALIENCE_MIN=3` 已经在做出生过滤。
- **recall 侧 breadth 过滤及其 "provisional 放宽"。** §6。
- **`valid_from`、独立的 `evidence.jsonl`、evidence 回填脚本。** append-only 快照已让历史可重放；第二个文件把可检查性砍半却不增加能力；合成引文是伪造 provenance。
- **机械相似度复活（`REVIVE_SIM=0.80`）。** 一个不被充分理解的数字，能复活用户故意杀掉的东西。改为：suspended 与近似命中的 retired 规则始终在候选集里可达，复活需要显式 `revive` op 或面板按钮——这也是把 durable 撤销误读成 `one_off` 时最便宜的修法。
- **`Store.compact()`。** 审计（E11）提议 `.jsonl.new` + 原子改名。v1.1 不做：单用户、10^5 行以下时载入是毫秒级，而重写一个 append-only 文件需要一整套备份/校验语义。改为只做紧凑 delta 行（`{"id","op":"counters",...}`，载入时折进该 id 的记录），把增长斜率从"每 flush 32 条整行快照"降到"每 flush ≤32 条单字段行"。真实库超过 5 万行时再谈压实。
- **每次注入持久化 `hit_count`。** 会让 recall 变成写者。
- **自由形式的 agent 自编辑路径、权重编辑、索引全量重建、索引持久化。** 综述里点名的陷阱；索引是 `Store.__init__` 毫秒级重建的派生态，所以它不能偏离真相——并且有一条测试断言"N 次增量 upsert 后的 `df`/`avgdl`/posting 等于冷重建的值"，这是设计承诺过但从未检查过的性质。
- **无条件删除 v1 的 in-round widen 从句**（`extraction.py:33-36`，`754e651` 加入）。删它的论证是对的——flash 模型拿一个信号确实分不清"复述"与"用到兄弟类别"，加宽应该发生在两个兄弟都可见的地方。但它是**第二个**变更：放在 `INROUND_WIDEN: bool` 后面跑两臂，否则任何 E 的差值都无法在"证据留存起了作用"与"删掉从句起了作用"之间归因。注意这个从句里的四个 exemplar 字符串本身必须先按 §9 O1 换掉,两臂用的都得是去污染后的版本。

### 测量前置条件（不是可选项）

- **Suite E 现在测不到任何东西。** `bench/runner/run_e2e.py:55-66` 是一个 12 行影子 store，构造裸 `Requirement(text=...)`（无 key、无 scope、无 salience），只认 new/reinforce/contradict/retire，从不调 consolidation——子行、`needs_widen`、`widen` 对它全部不可见。`run_persona` 必须驱动真实的 `Store(tmp/store.jsonl)` + `Pipeline` + 每次 flush 后的 `should_consolidate`/`run_consolidation`，`_apply_ops` 删除。这与 v1.1 无关也是个正确性修复（它是产品不使用的第二份写路径实现），且 v1 臂必须用新 runner 重跑之后才能比较。
- **Suite L 的 harness 现在驱动不了候选生成。** `run_extraction.run_case`（`bench/runner/run_extraction.py:44-48`）构造 `existing = [Requirement(text=t) for t in case.existing]` 交给 `provider.extract(events, existing)`——没有 Store、没有索引、没有子行。`ExtractionProvider.extract` 改为接受 `Store`，`run_case` 从 `case.existing` 建临时 Store。
- **L 的评分口径必须先写下来再跑。** `_match`（`run_extraction.py:16-41`）逐字比较 `op["kind"]` 并对 `retire` 特判。三条映射：`revoke{durable}` → `retire`；`revoke{one_off|unclear}` → 剥离（等价于 `[]`，与 `l-rvk-005`/`l-rvk-006` 期望一致）；`noop` op 在比较前剥离（`noop`-only 输出评为 `[]`）。第三条尤其重要：`noise-reject-content` + `noise-reject-task` 共 12/54 个 case 的 gold 是 `[]`，强制 `noop` 会把这些 case 的输出从 `[]` 变成 `[{"op":"noop"}]`。原始 durability 判断另存一个文件单独统计——测量这个拆分、而不是微调 durability 提示词，才是攻 0.50 revoke 类别的诚实方式。
- **`writer-zh` 从所有验收数字里 hold out**，单独作为 P3 诊断报告（§3 来源说明）。
- **`BREADTH_FLAGS_FOR_WIDEN ∈ {2, 3}` 预注册敏感性跑**，`--repeat 3`，两个 E 数字都进 ship note。若 2 比 3 高出运行方差，说明这个常数在做 bench 的工作而不是产品的工作，要么重新论证要么改成 3。
- **prompt 去污染的 A/B**：旧字符串臂 vs 新字符串臂各跑一次 L，差值本身就是污染量，与 v1.1 的数字并列报告，不折进去。

---

## 9. 审计发现处置表

### 约束/预算审计（A）

| # | 级别 | 处置 |
|---|---|---|
| A1 §7 与 §5 的 consolidation cap 自相矛盾且已越 10k | blocker | 采纳。`CONSOLIDATE_INPUT_CAP_TOK = 3000`（不是 2200 也不是 4500），且 consolidation 移出 flush 轮（A5），§7 全表重算 |
| A2 route-B 载荷无上界 | blocker | 采纳其"更好"的那个方案：只送 `user_added` delta + 200 字上下文，整块过 `SIGNALS_CAP_TOK=1200`。拒绝"每字段截 400 字"的备选：`attribute_diff` 已经算出 delta，截全文严格更差 |
| A3 evidence 渲染 3600 tok 未计价 | blocker | 采纳，但不用固定的 top-3：渲染条数由 `CANDIDATES_CAP_TOK` packer 决定，prompt 内引文截 80 字，落盘保留 200 字 |
| A4 translate 被记成 0 call | major | 采纳。轮总量口径包含 translate，§7 表加行重算，最坏 9.2k |
| A5 consolidation 与 flush 同轮 | major | 采纳。`consolidate_due` 标志 + 下一次 flush 入口执行；队列积压超 `2*BATCH_N` 时抽取优先 |
| A6 `verify_widen` 拒绝后 `needs_widen` 永久武装 | major | 采纳并加强。沿边武装 + `widen_attempted_at_flags` + `WIDEN_MAX_ATTEMPTS=2` → `widen_stalled` 进面板；`WIDEN_COOLDOWN_S` 整个删除 |
| A7 `max_tokens=1500` 变成整批静默丢失 | major | 全采纳：`quote` ≤80 字、`max_tokens=2000`、`parse_ops` 从截断数组抢救闭合对象 |
| A8 可检查性退化（计数器行洪水 + 面板 evidence 洪水） | major | 采纳性质，拒绝其落点。计数器 delta 行写 `store.jsonl`（紧凑单字段行），**不写 `events.jsonl`**——该文件在每次 submit 被全量解析两次（`server.py:71`/`166`），热路径不能再加高频行。面板过滤 + 父子分组在 ship 步骤 1 落，不是"以后" |
| A9 `transition()` 不是唯一 status 写者 | minor | 采纳。`Store.update` 与 `bump_strength` 委派给 `transition`，`ALLOWED` 边表加 `manual`/`auto_strength`；PATCH 拒绝 `suspended`（挂起是写路径状态，不是用户可设状态） |
| A10 §6 两句话不能同时成立 | minor | 采纳。明确：`index is None` → 退化为 key-hit + recency（v1 排序），`_key_hits_query` 保留；`translate()` 显式接 `index`，超 cap 分支永不静默失序 |
| A11 `from_dict` 并非全 `.get()` | minor | 采纳（与 P8 同）。`text`/`id` 改 `.get()`，per-line `try/except` 计数跳过 |

### P3 机制审计（P）

| # | 级别 | 处置 |
|---|---|---|
| P1 学习规则的 `breadth` 从不被填充 → 机制惰性 | blocker | 采纳。`new`/`contradict` 强制 `category_phrase` 并过 `verify_quote`；`breadth_state` 三态拆分哨兵；学习规则永不出生为 `global` |
| P2 `verify_widen` 拒绝一切真实加宽、只放行枚举 | blocker | 采纳诊断，重设计判据（§3）：类别槽保留 + 谓词保留 + 用户词汇锚定 ≥0.6 且中心词命中 + 反枚举 + 已变更。采纳其"只对展示过的子行判定"，但不采纳"重跑 `covers` 要求全通过"——加宽后子行按词法仍不被覆盖，改用 `resolved_by` 记录解决而非重算 |
| P3 df 门在 0–2 子行时惰性；无 founding 子行；release note 算错 | blocker | 全采纳。`DF_GATE_MIN=4`；`new` 写 founding 子行；`siblings` 排除被测子行；release note 改为"升级前既有规则需 3 轮 post-upgrade 兄弟证据" |
| P4 重复规则拆分证据流，两边都到不了集势 2 | major | 全采纳两条修法：`buckets()` 增 attribute 分组；`needs_widen` 在 attribute 组上并集计算。同时删掉初稿的 mutual-BM25 bucket（与 O6 合并处置） |
| P5a 规则出生前的兄弟证据被销毁 + 筛选偏向 lexicon 覆盖类别 | major | 采纳。`new` 时对最近 `RETRO_SPANS=50` 条已提交 span 跑 0-token BM25F 回溯，过同门者挂 `founding_retro` |
| P5b 另存 1–2 分被筛掉 span 的环形缓冲 | minor | **拒绝**：它在库最易受影响的时刻（规则出生）重新引入筛选已判定为非规则设定的句子；回溯 pass 覆盖真实案例已足够 |
| P6 机械 strength 与加宽路径符号相反且 strength 赢 | major | 全采纳。`bump_strength` 走 `transition(reason="auto_strength")`；目标规则有 ≥1 未解决分歧子行或 `needs_widen` 时抑制 −1；自动退休绝不退休子行 |
| P7 展示子集却按全集判分；计数器与活行漂移；弃权后标志常驻 | major | 全采纳。判定只对展示集；集势从活子行重算、不落盘；弃权走 A6 的沿边解除 + `widen_stalled` |
| P8 `from_dict` 兼容性说法夸大 | minor | 采纳，同 A11 |

### 过拟合审计（O）

| # | 级别 | 处置 |
|---|---|---|
| O1 现网 prompt 里含四个逐字 bench 字符串 | blocker | 全采纳。四个 exemplar 换成语料外杜撰类别；`tools/check_prompt_contamination.py` 做 CI 门（`src/**/*.py` 的 prompt 字面量与 `bench/cases/**` 的 ≥6 字 n-gram 交集必须为空）；旧串/新串两臂各跑一次 L，差值并列报告 |
| O2 lexicon provenance 注释是假的，且 v1.1 把它提为承重件 | blocker | 全采纳。删掉 `signals.py:130` 那句注释；`_RULE_PAT`/`_META_PAT`/`_WITHDRAW_PAT` 逐条审计（每条一句产品理由或删除），结论落 `docs/lexicon-audit.md`；审计后重跑 L 并接受任何下跌。连带纠正初稿"§2 step 0 signals.py untouched"的说法 |
| O3 P3 的 "observed for real" 实为 writer-zh persona | blocker | 全采纳三条。§3 改述来源；证据留存改用 `store.py:82` 的 provenance/可检查性论证（零 bench 输入）；writer-zh 从验收数字 hold out |
| O4 children boost 抬高 `self_score` 打死 abstain 门 | major | 采纳。`self_score` 只算 text+key+scope；fixture 加断言 |
| O5 `median(idf)` 统计量退化 | major | 采纳诊断，取其第二方案：**整条门删除**，只留三条语料内比值。拒绝"df≥2 分位数"——少一个旋钮胜过修一个旋钮 |
| O6 `rel >= 0.6` 双向近重复不可达，双语说法为假 | major | 全采纳。bucket 整个删除，"包括双语对"那句删除；其功能由 attribute bucket（P4）承担；不采纳建议值 ~0.35——引入一个没有 fixture 支撑的新阈值就是它警告的调参循环 |
| O7 `BREADTH_FLAGS_FOR_WIDEN=2` 正落在计分边界 | major | 采纳。`{2,3}` 预注册敏感性跑，`--repeat 3`，两个数字都进 ship note |
| O8 生命周期窗口的单位对用户无意义 | major | 全采纳。revoke 确认改数 `shadow_hits`（该规则本来会被注入的轮次）；`WIDEN_COOLDOWN_S` 删除，改为证据条件；`DEVIATION_WINDOW` 改为注入数与墙钟双窗口取先到 |
| O9 三次 unclear 静默退休；不对称性为假 | major | 采纳并加强。`unclear` 不计入任何退休路径；`one_off` streak 只能 suspend + 面板卡，绝不自动硬退休；durability 拆分的产品理由独立于分数陈述（真实用户确实会为单次任务撤回规则，v1 的二元 retire 无法表达） |
| O10 `CAND_CAP=16` 让 P2 修复在两个 suite 上都惰性 | major | 全采纳三条。16 的推导改为从 packer 反推；检索 fixture 成为一等公民并作为 ship 步骤 2 的门；ship note 明写"步骤 2 的 L 差值只归因于 prompt 变更" |
| O11 强制 `noop` 与 12/54 个 gold-`[]` case 冲突 | minor | 采纳。评分口径在跑之前写死（§8） |
| O12 一批无推导常数；`EVIDENCE_SHOWN=2` 与复现案例耦合 | minor | 采纳。每条常数在 `config.py` 给一行它所约束的产品量（§1 表）；`EVIDENCE_SHOWN` 取消常数化，改由 packer 决定 |

### 工程审计（E）

| # | 级别 | 处置 |
|---|---|---|
| E1 `transition()` 抛异常会在部分提交后炸掉整批 | blocker | 全采纳。`transition` 返回 `(ok, reason)`，`transition_or_raise` 只给面板；队列在 `apply_ops` 成功后才清，失败快照恢复 |
| E2 无锁，`maybe_flush` 可重入，新计数器是阈值触发 | blocker | 全采纳。`Pipeline` 加 `threading.RLock` 覆盖 check-drain-call-apply-sweep；sweep 按 `flush_id` 幂等 |
| E3 `transition` 不是唯一入口，其中一个是公开 HTTP | blocker | 全采纳，同 A9。PATCH 拒绝 `suspended` |
| E4 `verify_quote` 无法实现——op 与 span 无绑定 | blocker | 全采纳。信号编号 `A1..An`/`B1..Bm`，每个 op 必带 `span` 并在 `parse_ops` 校验范围；route-B 只对 `user_added` delta 验证，绝不对 `polished`/`final` 全文 |
| E5 索引归属与 df 记账未定义，`median(idf)` 静默漂移 | blocker | 采纳前两条：`index.upsert` 移进 `Store._append`，`Index.remove(id)` 先摘旧 posting，加"增量 == 冷重建"的断言测试。第三条自动消失——`median(idf)` 门已删（O5） |
| E6 `consolidation_ops(reqs)` 看不到子行，改签名会断 bench seam | major | 采纳。签名改 `consolidation_ops(store)`；`V1Provider` 持有真实 Store；写进 ship 步骤 |
| E7 `parse_ops` 共享导致 `widen` 绕过 `verify_widen` | major | 采纳。`parse_ops(raw, existing, *, allowed: frozenset[str])`，每个 op 只走拥有它的验证器 |
| E8 必填字段失败策略未定义，`salience` 默认 0 静默丢 op | major | 全采纳。`noop`/`revoke`/`revive` 豁免 salience 门；引文不可验证的 `reinforce` 加 strength、不写子行、记显式 flag |
| E9 新 bucket 源使 bucket 非互斥，`pos` 折叠重复 | major | 全采纳。`numbered` 先按 id 去重再编号；bucket 渲染为编号集合；`target_ids` 去重后 <2 个的 merge 拒绝 |
| E10 `needs_widen` + 持久弃权 = 无界 flash 循环；冷却期无归属 | major | 全采纳，同 A6。冷却期删除，取而代之的是持久在规则行上的 `widen_attempts` / `widen_attempted_at_flags` / `widen_stalled`（不再受 `create_app()` 重启影响） |
| E11 计数器快照使文件超线性增长，loader 全量读 | major | 部分采纳。紧凑 delta 行采纳；`Store.compact()` **拒绝**在 v1.1 落（§8，理由：单用户规模下载入是毫秒级，而重写 append-only 文件需要一整套备份/校验语义，成本高于收益，5 万行时再谈） |
| E12 重放/重试不幂等 | major | 全采纳。`add_evidence` 按 `(parent_id, normalized(quote))` 去重；每次 flush 的所有产出行带 `flush_id` |
| E13 混版写入会剥掉新字段；`superseded_by` 有两个真值源 | major | 采纳，但把"版本超前则拒绝打开"降级为"只读打开 + 面板横幅"——降级场景下硬拒绝等于把产品砖化。`schema_version` + `_append` carry-forward 未知键 + `superseded_by` 仅在键缺失时推导，全部采纳 |
| E14 `hit_count` 没有接线路径，bench 路径永远递增不了 | major | 全采纳。`translate()` 返回 `recalled_ids`；`server.py` 转 `pipeline.note_recall_hits`；重写的 `run_persona` 同样 |
| E15 FakeLLM 可测性退化（fake 按下标硬编码 `target`） | major | 全采纳。`tests/fakes.py::FakeLLM` 解析 `CANDIDATES:` 块、按规则文本脚本化、记录 prompt 供预算断言；sweep 接显式 `now`/`flush_id` |
| E16 Suite L harness 驱动不了候选生成 | major | 全采纳。`extract` 接 `Store`；`run_case` 建临时 Store；revoke→retire 映射落在 `V1Provider`，durability 另存 |
| E17 evidence 行漏进面板；事件日志在热路径上增长 | minor | 全采纳。`/api/requirements` 默认 `include_evidence=0` + 父子分组；候选 debug 写 `data/candidates.jsonl` |
| E18 "两阶段撤销"实为延迟退休，相位时钟是用户吞吐 | minor | 采纳。常数改名 `REVOKE_CONFIRM_SHADOW_HITS` 并改数 shadow hit；第二相位同时是一张面板确认卡（0 token）。文案里不再叫它"确认" |

---

## 10. 实现分解（TDD 里程碑）

每个里程碑独立可绿。测量点只在 N4 与 N6 之后，回归可以二分到单个 commit 而不是"v1.1"。

### N0 — 测量与来源修复（必须最先落，且先于任何数字）

- 文件：`src/memtranslator/extraction.py`（四个 exemplar）、`src/memtranslator/signals.py`（lexicon 审计 + 删假注释）、`tools/check_prompt_contamination.py`、`docs/lexicon-audit.md`、`bench/runner/run_e2e.py`（删 `_apply_ops`，驱动真实 Store+Pipeline+consolidation）、`bench/runner/run_extraction.py`（`run_case` 建临时 Store）、`bench/runner/providers.py`（`extract(events, store)`、revoke→retire 映射）、`bench/runner/config.py`
- 测试：`test_prompt_has_no_bench_ngrams`、`test_lexicon_terms_all_have_justification`（审计文件与 pattern 逐条对齐）、`test_run_persona_uses_real_store`、`test_run_persona_triggers_consolidation`、`test_run_case_builds_store_from_existing`、`test_revoke_durable_grades_as_retire`、`test_noop_stripped_before_match`
- 验收：污染门在 CI 上绿；v1 臂用新 runner 重跑并记录为新基线（旧的 L 0.852–0.926 / E 0.125–0.375 全部作废）；旧串/新串两臂 L 差值单独记录；`writer-zh` 从聚合数字中排除

### N1 — schema + store 收口

- 文件：`schema.py`（新字段、`SCHEMA_VERSION`、`from_dict` 加固）、`store.py`（`rules()`/`children()`/`transition()`/`ALLOWED` 边表、`update`/`bump_strength` 委派、counters delta 行、`flush_id`、carry-forward 未知键、只读模式）、`server.py`（PATCH 拒绝 `suspended`）
- 测试：`test_v1_rows_load_byte_identical`、`test_malformed_line_is_counted_not_fatal`、`test_unknown_kind_skipped_with_counter`、`test_transition_illegal_edge_returns_false_not_raises`、`test_apply_ops_never_raises_on_adversarial_batch`、`test_update_status_goes_through_transition`、`test_bump_strength_autoretire_has_reason`、`test_patch_rejects_suspended`、`test_counter_delta_row_folds_on_load`、`test_v1_writer_cannot_strip_new_fields`（carry-forward）、`test_future_schema_version_opens_read_only`
- 验收：116 个既有测试全绿且未改动；`data/store.jsonl` 的既有行加载后 `to_dict()` 与原文逐字段相等

### N2 — 并发与预算脚手架

- 文件：`pipeline.py`（`RLock`、队列后清、`flush_id`、`consolidate_due`）、`server.py`（consolidation 移出 flush 轮）、`budget.py`（`est_tokens` + packer）、`config.py`（全部 cap 常数 + 一行推导注释）、`tests/fakes.py`
- 测试：`test_concurrent_submits_produce_one_extraction_call`、`test_queue_survives_apply_failure`、`test_sweep_idempotent_per_flush_id`、`test_consolidation_never_shares_round_with_flush`、`test_worst_case_round_under_10k`（用 FakeLLM 记录的真实 prompt 断言）、`test_est_tokens_upper_bounds_real_tokenizer`
- 验收：最坏轮预算断言绿；`FakeLLM` 可按规则文本脚本化并记录 prompt

### N3 — evidence 子行与 relation 赋值

- 文件：`schema.py`（evidence kind）、`store.py`（`add_evidence` + 去重 + `EVIDENCE_CAP` 冗余度淘汰）、`extraction.py`（`quote`/`category_phrase`/`span` 契约、`parse_ops` 白名单与截断抢救、salience 豁免）、`divergence.py`（`div_tokens`/`covers`）、`server.py`（面板过滤 + 父子分组）
- 测试：`test_reinforce_cannot_mutate_parent_fields`、`test_new_writes_founding_child`、`test_first_reinforce_after_new_can_be_divergent`（P3 的 `DF_GATE_MIN` 回归）、`test_df_gate_disabled_below_four_siblings`、`test_learned_rule_never_born_global`、`test_unverifiable_quote_files_no_child_but_flags`、`test_quote_verified_against_declared_span_only`、`test_route_b_quote_cannot_come_from_polished`、`test_truncated_json_salvages_complete_ops`、`test_evidence_eviction_drops_most_redundant_not_oldest`、`test_panel_excludes_evidence_by_default`
- 验收：拿一条窄规则 + 两条异类别兄弟的手写 fixture，跑完 sweep 后 `unresolved_distinct_divergence == 2`；`EVIDENCE_CAP=0` 时全部子行写入消失且行为与 v1 等价

### N4 — 索引、候选生成、relation head

- 文件：`index.py`（BM25F + `remove`/`upsert`）、`candidates.py`、`lexicon.py`、`extraction.py`（`CANDIDATES:` 块 + 强制 abstain）、`store.py`（`_append` 内维护索引）、`tests/fixtures/retrieval/`
- 测试：`test_incremental_index_equals_cold_rebuild`、`test_manual_requirement_enters_index`、`test_child_never_lowers_parent_rel`（O4）、`test_below_cap_returns_all_rules_unfiltered`、`test_abstain_forced_when_no_candidate_clears`、`test_candidates_block_within_cap_tok`、`test_retrieval_fixture_pairing_recall`（fixture 门）、`test_widen_not_in_extraction_allowed_set`
- 验收：检索 fixture 上的配对 recall/precision 达到 fixture 自带的目标；`rel`/`df` 分布打印并入档。**跑一次 L**，ship note 明写差值只归因于 prompt 变更

### N5 — sweep + consolidation widen

- 文件：`consolidate.py`（`consolidation_ops(store)`、attribute bucket、去重编号、`needs_widen` 单元素 bucket、`widen` prompt）、`verify.py`（`verify_widen`）、`store.py`（`widen` 分支 + `resolved_by` + merge 继承集势 + retire 守卫）、`sweep.py`
- 测试：`test_widen_accepts_narrowest_covering_rewrite`（ToC 案例，诊断用）、`test_widen_rejects_global_jump`、`test_widen_rejects_enumeration`、`test_widen_rejects_unanchored_breadth`、`test_widen_clears_scope`、`test_resolved_children_stop_counting`、`test_widen_flag_rearms_only_on_new_divergence`、`test_widen_stalls_after_two_attempts`、`test_attribute_bucket_pairs_research_and_doc_citation`（S-B）、`test_heterogeneous_children_abstain_and_stall`（S-C）、`test_buckets_deduped_before_numbering`、`test_merge_rejects_single_distinct_id`、`test_retire_blocked_on_supported_rule_without_superseded_by`、`test_autoretire_does_not_retire_children`、`test_strength_penalty_suppressed_when_widen_pending`
- 验收：一条**无 founding 子行**的手写 fixture（模拟升级前既有规则）经 3 轮兄弟证据后完成一次端到端加宽；`writer-zh` 单独跑并报告加宽落地的轮号。**跑一次 L**，并跑 `BREADTH_FLAGS_FOR_WIDEN ∈ {2,3}` 的 E 敏感性

### N6 — 两阶段撤销

- 文件：`extraction.py`（durability rubric）、`store.py`/`sweep.py`（suspend/revive/shadow hits/deviation 双窗口）、`server.py`（面板确认卡）
- 测试：`test_durable_revoke_leaves_recall_immediately`、`test_unclear_never_counts_toward_retirement`、`test_one_off_streak_suspends_never_hard_retires`、`test_deviation_window_expires_on_wallclock_or_hits`、`test_revive_clears_counters`、`test_suspended_rule_stays_in_candidate_set`
- 验收：durability 三分的原始判断被单独 dump；L 的 revoke 类别与 v1 基线对比并同时报告 durability 拆分的分布

### N7 — recall 融合 + hit 接线

- 文件：`recall.py`（融合式 + `index` 形参 + 退化分支）、`translate.py`（返回 `recalled_ids`、接 `index`）、`server.py`、`pipeline.py`（`note_recall_hits`）、`bench/runner/run_e2e.py`
- 测试：`test_recall_below_cap_byte_identical_to_v1`、`test_recall_above_cap_without_index_falls_back_to_key_hits`、`test_translate_returns_recalled_ids`、`test_hit_count_persisted_once_per_flush`、`test_shadow_hits_advance_for_suspended`、`tests/test_recall.py` 全部不改动仍绿
- 验收：`hit_count` 在 bench 路径上确实递增（否则 deviation 窗口与融合式在 E 上仍不可测）

### N8 — 面板与可检查性收尾

- 文件：`web/`、`server.py`（`?include_evidence=`、父子分组、`widen_stalled` / revoke 确认 / 分歧证据三类卡片）
- 测试：`test_requirements_endpoint_groups_children_under_parent`、`test_stalled_widen_surfaces_in_panel`、`test_revoke_confirmation_card_shape`
- 验收：一条被加宽过的规则，在面板上能看到它的窄措辞历史、触发加宽的两条用户原话、以及 `retire_reason="widened"` 的链路

---

## 遗留的诚实结论

v1.1 买到的是**可修复性**（加宽所需的证据现在存在、可检索、可审计、可被人接管）与一条**有界的修复路径**（沿边武装、两次失败即交人）。它没有买到"永不复发"：第二条分歧证据到加宽落地之间仍有延迟窗口，措辞质量仍依赖 flash 模型，`verify_widen` 的词汇锚定是启发式，跨语言重复率会上升。这三条是要打点的对象，不是要在 release note 里抹掉的东西。

同时必须记住 N0 的结论：在污染修复与两个 bench runner 重写完成之前，这条分支上的每一个 L 和 E 数字都不能用来接受任何东西。
