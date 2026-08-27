<p align="center">
  <img src="assets/memtranslator-logo.svg" width="112" alt="MemTranslator double-arrow logo">
</p>

<h1 align="center">MemTranslator</h1>

<p align="center">
  <strong>Continually learning how you want your agent to get work done.</strong>
</p>

MemTranslator is a user-side memory layer for how tasks should be executed
and delivered. It learns from your instructions and corrections, then brings
the relevant preferences into your request before it reaches your agent.

> Think of it as a **shared, self-updating `AGENTS.md` for your working
> preferences**—continually maintained from your instructions and corrections.

## Why MemTranslator

- **Less repetition, less rework.** Carry forward your requirements instead
  of repeatedly explaining the same tone, format, evidence standard, or
  working procedure.
- **Your preferences travel with you.** Use one local memory across supported
  desktop and web inputs, including tools such as Codex, Cursor, and ChatGPT.
- **You have the final say.** Review and edit every rewrite before sending.
  Inspect, modify, or delete learned preferences in the Control Center.
- **Relevant instructions, not memory dumps.** The agent receives your
  rewritten request, not a separate memory store or a full personal profile.
- **Keep your tools and workflow.** Rewrite in the current input box with a
  hotkey. No downstream agent SDK integration or extra chat interface.

## Quickstart

**Requirements:** macOS for desktop integration, Python 3.12+, Git, and an
OpenAI-compatible or Anthropic LLM endpoint. Choose one installation method;
both use the same local runtime data by default.

### Option 1 — Install the package with pip

In a new directory, create an isolated environment and install the package:

```bash
mkdir -p my-memtranslator
cd my-memtranslator
python3.12 -m venv venv
source venv/bin/activate

python -m pip install --upgrade "git+https://github.com/FFFFFFFANG1/MemTranslator.git@macos-client"
memtranslator init
memtranslator start
```

The PyPI release is not published yet, so this installs the package directly
from the `macos-client` branch. Once published, the installation command will
be `python -m pip install -U memtranslator`. On later runs, reactivate the
environment with `source venv/bin/activate`, then run `memtranslator start`.

### Option 2 — Develop from source with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed,
then use the current macOS client branch:

```bash
git clone --branch macos-client https://github.com/FFFFFFFANG1/MemTranslator.git
cd MemTranslator
./scripts/dev-sync.sh

uv run memtranslator init
uv run memtranslator start
```

The sync script prepares one editable environment for the package, backend,
macOS client, and tests. Changes to `web/index.html` need a browser refresh;
restart the app after changing Python code.

### Configure once, adjust any time

`init` configures the LLM first: API format, model name, base URL, and key.
It then asks whether to configure a remote embedding API:

- **N:** download the default multilingual ONNX CPU model. No embedding API
  key or vector database is required.
- **Y:** enter an embedding model name. Leave its key and base URL blank to
  reuse the LLM connection; that endpoint must support an OpenAI-compatible
  `/embeddings` API.

Use the settings icon in the Control Center to change either configuration
later. The embedding **Default** button restores the local multilingual model
and downloads it if missing.

### Rewrite with the hotkey

1. Start MemTranslator and grant **Accessibility** permission when prompted.
   macOS may also request **Input Monitoring**. Relaunch after granting access.
2. Focus a supported input box and press **Option + Command + R** (`⌥⌘R`).
3. Review or edit the rewritten request, then send it normally.

