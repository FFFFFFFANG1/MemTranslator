# 设计与使用细节

[English](design_detail.md) | **简体中文**

[README 快速开始](../README.zh-CN.md#快速开始)介绍了安装方式和两个桌面快捷键。
本文说明配置、Learn 边界，以及该工作流背后的当前实现。

## 目录

- [运行环境与权限](#运行环境与权限)
- [LLM 与嵌入配置](#llm-与嵌入配置)
- [快捷键与来源允许列表](#快捷键与来源允许列表)
- [哪些内容会进入记忆](#哪些内容会进入记忆)
- [记忆管理](#记忆管理)
- [召回配置](#召回配置)
- [演示与启动选项](#演示与启动选项)
- [本地存储与隐私](#本地存储与隐私)
- [开发工作流](#开发工作流)

## 运行环境与权限

需要 Python 3.12 或更高版本。桌面客户端运行于 macOS；也可以通过
`memtranslator start --server-only` 单独运行后端和记忆管理器，不启动桌面客户端。
从源码安装还需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)。

`memtranslator start` 会启动本地后端，打开 Control Center（默认地址为
`http://127.0.0.1:8123`），并启动 macOS 菜单栏客户端。
请保持终端打开。Ctrl+C 会停止该命令启动的客户端和后端；如果复用了已有后端，
本次命令不拥有该后端，也不会将它停止。

出现提示时，请授予**辅助功能（Accessibility）**权限。macOS 还可能要求
**输入监控（Input Monitoring）**权限。授权后请重新启动。
如果事件监听器无法启动，请检查用于启动客户端的可执行文件或应用是否拥有权限。
受支持的应用仍需通过 macOS 辅助功能接口暴露可编辑输入框；加入允许列表本身不会赋予这种能力。

## LLM 与嵌入配置

首次运行 `memtranslator init`；如果已准备好源码环境，则运行
`uv run --no-sync memtranslator init`。更新或重新安装后无须再次运行 `init`。
选择后端端口后，依次配置：

1. **LLM：** 选择 `openai-compatible` 或 `anthropic`，然后输入模型名称、基础 URL 和 API 密钥。
   这里选择的是 API 格式，不是服务提供方列表。
2. **嵌入：** 选择是否使用远程嵌入 API。

   - **N 或直接回车：** 准备默认的 `multilingual-e5-small` ONNX CPU 模型。
     提示中会说明下载大小（约 252 MB）；已准备好的文件会被复用。
     这是本地嵌入，并非禁用嵌入，无须嵌入 API 密钥或向量数据库。
   - **Y：** 输入嵌入模型名称、API 密钥和基础 URL。后两个字段直接按 **Enter**，
     可复用 LLM 的密钥和 URL。端点必须提供兼容 OpenAI 的 `/embeddings` API；
     仅支持聊天或 Anthropic messages API 并不足够。

之后可以通过 Control Center 的设置图标修改 LLM 和嵌入配置。
嵌入设置中的 **Default** 会恢复本地多语言模型，并在文件缺失时下载。
即使共用连接配置，LLM 与嵌入调用也使用独立的服务模块。

API 密钥可在设置中查看，并保存在应用的本地 `.env` 文件中，文件权限为 `0600`。
这不是加密的凭据存储。哪些内容留在本地、哪些会发往配置的端点，见[本地存储与隐私](#本地存储与隐私)。

## 快捷键与来源允许列表

### Write 和 Learn 是两个独立操作

| 输入 | 行为 |
| --- | --- |
| **Fn + R**（`Fn+R`） | **Write：** 读取当前聚焦的草稿，编译适用偏好并验证写回。它会创建 Pending Write，但不会发送或学习。 |
| **Fn + Enter**（`Fn+Enter`） | **Learn：** 保存草稿快照，转发一次普通 Enter，并向 Extractor A 提交用户撰写的证据。无须事先 Write。 |
| 普通 **Enter** | 保留应用的正常行为，并关闭匹配的 Pending Write。它绝不会学习。 |

Learn 会先转发 Enter，不等待记忆提取完成。只有在配置为 Enter 发送的编辑框中，
这才意味着“发送”；其他编辑框可能只是插入换行。
MemTranslator 不会确认目标应用的服务端是否收到消息。
Learn 持久化失败会单独报告，绝不会因此再次发送 Enter。

快捷键处理器只接受精确的 Fn 组合；额外带有 Command、Option、Control 或 Shift 的组合
不再被拦截。在允许列表之外或不受支持的输入框中，系统会回放原生快捷键，
而不是执行 Write 或 Learn。菜单中的 **Write Focused Input**
操作仍可用于其他受支持的输入框。

这里的 Fn 指 macOS 的 Fn/地球仪修饰键。键盘必须能提供这个修饰键；
部分非 Apple 外接键盘不支持。Learn 同时接受 Return 和数字键盘 Enter，
数字键盘的位置标志不会改变快捷键匹配结果。

### 如何识别来源

客户端通过 macOS 辅助功能接口获取当前聚焦的应用和输入框。
原生应用按 bundle identifier 或应用名称匹配。
对于已识别的浏览器，还必须能读取页面域名；仅识别出浏览器不代表允许其中的所有网站。
网站匹配只保留主机名，不保留完整 URL 或查询参数。

Control Center 的 **Allowlist** 页面支持添加、编辑和删除来源。
应用条目按 bundle ID 或名称进行不区分大小写的精确匹配；网站条目匹配指定域名及其子域名。
不支持按路径或单个对话过滤。默认包括：

- **应用：** Codex、Cursor、Claude、Claude Code、ChatGPT 和 Windsurf。
- **网站：** ChatGPT、Claude、Gemini、豆包、DeepSeek、Kimi、元宝、Perplexity、Poe、Grok 和 Copilot。

允许列表中的名称并不保证兼容性。例如，在 Terminal 内运行的 CLI 仍然是终端输入，
不会自动成为原生的“Claude Code”输入框。终端滚动历史和安全输入框不参与 Write；
浏览器域名不可读时，系统会拒绝操作。

## 哪些内容会进入记忆

### Extractor A：用户主动提供的证据

桌面端从原始消息学习，需要在允许且受支持的输入框中执行 **Learn**（`Fn + Enter`）。
打字、Write、普通 Enter、鼠标点击、焦点变化和时间流逝，都不会独立将原始消息加入 A 的队列。
另一个主动入口是记忆管理器中未填写完整的手动条目表单，见[记忆管理](#记忆管理)。

对于从未执行 Write 的草稿，Learn 会提交用户撰写的文本。
执行 Write 后，Learn 会提交关联翻译事件中的原文，而不是让 A 学习模型自己的输出。
重复 Write 时，A 保留**第一次 Write 前的原文**，B 的纠正反馈则针对**最近一次 Write**。
服务端会验证翻译 ID 和来源身份，之后才接受这种关联。

只要客户端仍在运行，Pending Write 就会保留来源关系；即使焦点移到其他输入框，稍后回来也不会丢失。
纠正反馈有五分钟的归因窗口。窗口结束后，未变化的 Write 结果仍可 Learn 第一次 Write 前的原文，
但不会提交 B 反馈；已变化的草稿会因来源有歧义而拒绝 Learn。这时可以使用普通 Enter 发送而不 Learn。
该机制不是用于检测从其他地方粘贴的 AI 生成文本的通用检测器。

A 之前没有基于关键词或规则的偏好筛选器。符合条件的非空证据进入缓冲区，
再由提取器判断其中是否包含长期要求。每条消息提供给提取器的内容最多为 **600 tokens**，
长文本保留开头和结尾。Learn 一条消息，并不保证整条消息都会成为记忆条目。

### Extractor B：对已应用记忆的纠正

Write 会创建一个绑定到该输入框的 Pending Write；不同输入框保留相互独立的会话，客户端不会周期性轮询文本。
焦点变化或其他输入框中的活动只会让相应会话停放，不会关闭它。
在匹配的输入框中执行 Learn 时，客户端一次性读取当前草稿，并可提交纠正反馈。
普通 Enter 只关闭匹配会话而不学习；鼠标事件只有在随后一次读取确认同一个输入框已清空时才会关闭会话。

反馈通过 `translate_id` 关联，而不是与无关对话做模糊匹配。
服务端比较 Write 结果与 Learn 时的用户文本，并将差异与本次 Write 所应用的记忆快照配对。
B 要求同时存在已应用条目和实际文本差异。它可以更新或淘汰这些条目，也可以不作修改；
不会创建无关的新记忆。未修改的 Write 结果不会调用 B 提取，但接受结果可以通过机制性更新调整记忆强度。

完整的 Write 结果和 Write 后新添加的片段，都不会通过这条反馈路径送入 A。
Learn 是关于草稿的学习证据，不代表目标 Agent 已经收到消息。
这套桌面工作流不需要 Claude Code hook。

### 批处理与恢复

A 和 B 使用独立队列。当前默认阈值为 **A 的 8 条消息**、**B 的 3 条具有明确归因的差异**，
或从最早待处理条目算起的 **30 分钟**队列等待时间。
服务端在后续学习活动调用刷新路径时检查这些阈值；没有独立定时器保证应用空闲时恰好在第 30 分钟执行提取。

已接受的桌面 Learn 会写入本地事件日志。使用同一 Learn ID 重试会去重；
新的 Learn 操作则是新事件，即使文本完全相同。
守护进程重启后会恢复尚未处理的桌面 A 提交，已处理项则有标记，正常重放时会跳过。
LLM 不可用时，已接受的 A 队列会保留，等待后续尝试。
这不是客户端离线发件箱：未确认的提交会向用户报告。
B 队列和未填写完整的手动条目队列，没有同样的重启重放机制。

## 记忆管理

Control Center 是记忆管理器，不是第二个聊天界面。
每个条目显示文本、任务类型、作用域和类别。
**Modify**、**Delete** 和 **New** 操作后端存储；已删除条目可以恢复。

- **Work kind（任务类型）：** 如 `email` 或 `report`。勾选 **Any** 表示所有任务类型。
- **Scope（作用域）：** 自然语言条件或 `audience=client` 这样的结构化过滤条件。
  **Global** 表示广泛适用的默认要求，且任务类型必须为 **Any**。作用域留空不等于全局。
- **Bucket（类别）：** 受控下拉选项，不能自由输入。六个类别为
  `task_goal`、`reasoning_policy`、`deliverables`、`output_contract`、
  `communication_style` 和 `execution_policy`。尚未分配类别时，可选择未分类选项。

创建条目时，如果任务类型和作用域都已填写，则直接写入偏好库。
只要缺少其中一项，提交的文本就会作为用户消息加入 Extractor A 的队列。
部分填写的表单元数据会被记录，但只有文本会作为提取证据；表单不会暗中创建全局规则。
编辑已有条目时，两项属性都必须填写。

界面还支持中英文，以及浅色、深色和跟随系统的外观设置。
这些选项只影响界面，不会改变已存储记忆文本的语言。

## 召回配置

全局召回与作用域召回使用独立预算：全局要求共享 **2,048 个提示词 token**，
作用域召回最多选择 **16 个条目**。任务类型、作用域和生命周期元数据共同帮助判断适用性。

属性优先（也称反向检索）路径先用任务类型和作用域属性检索候选，再根据条目文本重排。
目前需要**手动启用**；`MT_SCOPED_ATTRIBUTE_POOL_CAP=0` 保留文本优先的基线方案。
要启用包含 32 个作用域条目的属性优先候选池，请根据安装方式运行对应命令：

```bash
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 memtranslator start
```

从源码目录运行：

```bash
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 uv run --no-sync memtranslator start
```

两条路径都使用配置的嵌入服务；稠密检索不可用时，回退到词项匹配。
Translator 读取的当前请求最多为 4,096 tokens，超出时保留开头和结尾。
这些是当前实现的默认值，不保证能找到每条相关记忆。

## 演示与启动选项

要添加十条具有不同作用域和生命周期的预设示例（包括一条全局默认规则），运行以下任一命令：

```bash
memtranslator start -demo
# From the source checkout:
uv run --no-sync memtranslator start -demo
```

演示模式写入的是**当前偏好库**，不是临时沙盒。重复启动不会重复导入这些演示 ID。
正常使用时运行 `start`，不加 `-demo` 即可；这不会移除先前导入的演示条目。

| 启动选项 | 用途 |
| --- | --- |
| `-demo` / `--demo` | 导入十条演示规则。 |
| `--server-only` | 启动时不运行 macOS 快捷键客户端。 |
| `--no-open` | 不自动打开浏览器。 |
| `--port PORT` | 覆盖本次启动使用的后端端口。 |
| `--home PATH` | 使用其他应用数据目录；需先使用相同的 `--home` 完成初始化。 |

全部 CLI 选项可通过 `memtranslator init --help` 或 `memtranslator start --help` 查看。
在已准备好的源码环境中使用时，前面加上 `uv run --no-sync`。

## 本地存储与隐私

macOS 默认应用数据目录为 `~/Library/Application Support/MemTranslator`，
与安装目录相互独立。其他平台默认为 `~/.memtranslator`。

| 应用数据目录内的路径 | 内容 |
| --- | --- |
| `.env` | 模型连接设置、密钥和运行配置。 |
| `data/store.jsonl` | 偏好条目及其生命周期状态。 |
| `data/events.jsonl` | 本地事件，包括 Learn 文本、Write 翻译结果和反馈。 |
| `data/source_allowlist.json` | 保存的来源允许列表自定义配置。 |
| `models/multilingual-e5-small/` | 默认本地嵌入模型文件。 |

**本地优先不等于完全离线。** LLM 调用会将相关输入和记忆证据发送到配置的端点。
远程嵌入模式也会发送文本以生成嵌入；本地 ONNX 模式不会。
即使提取器读取的是截断内容，本地事件记录仍可能包含完整文本。
删除记忆条目只是将其淘汰，不会擦除历史事件日志中的内容。

请让 Control Center 保持在本地回环地址上。它提供记忆管理，并能显示 API 密钥，
不适合作为公开托管的多用户服务。备份应用数据目录时，应将其视为敏感数据；
不要将凭据或事件日志提交到代码仓库。

## 开发工作流

当前开发和新的包构建使用 `main` 分支。源码安装同步脚本会为包、后端、macOS 客户端和测试
准备一个可编辑安装环境。它使用 `venv`，并让 `.venv` 指向该目录。
同步后，`uv run --no-sync` 使用已经准备好的环境，不会在每次启动时自动同步依赖包。

```bash
./scripts/dev-sync.sh
uv run --no-sync memtranslator start
```

修改 `web/index.html` 后需要刷新浏览器。修改 Python 代码后需要重启；
依赖或打包配置发生变化后，需要重新运行同步脚本。
如果旧环境针对 `memtranslator.cli` 报出 `ModuleNotFoundError`，
请停止应用，并从仓库根目录重新同步。脚本会拒绝覆盖存在冲突的环境目录。

### 刷新已有的源码安装

切换分支或修改打包配置后，请先停止运行中的客户端和后端，再刷新安装。
在当前 `main` 源码目录中，不复用构建缓存地重新安装可编辑包：

```bash
uv pip install --python venv/bin/python --no-cache --no-deps --reinstall --editable .
uv run --no-sync memtranslator start
```

这只会刷新 MemTranslator。如果依赖也有变化，请先运行 `./scripts/dev-sync.sh`。
可编辑安装会加载当前源码目录中的代码，因此 Python 修改在重启后即可生效，无须重新构建 wheel。
要检查环境实际加载的是哪个 CLI 模块：

```bash
uv run --no-sync python -c "import memtranslator.cli; print(memtranslator.cli.__file__)"
```

输出路径应指向当前源码目录中的 `src/memtranslator/cli.py`。
刷新安装不会重置应用数据目录、模型配置或偏好库，也无须再次运行 `init`。
它同样不能代替 macOS 辅助功能授权，也不保证解决快捷键问题。

### 通过包安装

安装包包含一份网页界面副本。测试新的包构建时，需要重新安装并重启；
修改其他源码目录不会更新已安装的副本。安装方式变化时，运行数据仍保留在应用数据目录中。

基准协议及其边界，见 [8 月 26 日的 E1 报告](2026-08-26-memtranslator-e1-performance-report.zh-CN.md)。
