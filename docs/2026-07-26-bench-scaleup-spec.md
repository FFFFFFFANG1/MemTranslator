> **我的独立复核（2026-07-26，在 agent 裁定之上二次核验一手页面）**
>
> | 断言 | agent 结论 | 我核到的 | 处置 |
> |---|---|---|---|
> | AgentIF (THU-KEG) | 许可三方冲突→弃 | HF 卡片确为 `cc-by-nc-4.0`，707 条人工标注实例 | ✅ **弃用成立**——NC 挡商用，且与论文附录 GPL-3.0 说法冲突，冲突未解决即无授权 |
> | AgentIF-OneDay | 存在，MIT | 确实存在（xbench/AgentIF-OneDay），`license: mit`，104 个任务；附件只给文件名不打包 | ✅ **我之前怀疑 owner 记错，是我错了** |
> | WildIFEval | Apache-2.0，主力供给 | 卡片确为 `apache-2.0`，test split 7,523 例，字段仅 `conversation_id` + `decomposition` | ✅ 成立;且**只发 decomposition 不发原文**，恰好绕开上游 LMSYS-Chat-1M 的 gated 条款 |
> | PEP 8 | public domain | 文档 Copyright 节自述已置于公共领域 | ✅ 成立（数值需变异是**测量**要求，非许可要求） |

# MemTranslator Bench 扩容终版规范（Suite R）

> 依据：dev @ `06a13bc`；产品常量均引自 `src/memtranslator/config.py`、`src/memtranslator/schema.py`、`src/memtranslator/recall.py`、`src/memtranslator/store.py`（本轮逐个读过）。所有语料事实带 URL；标注「卡片声明」的表示只在 HuggingFace/GitHub 卡片上核到，未见 LICENSE 文件。

---

## 0. 一句话总览与去留

**Suite R（Lifecycle Replay）**：12 个 scenario，每个是一条 ~112 事件的有序日志 + 一份 56 条 constraint 的 catalogue；任意前缀的 gold 状态由日志 fold 出来而非二次手写；在 8 个 checkpoint 上以 chained / segment / oracle 三种模式分别测「链式复利后的存量正确性」「单段写入」「纯读出」。

去留（不给选项）：

| 现有 | 处置 | 理由 |
|---|---|---|
| T，60 case | **原样保留**，retag `tier: unit`，权重 0.4 → **0.25** | 唯一有人工抽检背书的判据（29/30，`bench/gen/judge-audit.md`）；`preserve-long 0.40` 是活跃缺陷，R 不覆盖 |
| L，54 case | **原样保留**，retag `tier: unit`，权重 0.3 → **0.25**；**不扩容** | op 种类判定的低方差单点测量仍有价值；密集 store 下的 targeting 由 R-segment 覆盖，再加 18 条是重复投资 |
| E，8 persona × 16 轮 | **从 gate 退役**，不计权重，保留为 `E-legacy` 冒烟 | 3 条规则的 store 在结构上测不了 selection / consolidation / retirement；chained 模式在 R 里以 112 轮深度承接了它唯一独有的复利测量 |
| E 的 8 个 persona 文件 | **升级为 r-01..r-08 的种子** | `dev-zh` / `writer-zh` / `minimalist-zh` 等的 3 条规则进 catalogue 作 `first_seq ≤ 6`，16 轮变成 16 个 event，历史逐条数字仍可对照 |

114 个 case 一条不删。新权重 **T 0.25 / L 0.25 / R 0.50**。

**阈值不继承。** `GATE_OVERALL = 0.80` / `GATE_PER_SUITE = 0.70`（`bench/runner/config.py`）是按 v1 E 语义定的，同一批 run 在两把尺下读出 0.802 与 0.500，这笔账现在不必再算——R 的量纲与二者都不同。R **前两次全量跑不设 gate**，只出水位与 scenario 聚类 CI，之后由 siriux 定线。

---

## 1. 语料源裁定表

「可原文入库」= 可把 constraint 文本逐字放进开源 repo 并商用。这一列决定项目能不能开源，是硬约束。

### 用（原文可入库）

