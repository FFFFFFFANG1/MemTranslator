# LongMemEval preference 子集探针（B4 闸门预研）

> 2026-07-22。数据：`longmemeval_oracle.json`（cleaned 版，HF `xiaowu0162/longmemeval-cleaned`），已下到 `pilot/data/raw/LongMemEval/data/`。

## 数字

全集 500 题；类目分布：temporal-reasoning 133 / multi-session 133 / knowledge-update 78 / single-session-user 70 / single-session-assistant 56 / **single-session-preference 30**。

## 形态（对我们的适配度：高）

preference 题的结构与我们的用例同构：

- **历史**：haystack_sessions 是多轮真实对话（样例：用户与助手讨论 Adobe Premiere Pro 高级设置，18 turns）——偏好在对话中自然显露，不是单句陈述；
- **question**：underspecified 请求（"Can you recommend some resources where I can learn more about video editing?"——没提 Premiere）；
- **answer**：直接是 preference-following 期望的描述（"…prefer resources specifically tailored to Adobe Premiere Pro… not general video editing resources"）——可直接当 judge rubric。

三个连带好处：
1. write path 的输入正是多轮对话（我们的 extraction 天然形态）；
2. **Graphiti 的公平灌入问题被同时解决**（B0 memo 发现 4：孤立偏好句产出稀疏图；这里的 haystack 就是对话流，是其官方推荐形态）；
3. LongMemEval 官方带 eval 脚本，judge prompt 可复用（出处注明）。

## 闸门初判：建议 GO（待你扫一眼样题确认）

- requirement-like ✓、judge 可复用 ✓、对话流灌入 ✓。
- 顾虑：n=30 偏小，单臂统计功效弱——定位为"memory 社区标准 benchmark 上的补充数字"（副战场，与 baseline plan §0 一致），不做主结论；配对检验 + bootstrap 可用。
- oracle 版只含相关 session（检索难度低）——如需更真实检索压力用 `_s` 版（每题 ~40 session 干扰），B4 时定；oracle 先行足以对比"记忆→使用"环节。
- 30 题清单人工过目（plan B4 的 20 题闸门）：跑 `uv run python -c "import json; [print(q['question_id'], '|', q['question'][:80]) for q in json.load(open('pilot/data/raw/LongMemEval/data/longmemeval_oracle.json')) if q['question_type']=='single-session-preference']"` 即可扫完。
