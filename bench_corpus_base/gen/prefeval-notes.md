# PrefEval 筛选记录（Task 6）

- 数据源：`amazon-science/PrefEval` @ main（浅克隆 2026-07-24），`benchmark_dataset/explicit_preference/`，20 域共 1000 条 `{preference, question, explanation}`。
- **License：CC BY-NC 4.0（非商业）**。本 bench 为开源研究项目的评测数据，零散改写借用并注明出处，符合 NC 范围；**若项目未来商业化，需替换 source=prefeval 的条目与本文摘句**。
- 筛法：全量 keyword 初筛（format / bullet / concise / step-by-step / tone / length / structure / summary 等）得 15 条候选；education_learning_styles、education_resources、professional_work_location_style 三个最可能域另行逐条读。implicit_preference 未采（对话式结构，与 translator 场景不对口，性价比低）。

## (a) delivery 类合格条目：1 条（宁缺毋滥，预判应验）

| 原条目 | 处置 |
|---|---|
| `education_learning_styles[16]`: "I have a strong preference for logical and analytical learning approaches that involve breaking down complex concepts into structured, step-by-step processes." | 改写为 T case `t-single-006`（source=prefeval，替换原 generated 同位条目，保持 60 规模）：requirement "Explanations of complex concepts should be broken down into structured, step-by-step processes."，input 为研究生日常概念提问。 |

弃选典型（均为 content preference——约束"推荐/避开什么"，不是"任务怎么交付"）：
learning_styles[8]/[21]/[24]（学习环境与形式选择）、learning_styles[25] 与 education_resources[41]（偏好音频资源——资源形态选择）、education_resources[11]/[47]、entertain/shop/travel/lifestyle 全部命中条目。

## (b) content 负例池（供 Suite L noise-reject-content 取材，原文摘录）

1. `lifestyle_dietary[0]`: "I follow a strict gluten-free and dairy-free diet due to severe intolerances."
2. `entertain_music_book[27]`: "I exclusively listen to vinyl records and avoid digital music formats like streaming or MP3s."
3. `entertain_sports[26]`: "I have a phobia of heights, so I avoid all tall structures or high-altitude activities."
4. `shop_fashion[47]`: "I never wear sleeveless tops; I prefer tops with sleeves of any length."
5. `shop_home[10]`: "I avoid using any type of stone or marble in my home decor."
6. `professional_work_location_style[0]`: "I strongly dislike living in crowded, densely populated cities."
