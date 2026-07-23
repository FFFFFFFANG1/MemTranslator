# Judge 抽检记录（Task 9 Step 2 — 人工闸门，siriux 逐条标注）

- 样本源：`T-20260724-005534.json`（judge=`deepseek-v4-pro`），全部判定共 131 条，随机抽 30（seed 20260724；t-exc-004 疑似假阴性已强制纳入）。
- 标注口径：**一致** = 你作为人类判官会给出同一 verdict；**不一致** = 你会给相反 verdict。一致率 ≥90%（≥27/30）则 judge 可信；否则改 JUDGE_SYSTEM 或拆细判据后重抽。
- 结论：（待标注后填写：一致 N/30，判定日期）

| # | case | criterion | polished（截断） | judge | 人工 |
|---|---|---|---|---|---|
| 1 | t-lang-005 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Explain the difference between REST and GraphQL using bullet points. | yes |  |
| 2 | t-single-002 | The core task of the original request is unchanged in the rewritten request. | 写一个Python函数来去重列表同时保持顺序，只给代码，不要解释。 | yes |  |
| 3 | t-exc-006 | The rewritten request (or unchanged request) does NOT demand a code snippet. | Explain the concept of dependency injection. | yes |  |
| 4 | t-lang-003 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | 请用正式语气写一份对客户关于延迟的投诉的回复。 | yes |  |
| 5 | t-long-002 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | 帮我把这封邮件发给物业前润色一下，保持专业和正式的语气，里面的链接别动：你好，上周提交的维修申请（工单号 #4821，详情见 https://prop.exam | yes |  |
| 6 | t-exc-005 | The rewritten request (or unchanged request) does NOT enforce a formal tone. | Send an informal Slack message to your teammate asking if the CI passed. | yes |  |
| 7 | t-multi-004 | The rewritten request explicitly carries this constraint: Summaries must be exactly 3 sentences. | Summarize the abstract of the paper on transformer models for NLP in exactly 3 s | yes |  |
| 8 | t-lang-002 | The rewritten request explicitly carries this constraint: 代码类回答只给代码，不要解释。 | implement quicksort in rust, in-place. Only provide the code without explanation | yes |  |
| 9 | t-exc-010 | The rewritten request (or unchanged request) does NOT require citations. | What is the chemical formula of water? | yes |  |
| 10 | t-multi-006 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Explain how to debug a memory leak in Python. Please use a friendly, encouraging | yes |  |
| 11 | t-lang-007 | The rewritten request explicitly carries this constraint: Limit the response to three sentences. | 请用三句话解释一下机器学习中的过拟合问题。 | yes |  |
| 12 | t-single-005 | The core task of the original request is unchanged in the rewritten request. | 请帮我撰写一份项目总结报告，内容涵盖我们团队去年完成的工作。报告需采用正式的文档语气，并使用敬语表述。 | yes |  |
| 13 | t-single-002 | The rewritten request explicitly carries this constraint: 代码类回答只给代码，不要解释。 | 写一个Python函数来去重列表同时保持顺序，只给代码，不要解释。 | yes |  |
| 14 | t-lang-001 | The core task of the original request is unchanged in the rewritten request. | 帮我用英文给教授写封邮件，约下周 office hour 聊 thesis 选题。邮件请控制在120词以内。 | yes |  |
| 15 | t-multi-008 | The rewritten request explicitly carries this constraint: Use a polite tone. | Write a code review comment for a PR that introduces a new authentication method | yes |  |
| 16 | t-lang-005 | The rewritten request explicitly carries this constraint: 所有解释必须用 bullet points 列出。 | Explain the difference between REST and GraphQL using bullet points. | yes |  |
| 17 | t-lang-008 | The rewritten request explicitly carries this constraint: 代码必须包含注释。 | Write a function to reverse a linked list in C++. Please include comments in the | yes |  |
| 18 | t-long-008 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Please rewrite the following dev environment instructions as a formal document w | yes |  |
| 19 | t-single-007 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Draft a polite and professional email to the IT support team requesting a new la | yes |  |
| 20 | t-single-007 | The rewritten request explicitly carries this constraint: Emails should be written in a polite and professional tone. | Draft a polite and professional email to the IT support team requesting a new la | yes |  |
| 21 | t-long-002 | The core task of the original request is unchanged in the rewritten request. | 帮我把这封邮件发给物业前润色一下，保持专业和正式的语气，里面的链接别动：你好，上周提交的维修申请（工单号 #4821，详情见 https://prop.exam | yes |  |
| 22 | t-exc-004 | The rewritten request (or unchanged request) does NOT impose any word limit. | Give me a detailed explanation of how Kubernetes works. | no |  |
| 23 | t-multi-010 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Write documentation for the function parse_config that takes a file path and ret | yes |  |
| 24 | t-single-008 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | 写一个Python函数，实现二分查找。请在代码中包含详细的中文注释，解释每一步的逻辑。 | yes |  |
| 25 | t-multi-008 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Write a code review comment for a PR that introduces a new authentication method | yes |  |
| 26 | t-long-001 | Every workday item from the original notes (Mon–Fri) survives in the rewritten request; nothing is dropped, summarized away, or altered in meaning. | 把下面的记录整理成周报，用 bullet points 的格式（不要写大段落）：周一和 Leo 对了 pilot 的评测口径，把 judge prompt 改成 | yes |  |
| 27 | t-lang-008 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | Write a function to reverse a linked list in C++. Please include comments in the | yes |  |
| 28 | t-single-010 | The core task of the original request is unchanged in the rewritten request. | 帮我整理一下最近关于强化学习在机器人控制中的应用的研究进展。请用表格形式呈现研究结果，包括各项研究的方法、结果和局限性。 | yes |  |
| 29 | t-single-004 | The rewritten request adds no constraint that is not grounded in the listed stored requirements. | write a bash script to rename all .txt files to .md in current directory. Please | yes |  |
| 30 | t-multi-006 | The rewritten request explicitly carries this constraint: Provide step-by-step instructions. | Explain how to debug a memory leak in Python. Please use a friendly, encouraging | yes |  |