| 源 | 许可（来源 URL） | 预算条数 | 备注 |
|---|---|---|---|
| WildIFEval | Apache-2.0，卡片 + API tag 核实 https://huggingface.co/datasets/gililior/wild-if-eval | **~240**（每 scenario ~20） | 24,731 条去重原子 constraint，delivery 关键词命中 6,588 unique，超供 3–6 倍。发布件只含 conversation_id + decomposition，不触发 LMSYS-Chat-1M 的 gated 条款 |
| Google styleguide（Python/Java/Shell/Markdown） | CC BY 3.0，README + LICENSE 正文核实 https://github.com/google/styleguide | **~100** | 唯一天然供给 scope 冲突的源（Py 80 / Java 100 / PEP 8 79）。`source` 字段必须常驻 |
| Google developer documentation style guide | CC BY 4.0，页脚声明 https://developers.google.com/style | **~90** | `/style/highlights` 已是扁平原子规则表。与 GOV.UK 的 serial comma 冲突是设计好的 supersede 素材 |
| GOV.UK A-to-Z | OGL v3.0，页脚声明 https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/style-guides/a-to-z-style-guide/ | **~50 + 词条填充** | 旧 `www.gov.uk/guidance/style-guide` 已 301，引用新路径。词条型规则是 regex 判据的最便宜来源，但受 40% filler 上限约束 |
| M-IFEval | Apache-2.0，LICENSE.txt 逐字核实 https://github.com/lightblue-tech/M-IFEval | **~40** | `ja:startend:sentence_unified_end`、`fr:detectable_content:informal_address` 支撑 1 个 scope.lang scenario；id 命名空间直接对应 `scope.lang` |
| IFBench（Ai2） | 数据 ODC-BY-1.0 / 代码 Apache-2.0，README 明写 https://github.com/allenai/IFBench | **~30 + checker 代码** | 只取 `format:*` 家族；42/58 是 palindrome / prime_lengths 一类谜题约束，整类拒收。checker 代码直接复用 |
| IFEval | Apache-2.0，registry 文件头 + 卡片 https://github.com/google-research/google-research/tree/master/instruction_following_eval | **~25（模板，须改写）** | 判据模板价值高于文本；短句 boilerplate 是反 overfit 最高危项，入库前必须改成 user-voice 措辞 |
| PEP 8 | Public domain，Copyright 节逐字 https://peps.python.org/pep-0008/ | **~30（数值必须变异）** | 唯一零许可负担的源，但被 backbone 背熟：79→96、4 空格→2 是**测量要求**，不是许可要求 |
| Conventional Commits / Keep a Changelog / SemVer | CC BY 3.0（站点页脚）/ MIT（LICENSE 文件）/ CC BY 3.0（semver.md 尾部）https://www.conventionalcommits.org/en/v1.0.0/ · https://keepachangelog.com/en/1.1.0/ · https://raw.githubusercontent.com/semver/semver/master/semver.md | **~40（合计）** | 唯一一组 constraint 之间有真实依赖的素材，独占 1 个 release-engineering scenario。RFC 2119 关键词直接映射 `strength`；与本项目自有 commit 规则（`[scope] content`）天然冲突，是现成 supersede 对 |
| AgentIF-OneDay（xbench） | MIT，卡片 YAML 声明（**仅卡片**，GitHub 镜像无 LICENSE）https://huggingface.co/datasets/xbench/AgentIF-OneDay | **~30** | **owner 没记错，此物存在**，正确拼写 AgentIF-OneDay，与清华 AgentIF 是两个组两件东西。只取 rubric / task 文本，**绝不 vendor 附件**（内含 WEF 报告、歌词 PDF 等第三方版权物）。209 条负分判据是 `must_not_carry` 措辞的好来源 |
| PRISM（`system_string` / `open_feedback` / `self_description`） | 人写文本 CC BY 4.0，模型回复 CC BY-NC 4.0，卡片分栏声明 https://huggingface.co/datasets/HannahRoseKirk/prism-alignment | **~60 + 12 个 identity** | 唯一真实用户自述「怎么交付」的语料，是 `surface.signal.text` 的主要供给。**只碰人写字段**；~64% 是价值/安全表述（"no racism"），属于产品明令不存的 CONTENT 类，必须过滤，正好当 distractor |
| InFoBench | MIT，卡片声明 + 代码库 LICENSE https://huggingface.co/datasets/kqsong/InFoBench | **~20** | 质量补充；Format 标签需人工拆「制品身份」与「交付规则」 |
| ComplexBench | MIT，仓库根 LICENSE，API spdx_id 核实 https://github.com/thu-coai/ComplexBench | **~15** | 只取 en 侧且非题材绑定者；中文字数约束不能直接换算英文词数 |

合计预算 **~770**，实需 12 × 56 = **672**，留 15% 过滤余量。

### 慎用

| 源 | 许可 | 处置 |
|---|---|---|
| FollowBench | Apache-2.0，仓库根 LICENSE https://github.com/YJiangcm/FollowBench | 文本可入库，但 constraint 只以两级 prose 的差分形式存在，需 LLM diff 抽取并逐条抽检。**本轮预算 0**，列为储备源 |
| Multi-IF | 代码 Apache-2.0 / **数据 CC BY-NC 2.0** https://huggingface.co/datasets/facebook/Multi-IF | **只借设计不借文本**：turn 2/3 的「裸 constraint 语句」形态正是 `{"type":"natural"}` 的形状，照此自写；一个字不进 repo |
| PrefEval | CC BY-NC 4.0，仓库 LICENSE https://github.com/amazon-science/PrefEval | **足迹冻结**，不扩大。R 的 content-preference distractor 全部自写，不从 PrefEval 摘录——避免为零 delivery 产出加深 NC 暴露 |

### 弃

| 源 | 弃因（带证据） |
|---|---|
| AgentIF（THU-KEG） | 许可三方打架：HF 卡片 `license: cc-by-nc-4.0`（https://huggingface.co/datasets/THU-KEG/AgentIF），论文附录 B 称 GPL-3.0 + 仅学术研究，GitHub 根目录无 LICENSE。**未解决的冲突不是授权**；GPL-3.0 加在数据上对开源商业产品更糟 |
| CFBench | 仓库全树无 LICENSE，GitHub API `license: null` https://github.com/PKU-Baichuan-MLSystemLab/CFBench。结构最贴合我们的 schema（原子文本 + 类型 + 主需/次需优先级），仍然只能弃。想要就发信要授权 |
| CELLO | 无 LICENSE https://github.com/Abbey4799/CELLO；且 13 个 criterion 塌成 ~9 个模板，文本锁在中文 prose 里 |
| Microsoft Writing Style Guide | 全权保留，Learn 使用条款「personal and non-commercial use」且禁改 https://learn.microsoft.com/en-us/legal/termsofuse。比 CC BY-NC 更差（连研究授权都没有）；其覆盖面 Google devdocs + GOV.UK 已免费给全 |
| Chicago Manual of Style | 订阅制、机构条款明写不转让任何版权 https://www.chicagomanualofstyle.org/help-tools/Terms-of-Use/Terms-of-Use-Institutions.html。系统性改写编辑手册还构成汇编作品的演绎 |
| AP Stylebook | 专有付费；且 apstylebook.com / ap.org 在本环境不可 fetch，**一手许可未核实**——按自有证据标准即应弃 |
| LaMP | CC BY-NC-SA 4.0（viral ShareAlike）https://github.com/LaMP-Benchmark/LaMP；LaMP-6 还需 LDC 付费协议。且它按设计不含任何显式 preference 文本 |
| Persona-Hub | 数据 CC BY-NC-SA 4.0 + 卡片附加「research purposes only」+ 上游模型条款透传 https://huggingface.co/datasets/proj-persona/PersonaHub。买回来的只是 12 句职业描述，identity 我们自己写 |
| PersonalLLM | 许可最干净（CC BY 4.0 / MIT）但**没有任何文本**——user preference 是 reward model 权重向量 https://huggingface.co/datasets/namkoong-lab/PersonalLLM |
| IFEval-Ko | Apache-2.0 但语义与 IFEval 完全重复 https://huggingface.co/datasets/allganize/IFEval-Ko。**保留其唯一有用发现**：84 条 case 因 change_case 在韩文脚本中无意义而被删——这是 `scope_dead` 失效类型的现实依据 |
| MCJudgeBench | 无数据发布（abs 页与 v1 全文均无 repo/HF 链接）https://arxiv.org/abs/2605.03858；constraint 全部继承自 ComplexBench/InFoBench。**保留其发现**：judge 总体准确不代表逐 constraint 类型可靠 → 我们的 judge 抽检必须按 facet 分层 |
| EIFBench | 论文过 EMNLP 2025，但 https://github.com/Hope-Rita/EIFBench 全树只有一个 10 字节 README |

