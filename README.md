# MemTranslator

An open-source translator between you and your agents: it learns how you want tasks done (delivery requirements) and compiles them into the request itself, so downstream agents never read memory. All direction lives in `position_anchor.md`.

**v0** (anchor §7): the product shell — hotkey polish in the composer, human-in-the-loop by default — plus requirement storage and the oracle condition (requirements entered by hand; extraction is v1).

```
src/memtranslator/
  schema.py      Requirement (requirement-only memory, anchor §2.1)
  store.py       append-only JSONL store + event log (sends record their edit diff)
  translate.py   read path: recall → one flash call → JSON patch, noop-default
  llm.py         thin Anthropic client (translator: haiku; downstream: swappable)
  server.py      FastAPI shell: composer polish / requirement CRUD / streaming chat
  hotkey/        macOS AX capture/write, app profiles, edit tracking, feedback client
web/index.html   control center
tests/           mechanical tests with a fake LLM — no API key needed
```

## Release install

```bash
python -m pip install -U .     # ordinary wheel install; no editable .pth
memtranslator init            # LLM first, then local or API embedding
memtranslator start           # backend + Control Center + macOS menu-bar app
memtranslator start -demo     # same startup, plus 10 idempotent demo rules
```

After the package is published, the first command becomes
`python -m pip install -U memtranslator`. On this Mac, use `python`, which is
Python 3.12; Apple's `python3` is currently Python 3.9 and is too old.

`memtranslator init` imports an existing gitignored project `.env` when run
from this checkout. Runtime configuration, memory data, and optional local
models live under `~/Library/Application Support/MemTranslator`; values
already exported by the launch shell take precedence.
The demo downstream defaults to the configured LLM model; set `MT_DOWNSTREAM`
to an explicit model id when testing a different endpoint.

After the LLM API format, model, endpoint, and API key are configured, `init`
asks whether to use a remote embedding API. Answering **N** downloads the
pinned `multilingual-e5-small` ONNX CPU model (about 252 MB) into the runtime
home. Answering **Y** asks for an OpenAI-compatible embedding model name,
API key, and base URL; leaving the latter two blank reuses the active LLM
connection. Runtime retrieval is served through `embedding.py`; it downloads
nothing unless the user chooses local embedding during `init` or clicks the
WebUI's explicit **Default** embedding action. If either backend is
unavailable, retrieval safely falls back to BM25.

## Development with uv

The repository uses one project environment for the backend, macOS client,
tests, and packaging tools:

```bash
./scripts/dev-sync.sh         # one-time setup; rerun after dependency changes
uv run memtranslator init     # only needed once on this Mac
uv run memtranslator start
```

The setup script keeps the environment payload in `venv/` and exposes the
usual `.venv` path as a symlink. macOS can still reapply `UF_HIDDEN` to an
editable `.pth`, which Python 3.12 then skips. The installed CLI bootstrap
therefore restores the checkout's `src/` path itself instead of relying on
that `.pth`; repeated `uv run memtranslator start` calls remain stable.

For faster Python reloads while changing the backend, run the two processes in
separate terminals:

```bash
# terminal A: backend; Python edits reload automatically
PYTHONPATH=src uv run uvicorn memtranslator.server:app --host 127.0.0.1 --port 8123 --reload

# terminal B: detects the existing backend, then starts the macOS client
uv run memtranslator start --no-open
uv run memtranslator start -demo --no-open
```

Run tests with `PYTHONPATH=src uv run pytest`; direct `python -m` development
commands do not pass through the resilient CLI bootstrap.

An editable uv install reads `web/index.html` directly from the checkout, so
Web UI changes only require refreshing the page. Build a wheel only for a
release candidate:

```bash
uv build
```

