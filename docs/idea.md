# Position: Memory-Grounded User Translator for Personal Agents

> 原始 idea 文稿，2026-07-21 由 siriux 提供，原文落盘未改动。

## 核心问题

用户向 agent 提交的原始输入往往并不能完整表达真实任务意图。用户可能省略此前已经多次强调的要求，也可能默认 agent 已经理解其长期偏好，例如：

* 期望的分析方式；
* 输出格式和详细程度；
* 对 agent 行为的限制；
* 特定任务类型下反复出现的要求。

现有长期记忆系统通常将相关 memory 作为额外上下文检索并注入下游 agent。然而，这种做法将理解用户意图的责任留给了执行 agent：agent 需要同时处理原始请求、历史记忆和任务执行，而且容易出现记忆误用、约束遗漏和上下文膨胀。

我们提出将用户记忆视为一个位于用户与 agent 之间的轻量级翻译层，而不是下游 agent 的额外检索上下文。

## 基本定位

系统接收用户的原始输入，并结合长期维护的用户需求记忆，将其转换为一个更明确、更完整的 polished user input：

Original User Input --[User Translator + User Memory]--> Polished User Input --> Downstream Agent

User Translator 不负责执行任务，也不要求修改下游 agent。其作用是恢复和补全用户在当前输入中未明确表达、但能够从历史交互中可靠推断出的要求。

下游 agent 只接收修改后的用户输入，不需要直接读取或理解用户 memory。

## 记忆的监督信号

系统主要从两类自然交互信号中构建和更新用户记忆。

### 1. User Next-Turn Feedback

用户看到 agent 回复后，在下一轮中进行纠正、补充或重述，例如：

* "我不是要总结，我要你分析它的问题。"
* "不用解释背景，直接给代码。"
* "以后这种论文都要和相关工作做比较。"
* "不要改我的原始结构。"

这类反馈能够揭示上一轮 agent 对用户意图的理解偏差，并提供比单独分析用户初始请求更明确的监督信号。

系统可以从以下交互关系中提取候选记忆：

(User Request, Agent Response, User Feedback) -> Requirement Correction

### 2. Frequently Mentioned Requirements

如果用户在多个相关任务中反复提出相同或相近要求，这种重复本身可以作为需求具有持续性的证据。

例如，用户在多次科研讨论中持续要求：

* 进行批判性分析；
* 不仅总结论文，还要判断 novelty；
* 对其研究想法进行反驳和风险分析。

系统可以将这些频繁出现的要求总结为适用于特定任务范围的长期记忆。

## 当前明确的 Memory 问题

本项目目前只明确关注两类 memory management 问题。

### Memory Scope

用户要求不一定适用于所有任务。

例如：

* "邮件写得简短"不意味着"论文分析也要简短"；
* "科研讨论时要批判性分析"不一定适用于普通事实问答；
* 某项要求可能只适用于一个 session、一个项目或一个任务类型。

因此，memory 不能只保存需求内容，还需要描述其适用范围。具体的 scope 表示、推断和匹配方法仍待研究。

### Memory CRUD

用户需求会出现：

* 新增；
* 重复；
* 强化；
* 修改；
* 冲突；
* 失效；
* 删除。

系统需要管理 memory 的创建、读取、更新和删除，避免长期积累大量重复、矛盾或过时的要求。

当前不预设具体采用规则系统、结构化数据库、LLM 判断还是其他机制，这属于后续需要解决的核心设计问题。

## Query-Time Translation

User Translator 的输入是完整的用户原始输入，输出是完整的 polished user input。

它不是简单输出若干条检索到的 memory，也不是把 top-k memory 直接附加到 agent prompt 中。系统内部是否采用检索、top-k 或其他 memory access 方法属于实现细节，不构成最终接口。

例如：

```text
Original input:
帮我看看这个想法是否可行。我准备做一个使用用户历史的agent memory系统……
```

经过翻译后可能变为：

