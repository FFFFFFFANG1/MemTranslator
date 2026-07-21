# Typeless 逆向分析：feature 盘点与最可能的实现

> 2026-07-21。目的：Typeless 是我们 runtime 形态（polished 输出落回输入框、用户可改）的产品参照，摸清它的设计思路与实现，为 MemTranslator 的系统设计与论文 related-product 讨论提供参照。
> 方法与置信度：官网可抓页面全部一手抓取（主页 / manifesto / pricing / FAQ / help / privacy / about / use-cases）；trust center 的 subprocessors 页对爬虫 403、经真浏览器渲染取得；release notes 为 JS 渲染、同法取得（macOS 线 V0.4.3→V2.0.0 完整）。**§1–2 为文档写明的事实；§4–5 是我基于事实的推断**，每条标注依据强弱。未具名供应商、无任何官方架构文章，实现细节均为推断。

## 1. 产品事实（一手）

**定位与形态**：系统级语音输入——按 Fn 说话，AI 实时把口语变成润色后的书面文本，插入任意应用光标处（"Speak naturally… polished messages, emails, and documents that read like you carefully typed them - in real time"）。macOS / Windows / iOS / Android。三大模式（V1.0 定型）：**Dictate**（口述→润色文本）、**Translate**（说 A 语言→出 B 语言的 ready-to-send 文本）、**Ask anything**（对选中/只读文本发语音指令：改写、摘要、翻译、联网问答、快捷操作）。

**核心 feature**（官网原文归纳）：
- 去 filler（um/uh）、去重复；**mid-sentence 自我纠正只保留最终意图**；自动格式化列表/步骤；选词优化
- **per-app tone**（工作邮件正式、聊天随意——自动判断，用户不可逐 app 配置，Product Hunt 有用户抱怨这点）
- 个人 Dictionary（人名/术语/表达；V1.4 支持文件批量导入）
- 100+ 语言自动检测；V0.8.1 起区分**区域方言**（欧洲法语 vs 加拿大法语）
- whisper mode（低声说话可识别）
- V0.9："**Typeless learns your voice… adapting to your specific tone as you use it. No setup required**"（零配置自动风格学习）；Speak to edit / Speak for answer 可**自主联网搜索**并渲染 Markdown
- V2.0（2026-07-08）"Dictate the way you think"：**side note 留作上下文不进正文；描述性指称解析**（"说不上名字描述一下，它填精确名且不编造"）；**乱序输入按重要性重组；事后改主意只留最终决定**

**隐私与处理位置**（privacy policy 原文要点）：音频与"有限上下文信息（**当前应用、屏幕相关文本**）"上传云端，"processed in real time on our cloud servers and immediately discarded once the result is returned"；零保留、不训练；**dictation 历史只存本地**。第三方 LLM 供应商（政策未具名）。

**供应商**（trust center subprocessors，403 后浏览器实抓）：AI/ML = **OpenAI、Groq、Gemini**；基建 = AWS（+ACM）；WorkOS（SSO）；Stripe；Mixpanel；Apple；GitHub。**无 Anthropic**。

**商业**：免费 8,000 词/周 + "Standard accuracy" + 高峰标准通道；Pro $12/月（年付）"Enhanced accuracy" + 无限量 + 高峰优先。V2.0 加 Enterprise（管控/部署）。HIPAA / GDPR / ISO 27001。

**团队与节奏**：Stanford 校友团队，创始人 Huang Song，Palo Alto（实体 Simply CA LLC），受"Stanford 系加速器"支持（按其定义应为 StartX——我的推断，页面未点名）。2025-10 前后 beta，11-18 Product Hunt 桌面上线，12-24 iOS，2026-01-20 Android，节奏极快（~2 周一个 minor 版本）。

## 2. 时间线揭示的演进逻辑

| 阶段 | 版本 | 能力跃迁 |
|---|---|---|
| 打磨管线 | V0.4.x (2025-10/11) | Fn 即按即录（麦克风预热）、转写提速——**基础延迟战** |
| 扩语言 | V0.7–0.8.1 (12月) | Translation mode、方言 locale——ASR 层可配化 |
| 个性化+agent 化 | V0.9 (12-24) | 自动风格学习、intent 级重组、自主 web search |
| 模式定型 | V1.0 (2026-02) | Dictate / Translate / Ask anything 三分 |
| 语义深化 | V2.0 (07-08) | side-note、指称解析、乱序重组、跨段撤销 |

