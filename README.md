<p align="center">
  <img src="assets/memtranslator-logo.svg" width="112" alt="MemTranslator double-arrow logo">
</p>

<h1 align="center">MemTranslator</h1>

<p align="center">
  <strong>Compile user memory into better requests for any agent.</strong>
</p>

<p align="center">
  A local-first middleware that learns how you want work to be done, rewrites the focused prompt in place, and lets the downstream agent remain completely memory-agnostic.
</p>

MemTranslator sits between you and the agents you already use. It remembers
delivery requirements such as “cite primary sources,” “keep emails under 120
words,” or “state assumptions before conclusions,” then makes the relevant
constraints explicit in your request before it reaches Codex, Cursor, Claude,
ChatGPT, Gemini, or another agent.

The agent never reads MemTranslator's store and needs no SDK integration. It
receives an ordinary prompt that the user can inspect, edit, and approve.

> MemTranslator remembers **how the task should be done**, not everything
> about the user.

## Why MemTranslator

Strong agents still make users repeat the same corrections: the email is too
long, the report lacks sources, the code is over-explained, or the answer uses
the wrong structure. Existing memory approaches often solve this by loading a
profile or memory file into every agent. That creates three practical
problems:

- every agent needs its own memory integration;
- irrelevant memory consumes context and can leak into the wrong task;
- switching agents means rebuilding or copying memory behavior.

MemTranslator treats memory as a compilation layer instead:

```text
user request + applicable delivery requirements -> explicit task request
```

This gives the same working preferences to different agents without changing
their internals. The boundary is intentionally narrow: MemTranslator stores
requirements about execution and delivery, not a general personal profile,
knowledge base, or chat archive.

### Practical value

| What users need | What MemTranslator provides |
| --- | --- |
| Consistent behavior across agents | One local memory layer in front of Codex, Cursor, Claude, ChatGPT, Gemini, and other supported inputs |
| No downstream context pollution | The agent receives only the rewritten request, never the memory store |
| Fewer repeated corrections | Durable delivery requirements are recalled and woven into future tasks |
| Control over learned behavior | Every memory item exposes text, work kind, scope, bucket, lifecycle, Modify, and recoverable Delete |
| Safe personalization | Hotkey-triggered, human-in-the-loop rewriting with guarded write-back and an editable source allowlist |
| Lightweight deployment | Flash-tier LLMs, local ONNX CPU embeddings by default, BM25 fallback, and no vector database requirement |

## Results: flash-tier middleware vs Codex file memory

The E1 noisy evaluation replays a complete memory lifecycle across 12
episodes, 6,225 turns, 103 scored tasks, and stores peaking at 29–42 active
memories. MemTranslator used native extraction, structured storage, BGE-M3
retrieval, and a DeepSeek V4 Flash translator. The comparison system used
incrementally maintained `AGENTS.md + MEMORY.md` files with GPT-5.5 medium.

| Metric | MemTranslator | Codex file memory |
| --- | ---: | ---: |
| Applicable-memory CARRY, macro | **0.713** | 0.672 |
| Applicable-memory CARRY, micro | **74/107 (69.2%)** | 69/107 (64.5%) |
| Inapplicable-memory SUPPRESS, macro | 0.894 | **0.987** |
| Task-perfect | **68/103 (66.0%)** | 67/103 (65.0%) |
| Structured lifecycle STATE | 0.707 | Not comparable |

The observed task-perfect result is effectively tied. MemTranslator carried
five more applicable memories; Codex suppressed four more negative examples.
The paired confidence intervals cross zero, so this is not evidence of overall
statistical superiority. It is evidence that a narrow middleware powered by a
flash-tier model can match a much stronger native file-memory workflow while
remaining agent-independent.

See the [full E1 performance report](./2026-08-26-memtranslator-e1-performance-report.md)
for confidence intervals, per-episode results, protocol details, and limits.

## Quickstart

### Requirements

- macOS for the global hotkey and focused-input integration
- Python 3.12 or newer
- an OpenAI-compatible or Anthropic-compatible LLM endpoint
- Accessibility permission; macOS may also request Input Monitoring

### Install from source

```bash
git clone https://github.com/FFFFFFFANG1/MemTranslator.git
cd MemTranslator
./scripts/dev-sync.sh

uv run memtranslator init
uv run memtranslator start -demo
```

`init` configures the LLM first. It then asks whether to use a remote embedding
API. Choose **N** to download the pinned multilingual ONNX CPU model, or choose
**Y** to provide an OpenAI-compatible embedding model. The embedding key and
base URL can inherit the active LLM connection.

`start -demo` starts the local backend, Control Center, and macOS menu-bar
client, then idempotently adds ten example memories. Use the normal start mode
once you are ready for your own store:

```bash
uv run memtranslator start
```