Keep the terminal open while using the client; press **Ctrl+C** to stop it.
The Control Center opens at [127.0.0.1:8123](http://127.0.0.1:8123) by default.
It is a memory manager, not a chat app: manage item text, work kind, scope,
bucket, and deleted items; configure the source allowlist, model settings,
language, and light/dark appearance.

For a first look with ten example memories, start with:

```bash
memtranslator start -demo
# From the source checkout:
uv run memtranslator start -demo
```

Run one of these commands, not both. Demo mode adds ten rules with different
scopes and lifecycles to the current store without duplicating them on later
runs. Use `start` without `-demo` for normal operation.

## Contents

- [Architecture and core mechanisms](#architecture-and-core-mechanisms)
- [Rethinking the memory layer for task-driven agents](#rethinking-the-memory-layer-for-task-driven-agents)
- [Performance comparison](#performance-comparison)
- [Limitations](#limitations)
- [Acknowledgements](#acknowledgements)

## Architecture and core mechanisms

![MemTranslator architecture: a user-side intermediary with review before sending, A-side extraction and consolidation, B-side correction feedback, a six-bucket preference store, and recall-driven rewriting.](assets/memtranslator-architecture-no-header.png)

Original instructions and attributed corrections maintain one preference
store. Recall selects preferences for the current task; the translator
produces a request the user can inspect before sending to their existing
agent. The diagram shows conceptual dependencies, not synchronous execution.

### Learn, correct, recall, rewrite

1. **Extractor A — learn from instructions.** Eligible original user text is
   buffered for candidate extraction. Each candidate retrieves a small set of
   related memories; consolidation decides whether to add, reaffirm, merge,
   revise, retire, or ignore it.
2. **Extractor B — learn from corrections.** A user edit is paired with
   snapshots of the memories actually applied in that rewrite. B can update
   or retire those entries, or leave them unchanged; it does not create
   unrelated new memories. Unchanged rewrites do not trigger B extraction.
3. **Reverse retrieval — applicability first, item text second.** In the
   attribute-first mode, work-kind and scope attributes retrieve a candidate
   pool, then item text is used for reranking. Explicit global requirements
   use a separate budget from scoped recall.
4. **Translator — compile, then let the user decide.** Selected preferences
   become explicit requirements in the current request. Guarded patching and
   write-back checks protect the focused input; the user reviews the result.

A and B buffer independently. Generated rewrites are never treated as raw
user evidence for A. “Continual learning” here means maintaining memory
through instructions and feedback, not retraining model weights.

The store uses six controlled buckets: `task_goal`, `reasoning_policy`,
`deliverables`, `output_contract`, `communication_style`, and
`execution_policy`. Items also carry work-kind, scope, and lifecycle
metadata. They are editable requirements, not an opaque user profile.

**Attribute-first recall is currently opt-in.** Enable it with:

```bash
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 memtranslator start
# From the source checkout:
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 uv run memtranslator start
```

Run the command matching your installation. The current default, `0`, keeps
the text-first recall baseline. Both paths use the configured embedding
service, with lexical fallback when dense retrieval is unavailable.

## Rethinking the memory layer for task-driven agents

### When the workspace absorbs recall

Agents can inspect files, revisit past work, and maintain persistent notes.
Our reading of this shift is that **part of the factual and historical recall
once delegated to standalone memory systems is increasingly being absorbed
into agents' own workspaces and search tools**. Anthropic describes
[just-in-time context retrieval and persistent note-taking](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents);
Deep Agents exposes
[filesystem-backed memory with on-demand reads and updates](https://docs.langchain.com/oss/python/deepagents/memory).

In that setting, a separate user-side memory layer needs a clearer purpose
than keeping another copy of project facts or replaying old conversations.
Task facts can stay close to their sources. Past records can remain
searchable. The question becomes:

> When agents own their workspaces and move from conversations to tasks,
> what should a user-side memory layer still maintain?

Our answer is **how the user wants the work done**.

### Available history is not an active preference

A larger context window or a successful search can make a past instruction
available. It does not, by itself, decide whether that instruction should
remain a default for future work.

Consider these three statements:

| What the user said | What needs to be maintained |
| --- | --- |
| “For this reply, give me only three bullets.” | A one-off instruction, not automatically a lasting preference |
| “For future client emails, lead with a three-bullet summary.” | A reusable preference with a specific scope |
| “For these emails, use short paragraphs instead.” | A possible revision of the earlier preference |

An agent can reason over these records. MemTranslator's choice is to maintain
the resulting preferences on the user's side, where they can be inspected,
corrected, and reused across agents.

The distinction is not simply **what did the user say?** It is **what should
carry forward, when should it apply, and when should it change?**

### Our boundary: procedural preferences

By *procedural preferences*, we mean user requirements for task execution and
delivery—not an agent's general skill library, and not a comprehensive
biography.

For example:

- When researching, cite primary sources beside factual claims.
- When modifying code, keep the change focused and report unrun tests.
- When writing to clients, lead with the decision and keep the message short.

These preferences may be global or scoped to a task, audience, or project.
They should help fill in requirements the user has left implicit, not
override what the user explicitly asks for now.

This is a division of responsibility, not a claim that facts, episodic
memory, or reusable skills are obsolete. Those can remain valuable inside an
agent's working environment. MemTranslator deliberately focuses its
independent memory layer on the user's way of working.

### A shared, self-updating AGENTS.md

The simplest mental model is an **automatically updated, continually
maintained, shared `AGENTS.md` for your working preferences**:

- **Automatically maintained:** eligible instructions and corrections feed
  the memory loop; users can also edit items directly.
- **Shared across your agents:** the preferences belong to the user-side
  layer rather than a single conversation, repository, or agent.
- **Applied selectively:** the current request receives relevant
  requirements instead of the entire memory file.

This is an analogy, not file synchronization: MemTranslator does not create
or modify the agents' `AGENTS.md` files. It compiles preferences into an
ordinary request that the user can review.

Native agents and other memory systems can also maintain preferences. Our
product choice is to combine a narrow preference boundary, cross-agent use,
ongoing correction, and human-visible application in one user-side layer.

## Performance comparison

The [August 26 E1 report](2026-08-26-memtranslator-e1-performance-report.md)
compares native MemTranslator with a Codex file-memory workflow on 12 noisy
episodes, 6,225 historical turns, and 103 scored tasks. E1 evaluates memory
maintenance and preference use in **request rewrites**, not downstream coding
or general task-solving ability.

MemTranslator used native extraction and storage, BGE-M3 retrieval, and a
**DeepSeek V4 Flash** translator. The baseline maintained
`AGENTS.md + MEMORY.md` and used **GPT-5.5 medium** for readout.

| Metric | MemTranslator | Codex file memory |
| --- | ---: | ---: |
| Applicable-memory CARRY, macro | **0.713** | 0.672 |
| Inapplicable-memory SUPPRESS, macro | 0.894 | **0.987** |
| Task-perfect rewrites | **68/103 (66.0%)** | 67/103 (65.0%) |
| Store lifecycle STATE, macro | 0.707 | Not comparable |

In this run, MemTranslator carried five more applicable memories; Codex
suppressed four more negative examples. Task-perfect rewrites differed by
one task. The paired CARRY and SUPPRESS confidence intervals cross zero:
these observations do **not** establish overall superiority or statistical
equivalence.

The result supports the feasibility of a flash-tier intermediary for this
workflow. It is a system-level comparison, not an isolated test of Extractor
B or reverse retrieval. The benchmark's BGE-M3 configuration also differs
from the local ONNX embedding default in Quickstart. See the report for
protocol details, uncertainty, and evidence limits.

## Limitations

- **Desktop compatibility.** The hotkey client is macOS-only. Accessibility
  support varies across native, Electron, and browser inputs; uncertain
  targets can result in a no-op or failed read/write.
- **Learning is fallible and asynchronous.** Extraction and consolidation can
  miss, overgeneralize, or fail to retire a preference. A and B run in batches,
  so a correction is not guaranteed to become an immediate memory update.
- **Capture has a boundary.** Desktop capture is initiated by a hotkey
  transaction. Silent A-side learning is restricted to the configurable
  source allowlist; this is not continuous recording of every app or input.
- **Local-first is not fully offline.** Memory and configuration are stored
  under `~/Library/Application Support/MemTranslator` on macOS. Configured
  LLM calls send relevant text and memory evidence to that endpoint; remote
  embedding mode also sends text to its provider. API keys are stored in a
  local mode-`0600` file and are visible in settings. Keep the Control Center
  local.
- **No memory dump does not mean zero context cost.** Compiled requirements
  still occupy prompt tokens, and relevance selection can be wrong. Rewrite
  latency depends on the model and endpoint.
- **Evidence is limited.** The reported comparison has 12 episode clusters,
  different native system components, and no basis for an end-to-end
  speed/cost ranking. In that run, Codex had higher observed SUPPRESS; neither
  system was perfect.

## Acknowledgements

- [Mem0](https://github.com/mem0ai/mem0) — inspiration for practical,
  continually maintained memory layers.
- [Typeless](https://www.typeless.com/) — inspiration from its in-app
  voice-to-polished-text experience for our hotkey-triggered, in-place
  rewriting workflow.
