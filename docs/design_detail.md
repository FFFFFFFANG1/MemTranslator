# Design and usage details

The [README Quickstart](../README.md#quickstart) covers installation and the
two desktop hotkeys. This page documents configuration, capture boundaries,
and the current implementation behind that workflow.

## Contents

- [Runtime and permissions](#runtime-and-permissions)
- [LLM and embedding configuration](#llm-and-embedding-configuration)
- [Shortcuts and source allowlist](#shortcuts-and-source-allowlist)
- [What enters memory](#what-enters-memory)
- [Memory management](#memory-management)
- [Recall configuration](#recall-configuration)
- [Demo and startup options](#demo-and-startup-options)
- [Local storage and privacy](#local-storage-and-privacy)
- [Development workflow](#development-workflow)

## Runtime and permissions

Python 3.12+ is required. The desktop client runs on macOS; the backend and
memory manager can run without it using `memtranslator start --server-only`.
The source-install path also requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

`memtranslator start` launches the local backend, opens the Control Center
at `http://127.0.0.1:8123` by default, and starts the macOS menu-bar client.
Keep the terminal open. Ctrl+C stops the client and backend launched by that
command; a backend it reused is not owned or stopped by this invocation.

Grant **Accessibility** permission when prompted. macOS may also request
**Input Monitoring**. Relaunch after granting access. If the event tap cannot
start, check the permissions for the executable or app used to launch the
client. A supported app still needs an editable input exposed through macOS
Accessibility; adding it to the allowlist does not supply that capability.

## LLM and embedding configuration

Run `memtranslator init` once, or `uv run --no-sync memtranslator init` from
the prepared source environment. Updating or reinstalling the package does
not require another `init`. After choosing the backend port, configuration
proceeds in order:

1. **LLM:** choose `openai-compatible` or `anthropic`, then enter the model
   name, base URL, and API key. These are API formats, not a provider catalog.
2. **Embedding:** choose whether to use a remote embedding API.

   - **N, or Enter:** provision the default `multilingual-e5-small` ONNX CPU
     model. The prompt announces the download (approximately 252 MB); already
     provisioned files are reused. This is local embedding, not disabled
     embedding, and requires no embedding API key or vector database.
   - **Y:** enter the embedding model name, API key, and base URL. Press
     **Enter** in the last two fields to reuse the LLM key and URL. The
     endpoint must expose an OpenAI-compatible `/embeddings` API; support for
     chat or Anthropic messages alone is not sufficient.

The settings icon in the Control Center lets you change the LLM and embedding
configuration later. Embedding **Default** restores the local multilingual
model and downloads it if missing. LLM and embedding calls use separate
service modules, even when their connection settings are shared.

API keys are visible in settings and stored locally in the application's
`.env` file with mode `0600`. This is not encrypted credential storage. See
[Local storage and privacy](#local-storage-and-privacy) for what stays local
and what is sent to configured endpoints.

## Shortcuts and source allowlist

### Rewrite and capture are separate actions

| Input | Behavior |
| --- | --- |
| **Option + Control + R** (`⌥⌃R`) | Read the focused draft, request a rewrite, verify write-back, and track subsequent edits. Does not send or queue raw text for Extractor A. |
| **Option + Control + Enter** (`⌥⌃Enter`) | Snapshot the draft, forward one ordinary Enter, and submit user-authored evidence for Extractor A. No prior rewrite is needed. |
| Ordinary **Enter** | Preserve the app's normal behavior. It can finish an active rewrite-feedback session, but does not capture a new raw message for A. |

Capture forwards Enter before waiting for memory extraction. This means
"send" only in a composer configured for Enter-to-send; in another composer
it may insert a newline. MemTranslator does not confirm server-side delivery
in the target app. A memory-capture failure is reported separately and never
causes Enter to be sent again.

The shortcut handler accepts the exact Option + Control combinations. The
old `⌥⌘R`, `⌥R`, and `⌥Enter` shortcuts are no longer intercepted. Outside
the allowlist or in unsupported inputs, it replays the native shortcut rather
than rewriting or queuing memory. The menu's **Polish Focused Input** action
remains available in other supported inputs.

### How sources are identified

The client obtains the focused app and input from macOS Accessibility. Native
sources are matched against the app's bundle identifier or name. Known
browsers additionally require a readable page domain; browser identity alone
does not allow every website. Only the hostname is retained for website
matching, not the full URL or its query string.

The Control Center's **Allowlist** page supports adding, editing, and deleting
sources. App entries use exact, case-insensitive bundle-ID or name matches;
website entries match a domain and its subdomains. There is no per-path or
per-conversation filter. Defaults include:

- **Apps:** Codex, Cursor, Claude, Claude Code, ChatGPT, and Windsurf.
- **Websites:** ChatGPT, Claude, Gemini, Doubao, DeepSeek, Kimi, Yuanbao,
  Perplexity, Poe, Grok, and Copilot.

An allowlisted label is not a compatibility guarantee. In particular, a CLI
running inside Terminal is still a terminal input, not automatically a native
"Claude Code" input. Terminal scrollback and secure fields are excluded from
rewriting; an unreadable browser domain fails closed.

## What enters memory

### Extractor A: explicitly supplied user evidence

Desktop raw-message learning requires **Option + Control + Enter** in an
allowed, supported input. Typing, rewriting, ordinary Enter, mouse clicks,
focus changes, and tracking timeouts do not independently queue raw messages
for A. A second explicit entry point is the memory manager's incomplete
manual-item form, described under [Memory management](#memory-management).

For a draft that has never been rewritten, capture supplies its user-authored
text. For a rewritten draft, it supplies the original from the linked
translation event instead of teaching A the model's own output. Repeated
rewrites retain the **first pre-rewrite original** for A, while feedback
judges the **latest rewrite** for B. The server validates the translation ID
and source identity before accepting that link.

If a known rewritten draft changes after its tracking session has ended,
the client cannot safely establish its provenance and refuses explicit
capture. Use ordinary Enter to send without capture. Provenance is maintained
by the running client; this is not a general detector of AI-generated text
pasted from elsewhere.

There is no keyword or rule-based preference screen before A. Non-empty,
eligible evidence is buffered; the extractor decides whether it contains a
lasting requirement. Its input view is capped at **600 tokens per message**,
keeping the beginning and end of long text. Capturing a message does not
promise that the entire message becomes a memory item.

### Extractor B: corrections to applied memories

After a rewrite, a short-lived tracker observes the same input. Ordinary
Enter, a cleared input, a focus change, or **five minutes without a text
change** can close the session. Mouse clicks cause a follow-up observation;
they are not independently treated as proof that a message was sent.

Feedback is joined by `translate_id`, not a fuzzy match to an unrelated
conversation. The server compares the rewritten text with the latest observed
user text and pairs the diff with snapshots of the memories applied in that
rewrite. B requires both applied entries and a real diff. It can update or
retire those entries, or make no change; it does not create unrelated new
memories. An unchanged rewrite does not invoke B extraction, though acceptance
can update memory strength mechanically.

Neither the full rewritten text nor newly added post-rewrite fragments are
fed to A through this feedback path. Observation is feedback about the draft,
not confirmation that the target agent received it. No Claude Code hook is
required for this desktop workflow.

### Batching and recovery

A and B have separate queues. Current defaults are **8 messages for A** and
**3 attributed diffs for B**, or a queue age of **30 minutes** measured from
the oldest pending entry. The server checks those thresholds when later
learning activity calls the flush path; there is no independent timer that
guarantees extraction at exactly 30 minutes while the app is idle.

Accepted desktop captures are journaled in the local event log. A retry with
the same capture ID is deduplicated; a new capture gesture is a new event,
even if its text is identical. Pending desktop A captures are restored after
a daemon restart, while processed captures are marked so normal replay skips
them. LLM unavailability leaves the accepted A queue pending for a later
attempt. This is not a client-side offline outbox: an unconfirmed submission
is reported to the user. B and incomplete manual-item queues do not have the
same restart-replay mechanism.

## Memory management

The Control Center is a memory manager, not a second chat interface. Each
item shows its text, work kind, scope, and bucket. **Modify**, **Delete**, and
**New** operate on the backend store; deleted items can be restored.

- **Work kind:** a task category such as `email` or `report`; use the **Any**
  checkbox for all work kinds.
- **Scope:** a natural-language condition or structured filters such as
  `audience=client`. **Global** marks a broadly applicable default and
  requires work kind **Any**. An empty scope is not implicitly global.
- **Bucket:** a controlled dropdown, not free text. The six buckets are
  `task_goal`, `reasoning_policy`, `deliverables`, `output_contract`,
  `communication_style`, and `execution_policy`. An unclassified option is
  available when a bucket has not been assigned.

Creating an item with both work kind and scope writes it directly to the
store. If either is omitted, the submitted text is treated as a user message
and queued for Extractor A instead. Partial form metadata is logged, but only
the text is supplied as extraction evidence; the form does not silently
create a global rule. Existing-item edits require both attributes.

The UI also supports English/Chinese and light/dark/system appearance. These
controls affect the interface, not the language of stored memory text.

## Recall configuration

Global and scoped recall have separate budgets: global requirements share
**2,048 prompt tokens**, while scoped recall selects up to **16 items**.
Work-kind, scope, and lifecycle metadata help determine applicability.

The attribute-first, or reverse-retrieval, path first retrieves candidates
using work-kind and scope attributes, then reranks them using item text.
It is currently **opt-in**; `MT_SCOPED_ATTRIBUTE_POOL_CAP=0` preserves the
text-first baseline. To enable an attribute-first pool of 32 scoped items,
run the command matching your installation:

```bash
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 memtranslator start
```

From a source checkout:

```bash
MT_SCOPED_ATTRIBUTE_POOL_CAP=32 uv run --no-sync memtranslator start
```

Both paths use the configured embedding service, with lexical fallback when
dense retrieval is unavailable. The translator's view of the current request
is capped at 4,096 tokens with head-and-tail truncation. These are current
implementation defaults, not a guarantee that every relevant memory is found.

## Demo and startup options

To add ten curated examples with varied scopes and lifecycles, including a
global default, run one of:

```bash
memtranslator start -demo
# From the source checkout:
uv run --no-sync memtranslator start -demo
```

Demo mode writes to the **current store**, not a temporary sandbox. Repeated
starts do not duplicate those demo IDs. Run `start` without `-demo` for normal
operation; doing so does not remove previously imported demo items.

| Startup option | Purpose |
| --- | --- |
| `-demo` / `--demo` | Import the ten demo rules. |
| `--server-only` | Start without the macOS hotkey client. |
| `--no-open` | Do not automatically open the browser. |
| `--port PORT` | Override the backend port for this launch. |
| `--home PATH` | Use a different application home; initialize it with the same `--home` first. |

Use `memtranslator init --help` or `memtranslator start --help` for all CLI
options. Prefix with `uv run --no-sync` when working from the prepared source
environment.

## Local storage and privacy

The default macOS application home is
`~/Library/Application Support/MemTranslator`, independent of the installation
directory. Other platforms default to `~/.memtranslator`.

| Path inside the application home | Contents |
| --- | --- |
| `.env` | Model connection settings, keys, and runtime configuration. |
| `data/store.jsonl` | Preference items and their lifecycle state. |
| `data/events.jsonl` | Local events, including captured text, rewrites, and feedback. |
| `data/source_allowlist.json` | Saved source-allowlist customization. |
| `models/multilingual-e5-small/` | Default local embedding files. |

**Local-first does not mean fully offline.** LLM calls send the relevant input
and memory evidence to the configured endpoint. Remote embedding mode also
sends text for embedding; local ONNX mode does not. Local event records can
contain full text even when the extractor uses a truncated view. Deleting a
memory item retires it; it does not erase historical event-log content.

Keep the Control Center on the local loopback address. It exposes memory
management and visible API keys and is not intended as a publicly hosted,
multi-user service. Back up the application home as sensitive data and do
not commit its credentials or event logs to a repository.

## Development workflow

Use the `main` branch for current development and new package builds. The
source-install sync script prepares one editable environment for the package,
backend, macOS client, and tests. It uses `venv` with `.venv` pointing to it.
After syncing, `uv run --no-sync` uses that prepared environment without
automatically synchronizing packages on each launch.

```bash
./scripts/dev-sync.sh
uv run --no-sync memtranslator start
```

Changes to `web/index.html` need a browser refresh. Restart after changing
Python code; rerun the sync script after dependency or packaging changes.
If an old environment reports `ModuleNotFoundError` for `memtranslator.cli`,
stop the app and resync from the repository root. The script refuses to
overwrite conflicting environment directories.

### Refresh an existing source installation

After switching branches or changing packaging, stop the running client and
backend before refreshing the installation. From the current `main` checkout,
rebuild the editable package without reusing its build cache:

```bash
uv pip install --python venv/bin/python --no-cache --no-deps --reinstall --editable .
uv run --no-sync memtranslator start
```

This refreshes only MemTranslator. If dependencies also changed, run
`./scripts/dev-sync.sh` first. The editable installation loads this checkout's
source, so Python changes take effect after restarting without rebuilding a
wheel. To check which CLI module the environment actually loads:

```bash
uv run --no-sync python -c "import memtranslator.cli; print(memtranslator.cli.__file__)"
```

The path should point to `src/memtranslator/cli.py` in this checkout. Refreshing
the installation does not reset the application home, model configuration, or
memory store, and does not require another `init`. It also does not replace
macOS Accessibility permissions or guarantee that a hotkey issue is resolved.

### Package installations

Package installs include a copy of the web UI. To test a new package build,
reinstall it and restart; editing an unrelated source checkout does not update
that installed copy. Runtime data stays in the application home across
installation changes.

For the benchmark protocol and its limits, see the
[August 26 E1 report](2026-08-26-memtranslator-e1-performance-report.md).