Press **Option + Command + R** (`⌥⌘R`) in a supported focused input. A small
network animation appears while MemTranslator works, glows after verified
write-back, and disappears. Review or edit the rewritten prompt, then send it
normally.

Open [http://127.0.0.1:8123](http://127.0.0.1:8123) or choose **Open Control
Center** from the menu-bar app to manage memory, the source allowlist, LLM and
embedding settings, UI language, and light/dark appearance.

### Release package

The intended packaged installation is:

```bash
python -m pip install -U memtranslator
memtranslator init
memtranslator start
```

Until the package is published, use the source installation above. Runtime
configuration, memory data, allowlists, and local models are stored under
`~/Library/Application Support/MemTranslator` on macOS. API keys are stored
locally in a mode-`0600` `.env` file.

## High-level architecture

```text
+------------------------------ USER SIDE -------------------------------+
|  Allowlisted composer -> ⌥⌘R -> macOS capture -> local daemon          |
+------------------------------------------------------------------------+
                                  |
                                  v
+------------------------------- READ PATH ------------------------------+
|  raw task                                                              |
|     |                                                                   |
|     +-> explicit global requirements                                   |
|     |                                                                   |
|     +-> reverse retrieval: attributes -> candidate pool -> item rerank |
|                                  |                                     |
|                                  v                                     |
|                         Flash Translator -> guarded patch              |
+------------------------------------------------------------------------+
                                  |
                                  v
+--------------------------- HUMAN-IN-THE-LOOP --------------------------+
|  verified write-back -> user edits or accepts -> normal agent input    |
+------------------------------------------------------------------------+
                    |                                  |
                    v                                  v
+---------------- EXTRACTOR A ----------------+  +----- EXTRACTOR B -----+
| allowlisted raw signals                    |  | applied entries        |
| candidate extraction                       |  | + exact user diff      |
| per-candidate retrieval                     |  | -> update/retire/none  |
| CASE consolidation -> lifecycle operations |  | on attributed entries |
+---------------------------------------------+  +-----------------------+
                    |                                  |
                    +----------------+-----------------+
                                     v
+---------------------------- LOCAL MEMORY STORE ------------------------+
| append-only JSONL | active / retired / superseded | editable Web UI    |
+------------------------------------------------------------------------+
```

## Core mechanisms

### 1. Reverse retrieval: attribute first, item second

Ordinary text retrieval begins by asking which memory sentence resembles the
current task. That is often the wrong first question. A rule such as “keep
future launch copy calm and direct” may share little vocabulary with “draft
the homepage announcement,” even though its applicability attributes are a
strong match.

MemTranslator's reverse-retrieval path reverses the decision order:

1. Encode only the activation attributes: `work_kinds`, `applies_when`, and
   legacy scope.
2. Use the raw task to retrieve a deliberately wider attribute candidate
   pool.
3. Within that pool, use memory-item text with BM25 and dense retrieval to
   select and rerank the final prompt entries.
4. Send at most 16 scoped entries, plus a separately budgeted global lane, to
   the translator.

Attributes answer **where a rule may apply**; item text answers **which rule is
semantically relevant**. Keeping those stages separate helps with
cross-language and low-lexical-overlap tasks while preventing metadata from
overriding the actual requirement.

The attribute-first pool is currently configurable:

```bash
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 uv run memtranslator start
```

Set it to `0` to use the text-first baseline. Both modes reuse the configured
embedding service and fall back safely when dense retrieval is unavailable.

### 2. Extractor B: feedback with causal attribution

Most memory systems learn from a user's next message and must guess which old
memory it corrects. MemTranslator already knows which entries participated in
the rewrite.

Each translation event records an explicit `translate_id` and the exact
memory entries applied. If the user edits the rewritten text, MemTranslator
computes a bounded patch diff and sends Extractor B only:

- the entries used in that translation;
- the translator output around the changed span;
- the user's final edition of that span.

Extractor B can return `update`, `retire`, or `none`. Its decisions are
mechanically bound back to those attributed entries; the model cannot name an
arbitrary Store ID or search unrelated memory. This turns the user's normal
editing behavior into a precise learning signal instead of a second round of
global extraction.

### 3. Candidate-first Extractor A

Route A handles explicit, source-eligible user statements. A normal admitted
batch uses two generative calls—candidate extraction and consolidation—with
one additional schema-repair call only when extractor output is malformed:

```text
signals -> candidate extraction -> independent top-3 retrieval per candidate
        -> multi-CASE consolidation -> validated Store operations
```

The extractor never sees Store IDs or memory text. It emits durable
`potential_new` or `potential_change` candidates with controlled buckets,
work kinds, applicability, and facet keys. A separate consolidator may add,
reaffirm, merge, replace, retire, or ignore each candidate, but only inside
that candidate's retrieved CASE.

### 4. Human-visible, fail-closed translation

The translator emits small patch hunks rather than replacing the complete
request. MemTranslator verifies that focus and source text are unchanged,
preserves the clipboard, checks the written value, and degrades to a no-op on
parse, preservation, focus, or write failures. Unsupported and secure fields
are never typed into speculatively.

## Memory model

MemTranslator stores requirements in six controlled buckets:

| Bucket | Meaning |
| --- | --- |
| `task_goal` | The objective when the task is missing or vague |
| `reasoning_policy` | Method, evidence standard, or decision axes |
| `deliverables` | Required content or artifacts |
| `output_contract` | Structure, length, order, format, and language |
| `communication_style` | Tone, register, voice, and audience treatment |
| `execution_policy` | Tools, workflow, verification, and ask-vs-assume policy |

Each item also carries a work kind, applicability scope, lifecycle state,
facet key, confidence, timestamps, and provenance. Global requirements are
handled separately from retrieved scoped requirements. Deleting an item in
the Control Center retires it instead of erasing history, so it can be
restored and audited.

## Privacy and capture boundary

MemTranslator is not a permanent keylogger or document monitor.

- Capture starts only from an explicit translator hotkey transaction.
- Background learning is restricted to a configurable allowlist of native AI
  clients and AI-assistant websites.
- Browser capture records the hostname, not the full URL.
- Route A keeps a bounded head/tail view of long messages.
- Memory and configuration stay on the local machine unless the configured
  LLM or embedding endpoint is called.
- The Control Center can create, modify, retire, restore, and inspect every
  memory item.

Default allowlist entries cover common clients such as Codex, Cursor, Claude,
ChatGPT, and Windsurf, plus common AI-assistant websites. Add, change, or
remove entries from the **Allowlist** page; changes apply to the next hotkey
transaction.

## Commands

| Command | Purpose |
| --- | --- |
| `memtranslator init` | Configure LLM and local or remote embeddings |
| `memtranslator start` | Start backend, Control Center, and macOS client |
| `memtranslator start -demo` | Start and seed ten deterministic example rules |
| `memtranslator start --server-only` | Start without the macOS menu-bar client |
| `memtranslator start --no-open` | Do not open the Control Center automatically |

The LLM wire format is intentionally small: native Anthropic or
OpenAI-compatible. Ark, OpenRouter, and other compatible services differ only
by model name, API key, and base URL.

## Development

The repository uses one uv environment for the package, backend, Web UI,
macOS client, and tests:

```bash
./scripts/dev-sync.sh
uv run memtranslator start -demo
uv run python -m pytest -q
```

For backend auto-reload during development:

```bash
# terminal A
PYTHONPATH=src uv run uvicorn memtranslator.server:app \
  --host 127.0.0.1 --port 8123 --reload

# terminal B
uv run memtranslator start --no-open
```

The editable installation reads `web/index.html` directly, so Control Center
changes need only a page refresh. Build a release wheel with `uv build`.

## Project structure

```text
MemTranslator/
|-- src/memtranslator/
|   |-- hotkey/          macOS capture, guarded write-back, tracking, overlay
|   |-- translate.py     recall + flash translator + validated patch protocol
|   |-- recall.py        global lane and text/attribute retrieval policies
|   |-- extraction.py    Extractor A candidates and attributed Extractor B
|   |-- memory_write.py  candidate retrieval and CASE consolidation
|   |-- retrieval.py     BM25, embedding service, and deterministic rank fusion
|   |-- store.py         append-only requirement and lifecycle store
|   |-- server.py        local FastAPI daemon and Control Center API
|   `-- embedding.py     local ONNX and remote embedding adapters
|-- web/index.html       bilingual light/dark memory Control Center
|-- bench/               robustness, extraction, lifecycle, and E1 evaluation
|-- tests/               offline mechanical and integration tests
|-- position_anchor.md   product boundary and design priorities
`-- pyproject.toml       package and CLI definition
```

## Limitations

- The system-level E1 comparison does not isolate writer, retriever, and
  readout-model contributions.
- Codex currently suppresses retired or out-of-scope memory more reliably.
- Store lifecycle STATE is 0.707 on the reported run, leaving clear room for
  extraction and retirement improvements.
- The desktop hotkey shell is currently macOS-only.
- Accessibility support varies across native, Electron, and browser inputs;
  uncertain targets fail closed.
- Translation latency still depends on the configured model and endpoint.

## Acknowledgements

MemTranslator is inspired by [Mem0](https://github.com/mem0ai/mem0)'s work on
practical, evolving memory layers and by [Typeless](https://www.typeless.com/)'s
system-wide, keyboard-first experience for transforming text directly inside
the user's current app.

MemTranslator takes a deliberately narrower path: requirement-only memory,
agent-independent prompt compilation, and user-edit feedback bound to the
exact rewrite that produced it.

---

**Keep the agent. Upgrade the request.**
