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
web/index.html   the shell UI
tests/           mechanical tests with a fake LLM — no API key needed
```

## Run

```bash
uv sync
uv run pytest                  # 20 tests, no key needed

source ~/.zshrc                # ANTHROPIC_API_KEY
uv run uvicorn memtranslator.server:app --port 8123
```

Open http://127.0.0.1:8123 — add a requirement on the right, type a request, hit **⌘E** to polish (the result lands back in the composer, editable), then **Enter** to send. The downstream agent only sees the text you confirmed. Runtime state lives in `data/` (gitignored); delete it to reset.

> On this machine, keep the venv outside the iCloud tree or file eviction
> will randomly break editable installs:
> `export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/memtranslator"` before `uv` calls.

## The closed loop (v0.5)

Two channels join inside the daemon — no markers ever embedded in text:

    hotkey app ──(raw, polished)──▶ daemon ◀──(final text)── agent hook
                            join → accepted / edited / reverted / natural

- **Hotkey shell** (`uv run --group hotkey python -m memtranslator.hotkey`):
  menu bar ⇄, global ⌥⌘E polishes the focused text field via Accessibility
  (grant permission on first run). AX write-back with a clipboard fallback.
- **Claude Code hook**: merge `hooks/claude-code/settings-fragment.json`
  into `~/.claude/settings.json`. Fail-open: if the daemon is down the
  prompt passes through untouched. Cursor / Codex hooks: not yet.
- Everything stays on your machine: capture, storage (`data/`), and the
  flash extraction planned for v1.

- `position_anchor.md` — 项目定位锚点（唯一方向依据）
- `docs/archive.md` — record of the 2026-07 first build (record only; every approach in it deviates from the anchor)
