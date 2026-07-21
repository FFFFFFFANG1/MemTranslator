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
- ~~Typeless 文档从未提"从用户对输出的手工修改中学习"（编辑发生在目标应用里，采集不到）~~ **【2026-07-22 逆向部分证伪，见 §8.4】**：它其实在本地算"AI 润色文本 vs 实际结果"的 diff（`isLargeModify/addedCount/removedCount/changedCount`）并存 `edited_text`。但我们的 composer diff 采集更干净（同一输入框、不依赖跨 app AX 跟踪，且它的 extraction 实测未落地产出）——信息优势论断仍成立。

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

## 7. 未知项（部分经 §8 逆向解决）

- ~~各模式用哪家哪档模型、路由策略~~ **仍未知且逆向也拿不到**：客户端主进程无任何模型名/provider host/prompt 明文（§8.4），ASR+润色全在服务端，逆向客户端到此为止。
- ~~风格证据的具体表示~~ **仍未知**：`personal_auto_style_on` 确认自动风格是独立子系统（§8.3），但风格证据的表示在服务端，本地 db 只存 history+diff。
- ASR 与润色是否合并为单一多模态调用——仍未知（服务端）。
- Windows/Android 端集成细节（未抓 per-platform release notes；macOS 端逆向见 §8）。

---

## 8. 本地 app 逆向补充（一手证据，2026-07-22）

> 对象：`/Applications/Typeless.app` v2.0.1（siriux 付费版，macOS）。方法：只读静态检查——bundle 结构、Electron `app.asar` 解包、Drizzle 迁移 SQL、`~/Library/Application Support/Typeless/` 下的配置 JSON 与 SQLite schema。边界：不改任何文件、不碰 license、不外发数据、不把 Typeless 专有代码/prompt/用户历史内容搬入本 repo（下述均为架构结论与 schema 字段名）。**限制**：主进程 JS 经字符串数组混淆且关键逻辑在服务端，故润色 prompt 与 provider 路由拿不到（见 §8.4）。

### 8.1 技术栈（事实）
Electron（`Electron Framework.framework` + Squirrel 自动更新 + 4 个 helper 进程）+ Vite/React 前端（`dist/renderer/` 228 个 hash 命名 chunk）+ 主进程 `dist/main/index.js`(524K,混淆) + 音频 `dist/main/worker/opusWorker.js`。本地存储 Drizzle ORM/SQLite。依赖里打包了 **Vercel AI SDK**（`ai-sdk.dev`、`vercel/ai` 的 openai-responses-language-model）与 **@google/genai**（js-genai v1.19）。崩溃 Sentry、分析 Mixpanel。bundle id `now.typeless.desktop`，`public.app-category.developer-tools`。

### 8.2 本地存储 schema（Drizzle 11 个迁移，明文）
单表 `history`（后 `history_v2`）。字段揭示的采集面：
- 文本：`refined_text`（润色输出）、`edited_text` + `edited_text_status`(默认`NOT_EXTRACTED`) + `edited_text_attempts`、`hasRevertedAI`（撤销 AI）。
- 上下文：`ax_text`/`ax_html`（Accessibility 读取的目标字段）、`focused_app_name`/`bundle_id`/`window_title`/`web_title`/`web_domain`/`web_url`。
- 音频：`audio`(blob，v2 移除)、`audio_local_path`；`audio_cloud_path` 曾于迁移 0002 加入、0003 即删除（呼应 zero-retention）。
- 其他：`detected_language`/`languages`、`mode`(voice_transcript/command/translation)、`user_id`、`duration`。
- **索引**：建了大量 `(user_id, focused_app_bundle_id, web_domain, status, created_at)` 复合索引——**历史按"用户×应用×网站域名"分桶检索**。这是 per-app tone 的实现证据（原 §4.4/4.5 的推断坐实）。
- 迁移 0000 时间戳 = 2025-06-24：产品 2025-06 已开发，11 月才公开。
- 实测（我的库 24 条，仅看机制不看内容）：`edited_text_status` 全为 `NOT_EXTRACTED`——**"从编辑提炼"的 extraction pipeline 存在字段但未见落地产出**。