---

## 2. Scenario schema

文件：`bench/cases/replay/<id>.json`。四块：`identity` / `notice` / `constraints` / `events` + `checkpoints`。

```json
{
  "id": "r-devdocs-en",
  "schema_version": "R1",
  "identity": {
    "who": "devtools 公司的资深技术写作者",
    "apps": ["editor", "docs-site", "slack"],
    "tasks": ["reference-page", "release-note", "pr-review", "email"],
    "langs": ["en-US"]
  },
  "notice": [
    {"source": "Google developer documentation style guide",
     "license": "CC-BY-4.0", "url": "https://developers.google.com/style",
     "use": "verbatim"},
    {"source": "WildIFEval", "license": "Apache-2.0",
     "url": "https://huggingface.co/datasets/gililior/wild-if-eval",
     "use": "verbatim"}
  ],
  "constraints": [ /* 56 条 catalogue，见下 */ ],
  "events":      [ /* ~112 条有序日志 */ ],
  "checkpoints": [ /* 8 个前缀探针 */ ]
}
```

### 2.1 catalogue 条目（gold entity，**不是** `Requirement`）

刻意不是产品记录：SUT 会用自己的 id 和自己的措辞落库，harness 负责对齐（§4.1）。

```json
{
  "cid": "c-line-96",
  "gold_text": "你给我写的 Python 代码按 96 列折行，不是 80。",
  "key": "format.line_length",
  "kind": "style_rule",
  "scope": {"lang": "python", "app": "editor"},
  "salience": 4,
  "facet_family": "layout",
  "role": "chain",
  "provenance": {
    "source": "google/styleguide pyguide 3.2",
    "license": "CC-BY-3.0",
    "url": "https://github.com/google/styleguide",
    "use": "adapted",
    "mutation": "80 -> 96 columns (de-memorisation)"
  },
  "distinctive": "96 列",
  "grade": {
    "mech": {"name": "contains_all", "args": {"keywords": ["96"]}},
    "judge_criterion": "改写后的请求明确要求把 Python 代码按 96 列折行。"
  },
  "conflicts_with": ["c-line-79"],
  "first_seq": 12,
  "final_status": "active"
}
```

字段说明：

- `cid` — bench 内部稳定 id。产品记录的 hex id 永不出现在 case 里（`extraction._index_block` 用编号正是因为 flash 抄 id 会错）。
- `gold_text` / `key` / `kind` / `scope` / `salience` — 全部是产品 schema 原字段（`src/memtranslator/schema.py`），不新造词表。
- `facet_family` ∈ `{length, structure, tone, lexicon, language-register, artefact-form}`，是统计分层与 judge 分层抽检的单位。
- `role` ∈ `{chain, independent, filler}`。`chain` = 参与 CRUD 链或 scope 冲突；`filler` 硬上限 40%（lint 强制）。
- `provenance` — 逐条许可溯源，`bench/NOTICE` 由其并集生成。`use` ∈ `{verbatim, adapted, mutated, original}`。
- `distinctive` — 反 overfit 锚：一个变异后的数字或自造词。`tests/test_no_bench_contamination.py` 增加一道守卫，把全部 `distinctive` 哈希后 grep `src/`。
- `grade.mech` — **判据作用在改写后的请求文本上，不是作用在下游产出的制品上**。这是本规范最容易搞错的地方：SUT 的输出是一句被改写的**请求**，不是一段 Python 代码，所以 `max_line_length` 之类的制品级 checker 在这里是范畴错误。可用的机械判据只有请求级词法判据（§4.2）。
- `grade.judge_criterion` — 逐条手写，不在运行时生成。
- `conflicts_with` — lint 用它断言两条永不同时 active。

### 2.2 event 记录

日志是唯一可变的叙事；每条 event 同时声明 SUT 看得见的输入与作者写定的状态转移。

```json
{
  "seq": 37,
  "at": "2026-03-11T09:12:00Z",
  "surface": {
    "kind": "signal",
    "signal": {"type": "natural", "text": "别再写 “utilise” 了，用 “use”，以后都这样"}
  },
  "effect": {"op": "new", "cid": "c-lex-utilise", "salience": 4},
  "label": "clear",
  "signoff": ["siriux", "fang"]
}
```

`surface.kind` 三取一：

- `signal` — 载 `{"type":"natural","text":…}` 或 `{"type":"edited_diff","raw":…,"polished":…,"final":…}`，即产品现有的两种 signal 形状。
- `request` — `{"text":…, "context":{"app":…,"task":…,"lang":…}}`。一次热键。只有同时是 probe 时才计分。
- `distractor` — 必须产生零 op 的 signal：content preference、单次指令（"这次短一点"）、任务步骤。`effect.op = "none"` 且带 `why ∈ {content_preference, one_off, task_step}`。

`effect.op` 词表严格等同产品：`new | reinforce | contradict | retire | merge | none`，外加一个 bench-only 标记 `scope_dead`。payload：

| op | payload |
|---|---|
| new | `{cid, salience}` |
| reinforce | `{cid}` |
| contradict | `{cid, new_cid}` |
| retire | `{cid}` |
| merge | `{cids: [...], new_cid}` |
| scope_dead | `{cid}` |

