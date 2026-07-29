# Case 扩展生成（每 category 补至 10 条）

用 `deepseek-v4-flash`（拍板决议；`.env` 通道，thinking 默认开启帮助多样性）按下述
prompt 逐 category 生成，temperature 默认；生成后
**逐条人工审核**，过 checklist 才进 cases.jsonl，source 标 "generated"。

## 生成 prompt（替换 {CATEGORY_SPEC} 为计划 Task 4 表格中该行的"用户行为面 + 变化维度"，附上该类 2 条 seed 作为格式样例）

You are creating benchmark cases for a "translator" that rewrites a user's
raw request by weaving in that user's stored delivery requirements
(rules about HOW tasks should be executed/delivered — length, format, tone,
method, workflow). It must never invent constraints, never change the core
task, and must leave unrelated requests untouched.

Category to generate: {CATEGORY_SPEC}

Rules for every case:
- The scenario must be an everyday situation for a developer / grad student /
  knowledge worker. If failing this case would not annoy a real user, discard it.
- Requirements must be delivery preferences (how the task is done), NEVER
  content preferences (what to recommend / personal facts like allergies).
- Vary across the dimensions listed in the category spec; do not produce
  near-duplicates of the seeds or of each other.
- Keywords in contains_all must be verbatim substrings of the input that any
  correct rewrite must keep (entities, URLs, ticket numbers, tech terms).
- Output one JSON object per line (JSONL), exactly matching the seed schema,
  ids as {prefix}-{003..010}.

Produce 8 cases.

## 人工审核 checklist（逐条过，任一不过则改或弃）

1. 日常性：这个 case 若 fail，真实用户会恼火吗？（不是 adversarial 智力题）
2. requirement 是 delivery 类，不是 content preference / 个人事实。
3. 期望行为无歧义：一个合格人类改写者会同意 expect_decision 与 must_apply。
4. contains_all 关键词确实是"任何正确改写都必须保留"的实体，无误伤。
5. judge 判据（如有）单义、可二值判定。
6. 与已有 case 不近重复（域、约束、句式至少一处明显不同）。

---

# Suite L 扩展生成（每 category 补至 6 条；生成 5/类 + seed 1/类）

同款流程：`deepseek-v4-flash` 生成 → 逐条人工审核 → 过审进
`bench/cases/extraction/cases.jsonl`（source=generated）。schema 见 seed；
category 语义与期望见计划 Task 7 表（§2 评分协议）。

## 生成 prompt（{CATEGORY_SPEC} 换为该类行为面；附该类 seed 作格式样例）

You are creating extraction benchmark cases for a memory pipeline that turns
user signals into durable delivery requirements (rules about HOW tasks are
executed/delivered). Cases feed a provider `extract(events, existing) -> ops`.

Category to generate: {CATEGORY_SPEC}

Rules for every case:
- Everyday scenarios for a developer / grad student / knowledge worker.
- Durable delivery rules only; content preferences and personal facts are
  NEGATIVE material (they belong in noise-reject cases with expect_ops []).
- "events" is the exact event list the provider will see; keep it minimal and
  realistic. edited_diff events need all three of raw / polished / final.
- expect_ops gists must be short English paraphrases of the durable rule; a
  case with expect_ops [] means ANY extraction is a failure.
- relation cases: "existing" holds the store texts; target is the INDEX into
  existing. reinforce = restating the same rule; contradict = durably
  overriding it (include the corrected rule text in the gist).
- Output raw JSONL, ids {prefix}-002..006, category "{category}",
  source "generated". No prose, no fences.

Produce 5 cases.

## L 审核 checklist

1. 日常性同 T checklist 1。
2. expect_ops 的 gist 与 events 语义一致，无脑补；[] 类确实不该提取。
3. noise-reject-task 的一次性限定词（这次/例外/临时）真实自然。
4. relation 的 target 指向正确，reinforce/contradict 语义清晰二选一。
5. 与已有 case 不近重复。

---

# Suite L 第二批：CRUD 补全（revoke / diff-supersede / dedup，各 6 条；2026-07-24 拍板）

op 词表扩为 `{new, reinforce, contradict, retire, merge}`；events 为 [] 的
case 走 `provider.consolidate(existing)`（对齐 pipeline proposal 的
extraction + consolidation 两 call）。生成与审核流程同上，三类 spec：

- **revoke**：规则的持久撤销。(a) natural 撤销句（不用了/forget that rule）
  → 一个 `retire`（target 必填，无 gist）；(b) edited_diff 里用户仅把
  polished 织入的库中约束删回 raw（一次性负信号，机械 strength 处理）
  → expect_ops **[]**。比例约 3:2。
- **diff-supersede**：edited_diff 里 final 把 polished 织入的约束**改了参数**
  （120→80 词、bullet→table、英文→中文）→ 一个 `contradict`（target=被改
  条目，gist=新规则）。注意 raw/polished/final 必须是**用户请求**而非产出物
  内容；polished 织入的约束必须真来自 existing（第一批生成曾在这两点翻车）。
- **dedup**：events 必须 []。existing 3–5 条中恰有 2–3 条同义（改写或 zh/en
  互译），其余明显不同 → 一个 `merge`（targets=重复下标集，gist=合并后规则）。
  多余合并（把不同规则并进去）即 fail。

## 第二批审核 checklist 增补

6. supersede 的 diff 三元组是请求文本；polished 织入约束 grounded 于 existing。
7. revoke (b) 与 supersede 的区分：删除→[]，改参→contradict——绝不混淆。
8. dedup 的 targets 集合精确（漏合、多合都 fail）；merge 对语义必须真等价。
