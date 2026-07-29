# oracle 审计：15 条争议判定，请裁定（2026-07-29）

## 怎么读

- **请求** = 用户这一轮打进去的字。里面的临时要求（「先理时间线」「标个问号」）**不是**已存规则。
- **记忆里的已存规则** = 更早轮次建立、存进 store 的持久规则。gold 认为这次改写必须把它们写进请求。
- 每张卡问的只是**标 ← 的那一条**，同 probe 的其他规则一并列出作对照。

> **这条已存规则，改写器是否必须把它写进这个请求？**

「必须写进」= gold 对，裁判过严 → 放宽裁判判据。
「不必」= gold 错 → 收紧生成判据，这类从答案集剔除。

裁定会 fan-out 到全部 209 个 probe。

---

## A. 人称与语气

### 1. `e-01 seq35`

**请求**：帮我写个postmortem，昨天线上那个Redis缓存雪崩的事，先把时间线理清楚，然后根因分析和改进措施，有些数据我记不太清的地方你帮我标个问号

**记忆里的已存规则**：

- 标注不确定的内容　`⚠️ 争议`
- 写简洁点，别废话　`⚠️ 争议`
- 别用第一人称视角　`⚠️ 争议` ←── **本卡争议**

**裁定**： [ ] 必须写进　　[ ] 不必

### 2. `e-10 seq28`

**请求**：帮我整理一下过去24小时线上P1故障的时间线，按发生、发现、响应、恢复四个阶段列出，并标出每个节点的延迟分钟数。

**记忆里的已存规则**：

- 禁止用第一人称　`⚠️ 争议` ←── **本卡争议**

**裁定**： [ ] 必须写进　　[1 ] 不必

### 3. `e-03 seq35`

**请求**：跑一下上周的DAU趋势，按渠道拆开，把环比和同比都加上，单位用万。

**记忆里的已存规则**：

- 直接说重点，别整客套话　`⚠️ 争议` ←── **本卡争议**
- 避免使用否定缩写　`⚠️ 争议`

**裁定**： [ 1] 必须写进　　[ ] 不必

### 4. `e-01 seq35`

**请求**：帮我写个postmortem，昨天线上那个Redis缓存雪崩的事，先把时间线理清楚，然后根因分析和改进措施，有些数据我记不太清的地方你帮我标个问号

**记忆里的已存规则**：

- 标注不确定的内容　`⚠️ 争议`
- 写简洁点，别废话　`⚠️ 争议` ←── **本卡争议**
- 别用第一人称视角　`⚠️ 争议`

**裁定**： [ 1] 必须写进　　[ ] 不必

## B. 句法结构



### 5. `e-02 seq25`

**请求**：hey can you pull a weekly report showing how many new signups we got this week vs last week broken down by plan type include a quick summary of what's driving the change

**记忆里的已存规则**：

- don't use sentence structure where the verb is buried at the end　`⚠️ 争议` ←── **本卡争议**

**裁定**： [1 ] 必须写进　　[ ] 不必

### 6. `e-02 seq44`

**请求**：draft an email to the engineering team about the api latency spike we saw this morning. we need them to investigate and fix it by end of day.

**记忆里的已存规则**：

- don't use sentence structure where the verb is buried at the end　`⚠️ 争议` ←── **本卡争议**
- keep it to 11 sentences max　`❌ 产品漏了`

**裁定**： [ 1] 必须写进　　[ ] 不必

### 7. `e-02 seq48`

**请求**：hey can you draft an email to the engineering team about the new onboarding flow rollout we need to finalize the timeline for next sprint also include a note about the user testing feedback from last week and a reminder to review the updated specs before friday thanks

**记忆里的已存规则**：

- don't use sentence structure where the verb is buried at the end　`⚠️ 争议` ←── **本卡争议**
- keep it to 11 sentences max　`❌ 产品漏了`

**裁定**： [ 1] 必须写进　　[ ] 不必

### 8. `e-03 seq44`

**请求**：刚跑完A/B实验，转化率掉0.3pp，置信区间没跨零，但样本量不够，来个复盘看看是不是埋点漏了。

**记忆里的已存规则**：

- 别用复杂句子结构　`⚠️ 争议` ←── **本卡争议**
- 避免负向缩约，比如“没”“不”　`⚠️ 争议`

**裁定**： [ ] 必须写进　　[ 1] 不必

## C. 长度限制



### 9. `e-02 seq30`

**请求**：please generate a weekly product health report for the last 7 days include sections on user engagement churn rates feature adoption and support ticket trends make sure to break it down into many specific subheadings like daily active users by segment retention by cohort top features by usage and ticket volume by priority also add a comparison to the previous week and a summary of any anomalies or notable changes

**记忆里的已存规则**：

- keep articles to 13 sentences max　`⚠️ 争议` ←── **本卡争议**

**裁定**： [1 ] 必须写进　　[ ] 不必

### 10. `e-05 seq24`

**请求**：Can you pull a quick report on last month's docs open issues — how many were closed, how many still open, and the average time to first response?

**记忆里的已存规则**：

- keep responses under 83 words　`⚠️ 争议` ←── **本卡争议**

**裁定**： [ 1] 必须写进　　[ ] 不必

## D. 输出格式



### 11. `e-08 seq30`

**请求**：帮我写一封邮件，发给市场部，提醒他们下周三前提交下季度的活动排期，格式要表格，按时间、活动名称、负责人、备注列清楚。

**记忆里的已存规则**：

- 以后都别用markdown格式　`⚠️ 争议` ←── **本卡争议**

**裁定**： [ ] 必须写进　　[ 1] 不必（邮件里为什么会有markdown？？）

### 12. `e-09 seq25`

**请求**：Please draft an email to the client summarizing the key findings from our market analysis, with a polite tone and a clear call to action for a follow-up meeting.

**记忆里的已存规则**：

- keep every response under 83 words　`✅ 带上了`
- keep it to 13 sentences max　`✅ 带上了`
- no headings　`⚠️ 争议` ←── **本卡争议**

**裁定**： [1 ] 必须写进　　[ ] 不必

### 13. `e-12 seq15`

**请求**：帮我写一封邮件给产品经理，催他尽快把周五的稿件数据发过来，语气要专业但别太客气，我这边等着排版。

**记忆里的已存规则**：

- 内容控制在29字以内　`✅ 带上了`
- 一律用编号分步，别用圆点列表　`⚠️ 争议` ←── **本卡争议**

**裁定**： [1 ] 必须写进　　[ ] 不必

## E. 其他



### 14. `e-07 seq44`

**请求**：write a postmortem for the incident yesterday where the batch settlement job OOM'd. keep it tight, just the facts.

**记忆里的已存规则**：

- keep it under 3199 words　`❌ 产品漏了`
- never use future tense　`⚠️ 争议` ←── **本卡争议**

**裁定**： [ 1] 必须写进　　[ ] 不必

### 15. `e-08 seq5`

**请求**：帮我写一份上周活动页崩溃的事故复盘，按时间线、影响范围、根因、修复动作、后续改进这几个模块来，每个模块分点写，格式要清晰，别用大段文字。

**记忆里的已存规则**：

- 不要重复或罗列相同特征　`⚠️ 争议` ←── **本卡争议**

**裁定**： [ 1] 必须写进　　[ ] 不必