`label` ∈ `{clear, ambiguous}`。**ambiguous 的事件不删。** 双人复核不一致时记 `label: "ambiguous"` 并给 `accept: ["retire","contradict"]`（可接受 op 集合），它们进单独报告的 `R-amb` band，不进 headline。这是对原方案「有歧义就改写或降级成 distractor」的推翻：L 的 `revoke` 今天卡在 0.50 正是因为真实用户语句在 retire / contradict 之间本就模糊，把这批删掉等于把 bench 提纯成分布里容易的一半，然后在它最该测的类别上读出高分。

### 2.3 checkpoint 与 probe

```json
{
  "cp": "cp-05", "after_seq": 72,
  "expect": {"active": 42, "invalidated": 7},
  "probes": [
    {"pid": "r-devdocs-en/cp-05/p1",
     "request": {"text": "写 2.4 CLI flag 改名的 release note",
                 "context": {"app": "docs-site", "task": "release-note", "lang": "en-US"}},
     "must_carry":     ["c-sentence-case", "c-second-person", "c-no-utilise"],
     "must_not_carry": ["c-oxford-off@v1", "c-heading-title-case@v1"],
     "may_carry":      ["c-link-text"],
     "mech": [{"name": "same_language"},
              {"name": "not_contains", "args": {"keywords": ["utilise"]}}]}
  ]
}
```

`expect` 是构建期断言，由 fold 导出后回填，不是手写。

checkpoint 位置固定，卡在两条从未被测过的产品阈值上（`config.py`：`RECALL_CAP = 32`、`CONSOLIDATE_ACTIVE = 48`）：

| cp | after_seq | 累计引入 | 累计失效 | active | 意图 |
|---|---|---|---|---|---|
| cp-01 | 14 | 14 | 1 | 13 | 早期，对照 E-legacy 的 3 规则区间 |
| cp-02 | 28 | 26 | 3 | 23 | |
| cp-03 | 42 | 35 | 5 | 30 | 刚好卡在 RECALL_CAP=32 之下 |
| cp-04 | 56 | 42 | 6 | 36 | **首次越过 cap，recall 必须开始选择** |
| cp-05 | 72 | 49 | 7 | 42 | |
| cp-06 | 88 | 56 | 7 | **49** | **越过 CONSOLIDATE_ACTIVE=48，consolidation 首次在密集 store 上触发** |
| cp-07 | 100 | 56 | 14 | 42 | 紧接一次 contradict + merge 密集簇 |
| cp-08 | 112 | 56 | 19 | 37 | 终态 |

catalogue 定为 **56 而非 50**：要让峰值 active 越过 48 同时携带真实比例的失效条目，catalogue 必须超过 50。这是对 owner 原始「~50 条」的一处有理由的偏离，写在这里备案。

---

## 3. 56 条的构成与 ground truth

### 3.1 构成配额（lint 强制）

每个 scenario 的 catalogue：

- 总数 56 ± 4，其中 7 条是 contradict / merge 产生的后继记录。
- `role: chain` **≥ 20**（承担分数的部分，单独出 `R-crud` 子分）。
- `role: independent` ≥ 20，且横跨 **≥ 6 个 facet_family**。
- `role: filler` **≤ 22（40% 硬顶）**。超过即拒绝加载。凑到 50 条的最便宜路子就是 GOV.UK 式词条规则——它们必被召回、必被判对、从不冲突、从不失效；放任到 60% 就会得到一个又大又平又漂亮、但什么都没测的数字。

终态（cp-08）**37 active / 19 invalidated**，失效原因配额：

| 原因 | 条数 | 期望 op | 素材来源 |
|---|---|---|---|
| `superseded` | ≥ 7（含 1 条三级链 A→B→C） | `contradict` | 真实源之间的冲突：PEP 8 79 vs Google Py 80 vs 变异后 96；Google devdocs serial comma vs GOV.UK；Conventional Commits `type(scope):` vs 本项目自有 `[scope] content` |
| `revoked` | ≥ 6 | `retire` | PRISM `open_feedback`（CC BY 4.0）的撤回语句 |
| `merged` | ≥ 5，分 ≥ 2 组（一组 2→1、一组 3→1） | `merge` | 在日志中相隔 15–25 个 event 埋近重复，避免相邻即可发现 |
| `scope_dead` | ≥ 1 | `retire`（或 scope 收窄至永不匹配） | IFEval-Ko 的 84 条 change_case 在韩文脚本失效，是唯一有据可依的「scope 消失而非规则变错」范例 |

另有 6 条**故意有缺陷**的记录（`defect` 字段标注）：scope 过窄（已知的窄规则吞同族）、text 过泛、key 打错、一对近重复。它们是明牌，用来给 S-W 式的 widening / merge 事件当靶子。

### 3.2 gold 怎么确立

**核心机制：gold 不手写，由日志 fold 出来。**

`bench/replay/gold.py::gold_state(scenario, k)` 把 events[1..k] 的 `effect` 折叠进一个以 `cid` 为键的参考状态机，输出：

```json
{"c-line-96":  {"status": "active", "strength": 3, "since_seq": 12,
                "supersedes": null},
 "c-line-79":  {"status": "invalidated", "reason": "superseded",
                "invalidated_at_seq": 12, "successor": "c-line-96",
                "was_active_for": 8},
 "c-dup-a":    {"status": "invalidated", "reason": "merged",
                "invalidated_at_seq": 51, "successor": "c-bullets-merged"},
 "c-jp-keigo": {"status": "invalidated", "reason": "scope_dead",
                "invalidated_at_seq": 74, "successor": null}}
```

这个状态机与 `Store.apply_ops` 语义必须一致，靠一条 fuzz 等价测试钉死（`tests/test_gold_matches_store.py`，10k 条随机 op 流）。这是整套设计能成立的支点：**你写日志，gold 自己掉出来**，600+ 条 constraint × 8 个前缀的答案不需要任何人手写，也就消灭了最大一类静默标注错误。

三类 ground truth 的可信度不同，明说：