```text
Polished input:
请从研究创新性、与现有工作的差异、技术可实现性和实验可验证性四个方面，批判性评估下面的研究想法。不要仅顺着该想法展开；需要明确指出可能缺乏 novelty、无法评测或不值得继续的部分。

[原始研究想法保持不变]
```

这种设计将用户个性化需求编译进当前任务，而不是要求执行 agent 在运行时自行解释用户历史。

## Patch-Based Translation

对于较长的用户输入，让 Translator 重新生成完整文本可能存在几个问题：

* 容易遗漏原始内容；
* 可能无意中改写用户提供的数据、代码或材料；
* 长输入带来更高的生成成本；
* 难以区分用户原始内容和系统补充要求；
* 无法精确审计 Translator 修改了什么。

一种可能的实现方式是，将用户输入表示成可编辑的代码或文档对象，并要求 Translator 生成 patch，而不是重新生成完整输入。

例如：

```text
<USER_REQUEST>
帮我分析下面这篇论文。
</USER_REQUEST>

<USER_CONTENT>
[长篇论文内容或用户材料]
</USER_CONTENT>
```

Translator 只生成类似以下修改：

```diff
 <USER_REQUEST>
-帮我分析下面这篇论文。
+请总结论文的核心方法，并重点分析其与现有工作的区别、
+主要技术局限和潜在研究空缺。对于作者的贡献声明需要进行
+批判性判断，而不是直接接受。
 </USER_REQUEST>

 <USER_CONTENT>
 [长篇论文内容或用户材料]
 </USER_CONTENT>
```

最终系统将 patch 应用到原始输入，生成 polished user input。

这种方法的优势在于：

1. 保留用户原始材料；
2. 只修改与任务意图相关的部分；
3. 对长输入更高效；
4. 修改过程可追踪、可撤销；
5. 可以明确限制 Translator 不得改动数据、引用、代码和附件内容。

因此，patch-based translation 可能成为该系统区别于普通 prompt rewriting 的重要实现设计。

## 与现有 Memory 系统的区别

该工作的核心区别不在于是否使用 retrieval，也不在于是否使用小模型或 Flash API，而在于 memory 的作用位置不同。

典型 memory-augmented agent：

User Input + Retrieved Memories -> Agent

本文提出的架构：

User Input + Managed User Memory -> User Translator -> Polished User Input -> Agent

前者将 memory 作为 agent 的推理上下文；后者将 memory 用于修改和补全用户指令。

因此，memory 在这里不是知识层，而是用户意图解释层。

## 项目边界

当前项目不以以下内容为主要贡献：

* 训练专门的 intent 模型；
* 提出新的基础模型；
* 构建新的 benchmark；
* 直接提升 agent 的知识检索能力；
* 将用户历史简单地 top-k 注入 agent prompt；
* 构建完整的用户 persona；
* 从所有交互中无差别地提取长期记忆。

系统可以直接调用现有 Flash 模型完成 memory summarization、memory management 和 query translation。

## Benchmark 前提

本项目不计划新建 benchmark。

因此，该方向是否值得继续，取决于是否存在能够直接或经过有限适配评测以下能力的现有 benchmark：

1. 从用户后续反馈中识别其真实需求；
2. 从多轮历史中识别反复出现的用户要求；
3. 判断某条 requirement 的适用 scope；
4. 处理 preference 的新增、修改、冲突和删除；
5. 根据用户历史完善当前 underspecified query；
6. 对比 polished user input 与原始输入在下游任务上的效果；
7. 测量 memory translation 是否优于 raw memory injection。

如果现有 benchmark 无法覆盖其中的核心环节，并且必须自行构建大规模标注数据才能验证，那么该项目不应继续推进。

## 核心研究问题

本文最终希望回答的是：

> Can user feedback and repeatedly expressed requirements be maintained as scoped, editable memory and used by a lightweight user translator to patch underspecified user requests before they are passed to downstream agents?

更具体地说：

> Compared with directly injecting user memories into an agent prompt, can a memory-grounded user translator produce more accurate and controllable user instructions while preserving the user's original content?