### 8.3 服务端下发的用户档案（`app-storage.json` key 结构，一手）
- **两个个性化开关**：`personal_auto_dictionary_on` + `personal_auto_style_on`——自动词典与自动风格是**两个独立子系统**，都可关。
- **历史云端同步可选**：`transcription_sync_enabled(_at)`（默认本地；开启才上云，与 history 的 `user_id` 对应）。zero-retention 指"处理即弃"，不阻止用户选择性同步历史。
- **按应用/网站控制启用**：`app_blacklist/whitelist`、`url_blacklist/whitelist` + `regex/domain/exact/prefix` 匹配 + `accessibilityConfig`。
- **润色行为开关**：`auto_punctuation`、`smart_formatting`、`output_language_map`、`target_languages`。
- **配额客户端缓存**：`VOICE_TO_TEXT_WEEKLY_WORD_CNT`/`MONTHLY_WORD_CNT`/`DAILY_REQ_MAX_CNT`（8000 词/周免费档在端上计量）。
- 订阅/推荐/团队一大套；`rsa_public_key`+`rsa:is-enabled`（客户端持服务端 RSA 公钥，请求签名或字段加密）。
- `app-settings.json`：`enabledOpusCompression`、`dynamicMicrophoneDegradationEnabled`（弱网降码率）、`pushToTalk`/`keyboardShortcut`、三模式 shortcut、`historyDurationSeconds`、`__DEV_API_HOST`。

### 8.4 主进程行为与网络形态（`dist/main/index.js`，混淆但字段名可读）
- **单一网关**：主进程唯一自有 host = `api.typeless.com`（+`__DEV_API_HOST` 覆盖）。**无任何模型名、provider host、润色 prompt 明文**——ASR 与润色 LLM 调用**全在服务端**，客户端只上传音频+上下文、收润色结果。（整个 asar 里 "whisper" 命中 415 次多来自打包的 AI SDK 依赖，非客户端直接调用。）→ 原 §4 的"AWS 网关中转，供应商在后端"从推断升级为证据；也解释抓包只见 api.typeless.com（TLS）。
- **本地编辑 diff**：主进程计算 `{isLargeModify, addedCount, removedCount, changedCount}`，配合 `refined_inserted_text` 与 `original_input_box:{text_before_cursor, cursor_state}`——读输入框光标前文本作上下文、插入润色文本、再跟踪 diff 存 `edited_text`。→ 修正 §4.5（它确实采集编辑，非"采集不到"）。
- **音频 Opus 压缩上传**：`enabledOpusCompression` + `opusWorker.js` + `Recordings/` 386 个 `.ogg` + 弱网降码率。→ §4.2 从推断升级为证据。
- `PHASE3_TIMEOUT` 等分阶段标记暗示多阶段流水（采集→上传/ASR→润色/插入），与 V2.0 两级生成呼应（弱证据）。

### 8.5 对 MemTranslator 的净增结论
1. **"客户端持有个性化状态、随请求上行、云端处理即弃"被一手证据坐实**（§8.3 的 auto 开关 + §8.4 单网关 + zero-retention）——我们 memory store 客户端持有的部署形态有直接产品先例，且带隐私卖点。
2. **per-app scope 有工业实现**：Typeless 用 `(app_bundle_id, web_domain)` 给历史分桶 + 黑白名单控制启用（§8.2/8.3）。我们的 scope 判定（query-time LLM 判定 condition）是同一问题的更细粒度、可审计版本；论文可对照"隐式分桶 vs 显式 scoped requirement"。
3. **编辑 diff 是双方都想要的信号，但我们采集面更干净**：Typeless 靠跨 app AX 跟踪算 diff、且 extraction 实测未产出（§8.2）；我们的 composer 编辑在同一输入框内，diff 无损可采。TODO"编辑 diff 回流"的价值被强化。
4. **prompt 与 provider 路由是服务端机密**：逆向客户端到此为止，这条线不必再投入。
- iOS App Store 的 privacy nutrition label、App Store 版本历史（未抓取成功）。
