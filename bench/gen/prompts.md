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