Open http://127.0.0.1:8123 — or choose **Open Control Center** from the macOS menu-bar app — to manage memory items with **New**, **Modify**, and recoverable **Delete** actions. Every structured memory displays editable **Work kind** and **Scope** metadata. **Any** and **Global** are explicit checkboxes; Global also selects Any because a global rule applies to every work kind. If a new entry is missing either field, it is queued as a raw user message for Extractor-A instead of being inserted as structured memory. The separate **Allowlist** page manages the native apps and AI websites whose translated inputs may enter Extractor-A; its default rows can be created, modified, or deleted like any custom row. The **中 / EN** switch changes the interface language and remembers the choice locally. The Control Center does not contain a chat surface; use **⌥⌘R** in the focused input of another app to run the translator. Runtime state lives under `~/Library/Application Support/MemTranslator`.

The header's settings button edits the live LLM and embedding connections.
LLM configuration has only two wire formats: **OpenAI-compatible** and native
**Anthropic**; Ark, OpenRouter, and other compatible services differ only by
model, API key, and base URL.
API keys are displayed in the local form and stored only in the application
home's mode-0600 `.env`; saving also refreshes the current process, so a
restart is unnecessary. Remote embedding may inherit the active LLM key and
base URL. Its **Default** button selects the pinned multilingual ONNX CPU
model, downloading it only when the local artifacts are missing.

`memtranslator start -demo` (also `--demo`) seeds ten deterministic rules
covering global/scoped applicability and active/retired/superseded lifecycle
states. The IDs are stable, so repeated demo starts preserve edits and add no
duplicates.

## The closed loop (v0.5)

The desktop client closes the loop without embedding markers in text:

    focused input ──raw──▶ translator ──polished──▶ guarded write-back
          ▲                                             │
          └──────── final feedback ◀── short-lived AX tracker ────────┘

- **Hotkey shell** (`memtranslator start`):
  menu bar ⇄, global ⌥⌘R captures the focused editable text field through
  macOS Accessibility, sends a structured snapshot to the local daemon, and
  writes the result back only if focus and text are still unchanged. A small
  code-drawn network appears only while the translator is rewriting, builds
  node by node beside the focused input, glows on verified write-back, then
  fades away.
- **Adaptive write-back**: native controls try direct AX value replacement;
  Electron apps prefer verified clipboard paste; browsers use paste only.
  The clipboard is preserved and restored. Unsupported or secure fields fail
  closed instead of typing into an uncertain target.
- **Edit feedback**: after translation, the shell watches only that focused
  composer until five minutes of inactivity. This also covers a no-op without
  writing anything back. On submit, the original request enters Extractor-A
  only when the translate transaction started in an allowlisted AI client
  (Codex, Cursor, Claude/Claude Code, ChatGPT, or Windsurf) or an allowlisted
  AI-assistant website (ChatGPT, Claude, Gemini, 豆包, DeepSeek, Kimi, 元宝,
  Perplexity, Poe, Grok, or Copilot). Browser capture stores only the page
  hostname and fails closed when it cannot read one; ordinary apps and web
  pages never enter A. Inside an allowed source there is no keyword or
  rule-based filter: ordinary requests are queued too, while each message is
  limited to a 600-token head/tail view when Extractor-A runs. Enter, clearing,
  focus change, or a mouse click that causes clearing/focus change closes the
  session and submits the latest non-empty text. This still requires a
  translator hotkey transaction; it is not a permanent document-wide text
  logger. An incomplete entry submitted from the memory manager remains
  eligible because that action is explicit user intent, not silent capture.
  The full source list is editable on the Control Center's **Allowlist** page.
  Changes take effect for the next translator transaction and persist in
  `source_allowlist.json` beside the memory store.
- **Permissions**: Accessibility is required to inspect and update the focused
  text control. macOS may also request Input Monitoring for the global hotkey
  and Enter detection. Both permissions are visible and revocable in System
  Settings → Privacy & Security.
- Everything stays on your machine: capture, storage (`data/`), and the
  flash extraction planned for v1.

- `bench/` — the v1 acceptance bench: **overall ≥ 80% ⇔ the first
  user-facing release is good enough** (T translate / L learn / E e2e;
  see `bench/README.md` for the contract and current water line).

- `position_anchor.md` — 项目定位锚点（唯一方向依据）
- `docs/archive.md` — record of the 2026-07 first build (record only; every approach in it deviates from the anchor)