1. **失效状态本身** —— 构造性为真。日志说 seq 12 的 contradict 让 c-line-79 死了，那么此后任何前缀上它不是 active，这是定义，不是推断，不需要 judge 也不需要标注员。
2. **`must_carry` / `must_not_carry`** —— 由 lint 从 gold 导出，不允许作者手写。规则：`must_carry` 的 cid 必须在该前缀 active 且 scope 与 probe context 相容；`must_not_carry` 的 cid 必须已失效或尚未引入；**且每个 `must_not_carry` 必须与同 probe 内某个 `must_carry` 共享 `key` 前缀**——否则这个陷阱是白送的。
3. **`effect` 字段本身** —— 这是唯一由人判断的一层，也是最弱的一环（§7）。非 `new` 的 effect 全部双人签字，不一致的走 `label: "ambiguous"` 单独成 band，并**公布逐失效原因的作者分歧率**。

「仍然失效」在每个 `invalidated_at_seq` 之后的前缀上有两条独立断言：

- **STATE**：对齐后的 SUT 记录不得为 active。失败记 `zombie`。
- **BEHAVIOUR**：同 checkpoint 上把该 cid 列入 `must_not_carry` 的 probe，改写里不得携带它。失败记 `behavioural zombie`。

只测 STATE 不行：一条「已 retire 但仍被召回注入」的规则和一条「仍 active 但从不被召回」的规则在状态空间里长得一样，在产品里是两回事。

**revival**：两个 scenario 在撤回 ~20 个 event 后重新陈述同一规则，gold 期望一条全新 active 条目。SUT 若改为把旧墓碑翻活（status 回 active 且 strength 保留），记为通过并单独统计——产品对此没有既定立场，bench 不替它拍板，但要把两种行为的比例报出来。

---

## 4. 评分协议

### 4.1 对齐（state 计分的前置，也是最脆的一环）

SUT 记录 → gold cid，三级，先便宜后贵：

1. 机械：`distinctive` 子串命中，或 `key` + scope 精确匹配且无竞争者。
2. 机械：同 `key` 桶内与 `gold_text` 的 token 重合度 ≥ 0.6。
3. judge：**一次**窄二元调用，候选限定在共享 `key` 前缀的 cid 内，context 只给 `{"stored_text": …}`。判据沿用已过抽检的 L 措辞：「这条已存要求陈述的规则与以下要点相同：\<gold_text\>」。窄 context 是 2026-07-24 已落地的决定，同一对样本全 context 判 [T,F,T]、窄 context 判 [T,T,T]。

未匹配的 SUT active = phantom；未匹配的 gold active = miss。

**对抗对照集**：随附 40 对手工构造的近义反例（同 facet、实为不同规则），对齐器必须拒绝 ≥ 0.9，否则**不输出 state 分**。宽松的对齐器会把「存了个差不多的东西」洗成命中，更糟的是它会掩盖 zombie——zombie 只有先被对齐才会被计入。

### 4.2 机械判据管什么

判据全部作用在**改写后的请求**上。可用的注册项（扩 `bench/runner/checkers.py`，现有只有 `contains_all` / `not_contains` / `same_language`）：

| checker | 管什么 |
|---|---|
| `contains_all` / `not_contains` | 变异后的 distinctive token 在不在（"96" 在、"80" 不在） |
| `regex_present` / `regex_absent` | 词条型规则（GOV.UK "写 X 不写 Y"）、SemVer 官方版本号正则 |
| `same_language` | zh-in→zh-out |
| `preserves_request_ratio` | bench 侧独立断言 `PRESERVE_MIN_RATIO = 0.85`，不只依赖产品自带护栏。P0「translator 从改写翻转成直接作答」的 bug 正是在这一层能在密度下被抓住 |
| `numeral_present` | 变异数值这一类的专用快捷判据 |

**`must_not_carry` 的绝大多数是机械可判的**（前驱条目的 distinctive token 不出现 = `not_contains`），这是负例侧最值钱的性质：反 dump 的那一半几乎零 LLM 成本。

明确纠正原提案里的一处范畴错误：`max_line_length`、`serial_comma`、`commit_shape`、以及直接 import IFBench 的 `format:*` checker，全都是在校验一段**产出的制品**；把它们套在「帮我 review 这段 asyncio 装饰器」这句被改写的中文请求上，量的是那句中文的行宽。因此「≥60% 断言零 LLM」的原估算作废，按词法判据重估为 **~40%**，下面的成本模型按 40% 算。

### 4.3 judge 判据管什么

余下 ~60%：`must_carry` 的语义携带、对齐的第 3 级。仍是一判据一调用一二元，fail-closed，parse flag 上报（`bench/runner/judge.py` 现有行为不变，`deepseek-v4-pro`、thinking disabled、temperature 0）。

**准入门槛**：一条 constraint 能进 `must_carry` 计分，必须满足其一——(a) 有请求级机械判据；(b) 有手写 `judge_criterion` 且其 facet_family 的抽检一致率 ≥ 0.9。不满足的降级为 `may_carry`，两个方向都不计分。这既保住了「标签必须可操作」的纪律，又不至于把 tone / method 这半个产品域整片砍掉——那半个才是产品真正赚钱的地方。

**分层抽检**：不是全局抽 30 条。按 6 个 facet_family 各抽 ≥ 20 条人工核对，逐 family 报一致率。依据是 MCJudgeBench 的发现——总体准确的 judge 在特定 constraint 类型上仍可能不可靠（https://arxiv.org/abs/2605.03858）。现有 29/30 的背书是在 1–3 规则 context 下拿到的，不自动转移到 50 条 context。抽检行由 `bench/runner/make_audit.py` 扩出（每行已带完整 judge context）。

### 4.4 分数定义

checkpoint 的 state 分：

```
active_f1       对齐后 active 集的 F1
zombie_rate     gold 已失效但 SUT 仍 active / gold 失效数
chain_fidelity  superseded 的 SUT 后继记录 supersedes 指向正确前驱的比例（纯机械）
S = 0.5*active_f1 + 0.3*(1 - zombie_rate) + 0.2*chain_fidelity
```
phantom_rate 单独报告，只通过 F1 的 precision 入分，不重复计一次。