演进方向清晰：**转写器 → 意图编译器**。V2.0 的四个能力全部不是 ASR 能力，是"把口语流当草稿、LLM 输出最终稿"的语义层能力——与我们 idea 的"把用户输入当 underspecified 草稿、translator 输出 polished input"是同一抽象在不同输入模态上的实例。

## 3. 设计思路（从 feature 反推的产品原则)

1. **输出可编辑是信任的来源**：AI 直接替你发出去风险不可接受；落回输入框让人过目，错误代价→一次手动修改。我们 typeless 式 runtime 决策的原始出处。
2. **零配置个性化**（"No setup required"）：不让用户写 style 规则，从使用中隐式学——与我们"从 feedback 提取显式 requirement"是同一目标的两条路线（隐式画像 vs 显式可审计条目）。
3. **上下文即场景**：per-app tone 不靠用户配置，靠"当前应用+屏幕文本"实时判断——scope 判定做在 query-time，与我们 translator 端 scope 判定同构。
4. **隐私作为架构约束**：zero-retention + 历史本地存 ⇒ 服务端无用户状态。个性化所需的一切（词典、风格证据）必须由客户端每次随请求上行。这不是营销话术而是系统设计的第一约束（推断，见 §4.5）。
5. **延迟是产品生死线**：manifesto 全篇"real time"；V0.4.4 专门发版做"按下 Fn 瞬时开麦"；subprocessor 里的 Groq 几乎只为低延迟存在。

## 4. 最可能的系统架构（推断）

```
┌─ 客户端（mac/win/iOS/Android）─────────────────────────┐
│ 全局热键(Fn) → 常驻音频引擎(预热) → 流式上行(WebSocket)   │
│ 焦点应用/屏幕文本采集(Accessibility) ──┐                │
│ 本地状态：Dictionary + 风格证据 + 历史 ─┴→ 随请求上行     │
│ 文本插入：AX API / 粘贴模拟 ← 结果流                     │
└──────────────────────────────────────────────────────┘
                    ↓↑ AWS(API 网关/编排,无用户内容存储)
        ┌───────────┴───────────┐
        │ ASR(流式): Whisper 系   │  ← OpenAI / Groq(whisper-turbo)
        │ 润色 LLM(分句/终稿两级): │  ← OpenAI / Groq / Gemini 路由
        │ 工具: web search        │
        └───────────────────────┘
```

**4.1 客户端集成层**【强推断：FAQ 明说 Accessibility 权限+Fn 触发】
- macOS：菜单栏常驻 app。全局热键=CGEventTap/NSEvent 全局监听（Fn 需 Input Monitoring 权限）；文本插入=AXUIElement `setValue`/`insertText`，不可及元素回退为剪贴板+⌘V 模拟（troubleshooting 有"权限问题""系统设置冲突"条目佐证此层的脆弱性）；焦点上下文=NSWorkspace frontmost app bundle id + AX 树读焦点元素文本与选中文本（privacy 的"relevant on-screen text"）。
- iOS/Android：自定义键盘（Play 包名 `com.typeless.mobile`），键盘扩展联网（iOS 需 Full Access）+ 主 app 管理。
- V0.6"老硬件也流畅"+全平台快速跟进 ⇒ 客户端薄、重活全在云端【强推断】。

**4.2 音频与传输**【中推断】：Fn 按下即录（V0.4.4 的"instant microphone access"说明 AVAudioEngine 常驻预热）；流式分帧上行（WebSocket/gRPC over AWS）；VAD 在端上做静音截断以省流量（惯例，无直接证据）。

**4.3 ASR 层**【强推断：subprocessors + 100+语言 + 方言 + whisper mode】
- Whisper 系是唯一同时满足"100+ 语言自动检测 + 方言变体 + 低声鲁棒"的公开选项；供应商证据下最可能组合：**Groq 托管 whisper-large-v3-turbo**（市面最低延迟档）为实时主力，OpenAI（whisper/gpt-4o-transcribe）为质量档或回退。locale/方言（V0.8.1）作为解码 hint 传入。
- Dictionary 热词以 initial_prompt/词表 biasing 注入 ASR，同时进润色层 prompt（双保险，惯例做法)【中推断】。

