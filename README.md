# MemTranslator

An open-source translator between you and your agents: it learns how you want tasks done (delivery requirements) and compiles them into the request itself, so downstream agents never read memory. All direction lives in `position_anchor.md`.

**v0** (anchor §7): the product shell — hotkey polish in the composer, human-in-the-loop by default — plus requirement storage and the oracle condition (requirements entered by hand; extraction is v1).

```
src/memtranslator/
  schema.py      Requirement (requirement-only memory, anchor §2.1)
  store.py       append-only JSONL store + event log (sends record their edit diff)
  translate.py   read path: recall → one flash call → JSON patch, noop-default
  vocabulary.py  exact spellings learned from post-polish user corrections
  llm.py         thin Anthropic client (translator: haiku; downstream: swappable)
  server.py      FastAPI shell: composer polish / requirement CRUD / streaming chat
  hotkey/        macOS AX capture/write, app profiles, edit tracking, feedback client
web/index.html   control center
web/demo.html    deterministic interactive desktop demo (no API key or OS writes)
tests/           mechanical tests with a fake LLM — no API key needed
```

## Run

```bash
uv sync --group hotkey
uv run pytest                  # no key needed

uv run uvicorn memtranslator.server:app --port 8123
```

Provider credentials are loaded from the gitignored project `.env`; values
already exported by the launch shell take precedence.
The demo downstream defaults to `ark:$LLM_MODEL`; set `MT_DOWNSTREAM` to an
explicit model id when testing a different provider.

Open http://127.0.0.1:8123 — add a requirement on the right, type a request, hit **⌥⌘R** to polish (the result lands back in the composer, editable), then **Enter** to send. The downstream agent only sees the text you confirmed. Open http://127.0.0.1:8123/demo for a deterministic walkthrough of the desktop loop. Runtime state lives in `data/` (gitignored); delete it to reset.

> On this machine, keep the venv outside the iCloud tree or file eviction
> will randomly break editable installs:
> `export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/memtranslator"` before `uv` calls.

## The closed loop (v0.5)

Two channels join inside the daemon — no markers ever embedded in text:

    hotkey app ──(raw, polished)──▶ daemon ◀──(final text)── agent hook
                            join → accepted / edited / reverted / natural

- **Hotkey shell** (`uv run --group hotkey python -m memtranslator.hotkey`):
  menu bar ⇄, global ⌥⌘R captures the focused editable text field through
  macOS Accessibility, sends a structured snapshot to the local daemon, and
  writes the result back only if focus and text are still unchanged.
- **Adaptive write-back**: native controls try direct AX value replacement;
  Electron apps prefer verified clipboard paste; browsers use paste only.
  The clipboard is preserved and restored. Unsupported or secure fields fail
  closed instead of typing into an uncertain target.
- **Edit feedback**: after a successful write, the shell watches only that
  focused composer for up to 15 seconds. Enter, clearing, focus change, or
  timeout closes the session and submits the latest non-empty text. It does not
  run a permanent document-wide text logger.
- **Vocabulary**: conservative one-token spelling corrections such as
  `Sirius → siriux` are stored in a separate exact-spelling ledger. Delivery
  requirements continue to describe *how work should be done*; vocabulary is
  never compiled into that requirement memory. Confirmed aliases are applied
  locally as a deterministic token-level pre-pass on future requests, before
  the requirement compiler runs.
- **Permissions**: Accessibility is required to inspect and update the focused
  text control. macOS may also request Input Monitoring for the global hotkey
  and Enter detection. Both permissions are visible and revocable in System
  Settings → Privacy & Security.
- **Claude Code hook**: merge `hooks/claude-code/settings-fragment.json`
  into `~/.claude/settings.json`. Fail-open: if the daemon is down the
  prompt passes through untouched. Cursor / Codex hooks: not yet.
- Everything stays on your machine: capture, storage (`data/`), and the
  flash extraction planned for v1.

- `bench/` — the v1 acceptance bench: **overall ≥ 80% ⇔ the first
  user-facing release is good enough** (T translate / L learn / E e2e;
  see `bench/README.md` for the contract and current water line).

- `position_anchor.md` — 项目定位锚点（唯一方向依据）
- `docs/archive.md` — record of the 2026-07 first build (record only; every approach in it deviates from the anchor)