probe 的 rewrite 分：

```
机械闸门：preserves_request_ratio 与全部 mech 判据，任一不过则该 probe 记 0
carry    = 判定命中的 must_carry / |must_carry|
suppress = 1 - (判定命中的 must_not_carry / |must_not_carry|)
W = 0.6*carry + 0.4*suppress
```

聚合：checkpoint 分 = `0.5*S + 0.5*mean(W)`；scenario 分 = 8 个 checkpoint 均值；R = 12 个 scenario 均值。

另出三个独立数字，不并进 headline：`R-crud`（只算 `role: chain` 的条目，这才是该驱动工程优先级的数）、`R-amb`（歧义 band 的宽容集判定）、`R-legacy`（E-legacy 冒烟）。

### 4.5 三个强制对照臂

每次全量跑各跑一次，不是脚注：

| 臂 | 做法 | 判定 |
|---|---|---|
| `null-dump` | 从不 retire，按 strength 取前 32 条无脑注入 | 若其 suppress 半边与真系统相差 < 0.05 → **本次 run 作废**，不是打个标记 |
| `flat-dump` | store 正确，但绕过 `recall()` 直接注入全部 active | 若 R-oracle 无法把真系统与它分开 → 如实发布「50 条尚不构成读路径压力」，而不是发布一个 suite 分数。50 条约 1,250 token，flash 上下文吃得下，这个前提是可证伪的 |
| `oracle-ceiling` | 完美 store + 完美注入的 stub | < 0.9 说明断言本身不可满足，是 case 文件有 bug，不是产品有 bug |

### 4.6 三种运行模式

同一条日志，三种跑法：

- `chained` —— store 全程带下去，复利在内。**gate 指标。**
- `segment` —— 每个 checkpoint 注入 `gold_state(prev_cp)`，只重放 (prev_cp, cp] 区间的事件。纯测写路径，无继承误差。
- `oracle` —— 注入 `gold_state(cp)`，不学习，只判 probe。纯测读路径。

`chained − segment` 定位复利；`chained − oracle` 定位习得误差。现有 `run_e2e.py::_reset_to_gold` 就是它的 3 规则退化版，而它已经产出过本项目最有价值的一个结论（repaired 0.841 vs chained 0.727，27 点里只有 11 点是记忆）。

重复次数：**chained ×2、segment ×2、oracle ×2**。产品侧 `GEN_TEMPERATURE = 0.0` 已经钉住了生成方差，3 次 chained 重复是按 E 时代的噪声水平定的，现在没必要；而 segment / oracle 是唯二有资格声称 checkpoint 级独立性的模式，统计功效主要来自它们，不能只跑一次。

### 4.7 统计功效

**CI 必须以 scenario 为聚类单位 bootstrap（12 个簇），永远不要报 checkpoint 级 CI。** chained 模式下 96 个 checkpoint 分携带的信息量约等于 12 个 scenario；报 checkpoint 级 CI 会宣称一个不存在的精度，这正是当前 bench 已经犯过一次的错（8 persona 的二项分布压在 0.8 的悬崖上）。

单趟 pass 的断言量与区间（假设 `p = 0.8`）：

| 量 | n（单趟） | 分层后 | 95% CI 半宽 |
|---|---|---|---|
| rewrite 断言（288 probe × ~5） | 1,440 | 6 个 facet → 每 facet 240 | 朴素 ±0.051；按 scenario 聚类 DEFF ≈ 1.95（ρ 假设 0.05，m=20）→ n_eff ≈ 123 → **±0.071** |
| state 断言 | 96 cp × ~45 = 4,320，高度相关 | 有效单位 = 12 个 scenario | scenario 间 SD 0.10 → **±0.057**；SD 0.15 → ±0.085 |
| `R-crud` 子分 | 12 × 8 × ~20 | 12 个簇 | ≈ ±0.07 |

对照现状：T 的每类别 n=10，`p=0.5` 时 Wilson 95% CI ≈ [0.24, 0.76]，半宽 ±0.26；E 第二半程 8 persona × 8 轮 × ~1 断言 = 64 个观测且无 facet 拆分，实测 persona spread 最大 0.50。**这就是本次扩容要买的东西：可以据以排工程优先级的类别分。**

ρ = 0.05 是假设，不是测量值，第一次全量跑必须实测并回填；若 CI 半宽 > 0.08，如实报出并且不设 gate。

也顺带说明为什么是 12 而不是 20：簇数从 12 加到 20，SD=0.10 时 CI 半宽只从 ±0.057 收到 ±0.044，而要多写 8 个 scenario（约 450 条 constraint、900 个 event 的双人复核）。12 是收益拐点。

---

## 5. 生成管线

| 步 | 内容 | 自动/人工 |
|---|---|---|
| P1 | 按 §1 预算从各源拉取候选 constraint，落 `bench/gen/harvest/<source>.jsonl`，逐条带 `provenance` | 自动（脚本 + 已有 fetch） |
| P2 | delivery/content 二分过滤（丢弃 PRISM 的价值安全表述、WildIFEval 的任务步骤、AgentIF-OneDay 的文件存在性判据） | flash 初筛 + **人工全量过目** |
| P3 | 归一化为 catalogue 条目：填 `key` / `scope` / `salience` / `facet_family` / `kind` | flash 起草 + **人工抽检 10%** |
| P4 | 变异：数值参数强制变异（79→96、4→2、100→96）；无数值可变异的高记忆度规则（"headings 用 sentence case"）**取反或丢弃**，取反语义不安全就丢 | 人工逐条 |
| P5 | 写 `distinctive` 与 `grade`（mech 判据 + judge_criterion） | 人工逐条（这是 must_carry 计分的准入条件，不能自动） |
| P6 | 编日志：安排 `first_seq`、埋近重复、插 distractor、写 `effect` | 人工；`surface.signal.text` 的措辞可由 PRISM 真实用户语句改写 |
| P7 | 双人签字：所有非 `new` 的 `effect`。不一致 → `label: "ambiguous"` + `accept` 集合 | **人工，双人** |
| P8 | fold 出 gold，回填 `checkpoints[].expect`，lint 导出 `must_carry` / `must_not_carry` | 自动 |
| P9 | lint 全绿 + 许可 lint + NOTICE 生成 | 自动（CI） |
| P10 | facet 分层 judge 抽检（6 × 20）+ 40 对对抗对齐集 | 人工 |