**4.4 润色 LLM 层（核心）**【强推断框架 + 中推断细节】
- 输入组装：ASR 转写（partial+final）、已插入前文、app 上下文（bundle id/窗口标题/焦点字段已有文本）、Dictionary 相关词、风格证据、模式指令（dictate/translate/ask）。
- 两级生成【中推断，由 V2.0 能力倒推】：1.x 时代按句流式 commit（ASR final 边界→润色→立即插入，"real time"体感）；V2.0 的乱序重组/跨段撤销/side-note **只能在整段视野下做**，所以 2.0 应为"说话中轻量流式（或灰显 raw）+ 结束时终稿 pass 全局重写替换"。指称解析（"描述→精确名"）=Dictionary+屏幕上下文的受约束检索，"不编造"靠 prompt 强约束+词典白名单。
- 模型路由=账面上的 "Standard vs Enhanced accuracy"【强推断：定价页原文 + 三家供应商并存的唯一合理解释】：免费档走 Groq 开源模型/Gemini Flash 档，Pro 走 OpenAI/Gemini 高档 + 高峰优先队列。
- Ask anything=同一管线加 tool-use（web search + Markdown 渲染，V0.9 起），选中文本经 AX 读取入 context。

**4.5 个性化状态（与我们最相关）**【强推断链】
zero-retention（即弃）+ 历史仅本地 ⇒ **服务端不能持有用户画像** ⇒ "learns your voice, no setup" 的唯一实现路径：客户端从本地历史提炼风格证据（或直接选取最近/相似的 K 条确认输出作 few-shot），**每次请求随行上传**。即：个性化记忆的 owner 是客户端，云端无状态。
- 这与我们 MemTranslator 的部署形态互证：requirement memory 完全可以客户端持有、translate 时上行——zero-retention 类产品约束下这甚至是唯一形态。
- Typeless 文档从未提"从用户对输出的手工修改中学习"（他们的编辑发生在目标应用里，采集不到——插入即失控）。**我们的 demo 编辑发生在自己的 composer 里，diff 可采集**——这是 MemTranslator 相对 Typeless 形态的结构性信息优势（TODO"编辑 diff 回流"的价值论证）。

**4.6 企业与合规**【事实+弱推断】：WorkOS=SSO/SCIM；HIPAA ⇒ 与模型供应商有 BAA（OpenAI/Google 企业协议均可签）；AWS 单云。计量按输出词数（8,000 词/周），Stripe 订阅。

## 5. 关键设计张力与它的解法

| 张力 | Typeless 的解 | 对我们的启示 |
|---|---|---|
| 实时体感 vs 全局语义重写 | 两级：流式草稿 + 终稿 pass（V2.0） | translator 也可两级：即时 patch + 可选深度重写 |
| zero-retention vs 个性化 | 状态客户端持有、随请求上行 | memory store 客户端持有是可行且有隐私卖点的部署形态 |
| 自动 per-app 适配 vs 用户可控 | 全自动（用户不可配，已有抱怨） | 我们的显式 requirement + 可编辑输出正好补它的可控性短板 |
| 错误代价 | 输出落回输入框，人工兜底 | 同款（我们 runtime 决策的出处） |
| 延迟 vs 质量 | 模型路由分档卖钱（Standard/Enhanced） | pilot 的强弱下游对照有产品级先例 |

## 6. 对 MemTranslator 的直接启示

1. **形态验证**：一个 Stanford 团队 8 个月做到 V2.0+Enterprise，证明"用户输入的意图编译层"是被市场接受的产品位置；我们是同一位置的文本模态+显式记忆版。
2. **差异点更清晰**：Typeless 的个性化是隐式风格画像（不可审计、不可 scope、无 CRUD）；我们是显式 requirement 条目（provenance+scope+状态机）。论文 related products 可引用其 feature 页与 release notes 佐证需求真实性，再指出隐式路线的不可控作为动机。
3. **编辑 diff 回流**是我们形态独有的信号源（§4.5），应提升优先级（现 TODO #1）。
4. **两级生成**（即时 patch + 终稿重写）值得进 phase 2 设计讨论。

## 7. 未知项

- 各模式具体用哪家哪档模型、路由策略（供应商三选的内部分工是推断）。
- 风格证据的具体表示（few-shot 样本 vs 归纳出的 style profile 文本）。
- ASR 与润色是否已合并为单一多模态调用（gpt-4o-audio/gemini native audio 路线；按 2025-11 的延迟战与 Groq 存在，推断仍是 ASR→LLM 两段，置信中）。
- Windows/Android 端集成细节（未抓 per-platform release notes 全文）。
- iOS App Store 的 privacy nutrition label、App Store 版本历史（未抓取成功）。
