# PrefEval 数据事实（pilot Task 1 核验产出）

> 2026-07-22 核验，clone 自 [amazon-science/PrefEval](https://github.com/amazon-science/PrefEval)（depth 1）。本文件是后续所有 pilot Task 的数据事实来源。

## V1–V5 闸门结论：全部通过，plan 无需结构性修改

| # | 假设 | 结果 |
|---|---|---|
| V1 | repo 位置 + ~3000 preference、20 topics | **部分修正**：repo ✓、20 topics ✓；explicit preference 实为 **1000 条**（诊断的 ~3000 应含 implicit_preference 与 mcq_options 在内的全量）。1000 ≫ 150+100，抽样无碍 |
| V2 | 可解析 (topic, preference, query) 三元组 | ✓ 字段为 `preference` / `question` / `explanation`（附带 explanation 说明预期行为，可用于 judge 校准参考）；topic = 文件名 |
| V3 | repo 自带 LLM judge | ✓ `generation_task/llm_based_evaluation_errortypes.py`、`generation_task/get_preference_following_accuracy_generation_task.py`（error-type 分类式判定）；Task 8 judge 实现时优先采用官方 prompt 并注明出处 |
| V4 | license 允许研究使用 | ✓ CC **BY-NC** 4.0——学术使用没问题，注意不可商用 |
| V5 | 每 topic 数量支撑 150 正 + 100 负分层抽样 | ✓ 每 topic 31–62 条（见下表），150 正例 = 每 topic 7–8 条，余量充足 |

## 数据结构

`benchmark_dataset/explicit_preference/<topic>.json` = `list[{preference, question, explanation}]`。

样例（travel_restaurant）：
```json
{"preference": "I strictly avoid restaurants that serve foods containing gluten due to a severe gluten intolerance.",
 "question": "I'll be visiting Rome soon. What are some must-try local restaurants you'd recommend for me?",
 "explanation": "…The assistant should research and recommend gluten-free restaurants or options…"}
```

其余目录：`implicit_preference/`（隐式偏好，pilot 不用）、`mcq_options/`、`rag_retrieval/`、`filtered_inter_turns.json`（多轮插入对话，主实验臂 A2/A3 的 memory_store 构造不依赖它）。

## 每 topic 条数（explicit）

education_learning_styles 31 · education_resources 54 · entertain_games 51 · entertain_music_book 56 · entertain_shows 62 · entertain_sports 52 · lifestyle_beauty 53 · lifestyle_dietary 57 · lifestyle_fit 52 · lifestyle_health 49 · pet_ownership 43 · professional_work_location_style 36 · shop_fashion 54 · shop_home 56 · shop_motors 45 · shop_technology 35 · travel_activities 58 · travel_hotel 54 · travel_restaurant 56 · travel_transportation 46 —— **合计 1000，20 topics**

## 对 pilot plan 的影响

无结构性修改。两个备注：
1. `load_prefeval()` 按"目录扫描 + 文件名为 topic + 三字段"实现（Task 2）。
2. 负例构造（跨 topic）可用 topic 前缀分组（travel_* / lifestyle_* …）避免相近大类误当"无关"——比 plan 里"≠X topic"更严格一档，实现时用大类前缀不同作为负例条件。