### lint 检查项（`bench/replay/lint.py`，零 LLM，进 CI）

1. 每个 `must_carry` 的 cid 在该前缀 gold 中 active，且 scope 与 probe context 相容。
2. 每个 `must_not_carry` 的 cid 在该前缀已失效或未引入。
3. 每个 `must_not_carry` 与同 probe 内某个 `must_carry` 共享 `key` 前缀（陷阱不许白送）。
4. `conflicts_with` 对永不同时 active。
5. catalogue ≥ 48 条，终态失效 17–21 条，四种失效原因各达配额。
6. `role: filler` ≤ 40%；`facet_family` 覆盖 ≥ 6。
7. 所有 `use: verbatim` 记录的 license 落在白名单 `{Apache-2.0, MIT, CC-BY-3.0, CC-BY-4.0, ODC-BY-1.0, OGL-3.0, public-domain}` 内。
8. 来自 PEP 8 / google-styleguide 的数值型条目必须带 `provenance.mutation`，否则拒绝。
9. 所有非 `new` 的 `effect` 必须有 `signoff` 两人。
10. `gold_state` 重放结果与 `checkpoints[].expect` 一致。

### 人工审核 checklist（每个 scenario 签字前逐条打勾）

- [ ] 56 条里每一条都能想象成某个真人真的说过——不是「某语料里有这句」。这条口径必须扛住 case 数 15 倍的膨胀。
- [ ] 每条 `distinctive` 在 `src/` 里 grep 不到。
- [ ] 每条数值型 style-guide 规则已变异并记录。
- [ ] 每个 `must_not_carry` 陷阱都在同一个 facet 上，不是话题无关的送分题。
- [ ] 每个非 `new` 的 `effect`，两人独立给出同一 op；不一致者已标 `ambiguous` 并写好 `accept` 集合，**没有被删掉或改写成好判的**。
- [ ] 6 条 `defect` 条目已标注，且各有对应事件当靶子。
- [ ] `notice` 块覆盖本 scenario 用到的全部源。

---

## 6. 成本

调用尺寸按仓库实际 prompt 形状估：translator system ≈ 580 tok、extraction system ≈ 916 tok、judge system ≈ 79 tok、`INDEX_ROW_TOKENS = 20`、`BATCH_N = 8`、`CONSOLIDATE_ADDS = 16`。

单 scenario 单 chained pass：

| 调用 | 次数 | in/次 | out/次 |
|---|---|---|---|
| extraction（flash） | ~11（~85 signal / BATCH_N=8） | 2.2k（含 56 行编号 index ≈ 1.1k） | 400 |
| consolidation（flash） | ~3 | 1.6k | 400 |
| translate（flash） | 24（8 cp × 3 probe） | 1.7k（≤32 条召回 ≈ 0.8k） | 250 |

全量 = chained ×2 + segment ×2 + oracle ×2：

| 项 | 调用数 | in | out |
|---|---|---|---|
| SUT（flash 档） | ~1,824 | ~3.44M | ~556k |
| judge（对齐 3,840 + 改写 3,456，改写侧已扣 40% 机械解决） | ~7,296 | ~2.55M | ~290k |
| **合计** | **~9,120** | **~5.99M** | **~846k** |

金额：**费率是假设，不是核过的账单**，引用前按当前价目表重算。按 flash 档 $1/$5 每 MTok、judge 档 $0.3/$1.2 每 MTok → SUT ≈ $6.2、judge ≈ $1.1，**全量一次 ≈ $7.3**。即便费率差 5 倍也不到 $40，钱不是约束。

墙钟：8 路并发、单调用中位 3s ≈ **57 分钟**。必须沿用现有 5/15/45/120s 重试梯（本机 Anthropic 代理一天抖 5 次以上，单次可达 3 分钟；9,000 次调用一定撞上）。

冒烟档：3 个 scenario × 1 次 chained，state 只判 cp-04 / cp-08 ≈ 200 SUT + 500 judge 调用 ≈ $0.6、~8 分钟，可以跟 T/L 一起挂在 commit 上。

一次性构建成本才是大头，而且是人时不是 token：672 条 constraint + ~1,350 个 event + 双人签字 + 6×20 分层抽检 + 40 对对抗集。按 **6–8 个工作日** 预算，不要按一个下午。lint 与 fold 是让它可行的关键——没有任何一份 gold 状态是手写的。

---

## 7. 反 overfit 与许可防线

**最大的风险说在前面：gold 是我们的意见，而样本量会让这个意见看起来像测量。** 每一个 `effect` 都是写日志时决定的——「这句话应该触发 c-17 的 contradict 而不是 new」。真实用户语句在这一点上本来就模糊，L 的 revoke 今天 0.50 就是证据。96 个 checkpoint × 45 条会吐出 0.834 这样带着紧凑区间的数，而底下的标签噪声可能有 10–20%。一个错 15% 却报三位有效数字的 bench，比它取代的 60 条 suite 更糟，因为它会被信。

对应防线，全部是发布前的硬条件：

1. 非 `new` 的 effect 双人签字；不一致者进 `R-amb` band 用宽容集判定，**不删除**；逐失效原因的作者分歧率随每次 run 公布。
2. `null-dump` 对照臂不过就作废本次 run（§4.5）。
3. `flat-dump` 对照臂是 go/no-go：分不开就发布「50 条不构成压力」这个结论本身。
4. 陷阱有效性活检：每次报出 null 系统（从不 retire、全量注入）在每个 probe 上的失败基率。它若接近真系统，陷阱集是摆设。

反 overfit：

5. 每条 constraint 的 `distinctive` 哈希后 grep `src/`，并入 `tests/test_no_bench_contamination.py`。反向也查：产品 prompt 里的固定短语不得出现在 case 里。2026-07-25 已经出过一次逐字泄漏（extraction prompt 的四个 exemplar 抄自 writer-zh），672 条的暴露面比 114 条大得多。
6. 数值强制变异，lint 拒绝未变异的 style-guide 数值条目。理由是**测量**不是许可：PEP 8 被 backbone 背熟，未变异的「4 空格缩进」下游本来就会遵守，这条 case 分不清「translator 带过去了」和「模型本来就这么干」。
7. 无数值可变的高记忆度规则取反或丢弃；取反是合法变异，而且让记忆变成负担。
8. IFEval 来源的短句 boilerplate（"Wrap your entire response in double quotation marks"）在入库前一律改成 user-voice 措辞——它太通用，会让查重守卫要么误报要么空过。

许可：

9. 逐条 `provenance`，`bench/NOTICE` 由并集生成，CC BY 系列的 `source` 字段常驻不可剥离。
10. lint 白名单挡住非可再分发许可的 `use: verbatim`。
11. 不新增任何 NC 依赖。PrefEval 足迹冻结在现状，distractor 全部自写。AgentIF、Multi-IF 数据、CFBench、CELLO、Microsoft、CMOS、AP、LaMP、Persona-Hub 一个字不进 repo。
12. AgentIF-OneDay 只取 rubric 与 task 文本，附件（WEF 报告、Radiohead 歌词 PDF 等）绝不 vendor——MIT 标签清不掉第三方版权。

harness 自身：

13. `gold.py` 与 `Store.apply_ops` 的 fuzz 等价测试不是可选项。两个状态机一旦漂移，suite 里每个数字都错，而任何 judge 都发现不了。这条写在这里，是因为 harness 侧已经引入过两个 bug（`latest("E")` 的 glob 吃到诊断快照、bench 文本泄漏进 prompt），而 R 的 harness 比现在大得多。

---

## 8. 实现分解

| 里程碑 | 产出物 | 验收标准 |
|---|---|---|
| **N0** 状态机 | `bench/replay/gold.py`、`bench/replay/lint.py`、`tests/test_gold_matches_store.py`。零 LLM、零 case | 10k 条 fuzz op 流上 `gold_state` 与 `Store.apply_ops` 状态等价；lint 能抓出 8 个人为植入的缺陷 case |
| **N1** 首个 scenario | `dev-zh` → `r-01`，满规格（56 条、112 事件、8 cp）；`bench/runner/run_replay.py` 三模式 | lint 全绿；r-01 在 oracle 模式、cp-01/cp-02 密度（≈3 规则）下的分数与 E-repaired 在 dev-zh 上的历史值相差 ≤ 0.10。差得多说明 harness 错了，不是产品错了 |
| **N2** 判据层 | 扩后的 `checkers.py`（全部请求级）、逐条 `judge_criterion`、`make_audit.py` 的 replay 行、40 对对抗对齐集 | 6 个 facet_family 各 20 条人工抽检，逐 family 一致率 ≥ 0.9（不达标则重写判据，不是降低门槛）；对抗对齐集拒绝率 ≥ 0.9 |
| **N3** 对照臂 | `null-dump` / `flat-dump` / `oracle-ceiling` 三个 stub provider | r-01 上 oracle-ceiling ≥ 0.9；null-dump 的 suppress 半边 ≤ 0.5；flat-dump 与真系统的差值如实记录（不设门槛，是观测） |
| **N4** 五个 scenario | r-02..r-06（含 release-engineering 与 en-US/en-GB 冲突两个） | 许可 lint 全绿；`bench/NOTICE` 生成；双人签字日志与逐原因分歧率落盘 |
| **N5** 补齐 | r-07..r-12（含 ja/fr scope.lang 一个） | 12 个 scenario 全部过 lint；每个 ≥ 6 facet family、filler ≤ 40%、`role: chain` ≥ 20 |
| **N6** 水位 | 两次全量跑，报 R / R-crud / R-amb / 三对照臂 + scenario 聚类 bootstrap CI + 实测 ICC | headline CI 半宽 ≤ 0.08。> 0.08 就如实报出并明确不设 gate |
| **N7** 定线 | `bench/runner/config.py` 权重改 T .25 / L .25 / R .50；阈值由 siriux 拍 | 权重与阈值连同定线依据写进 `bench/README.md`；E 退出 gate 的记录归档 |

N0–N3 是纯工程，可以先行；N4–N5 是人时大头；N6 之前 R 不产生任何可引用的分数。

---

## 9. 明确不做的事

- **不做 20 个 scenario**，做 12。12 → 20 只把 CI 半宽从 ±0.057 收到 ±0.044，代价是 450 条 constraint 的双人复核。
- **不扩 L**。密集 store 下的写入 targeting 由 R-segment 覆盖，再加 18 条 L case 是重复投资。
- **不把 recall 探针做成 bench 臂**。`recall()` 是 15 行确定性函数，第一行就是 `status == "active"` 过滤；480 条手写探针买不到梯度。它进 `tests/test_recall_at_density.py`，做生成式 store 上的 property test，不进 case 语料。
- **不做制品级判据**。不校验产出的 Python 代码行宽、commit 形状、slide 页数。SUT 的输出是一句被改写的请求，判据就只能作用在这句请求上。
- **不 gate latency / token 效率 / store 体积**。当遥测报，不入分。存储介质不是瓶颈这条口径不变。
- **不因 bench 而改产品 schema**。`superseded_by` / `retire_reason` 是 v1.1 的产品决定（memory 调研已指向 append-only + 双时序），bench 用 `cid` 空间自己 fold 出反向指针，不推着产品加字段。
- **不删歧义 case**。宁可单独报一个更难看的 band。
- **不引入第二个 NC 依赖**。CFBench 的数据形状最贴合我们的 schema，仍然弃；要用就发信向作者要明确授权。
- **不做多用户 / 跨 app 迁移 / embedding 检索评测**。都是 v2 之后的题。