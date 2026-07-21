# MemTranslator prototype

Working implementation of `docs/memory-design.md`: requirement-only memory with the ≤2-LLM-call write path (extract → batch consolidate), the zero-LLM read path, and a typeless-style demo where the polished input lands back in the composer for the user to edit before sending.

```
src/memtranslator/
  schema.py       MemoryEntry / Candidate / ConsolidationOp (design §2)
  store.py        append-only JSONL store, state machine, quarantine, recall
  extract.py      write path Call 1 (verbatim-quote validation)
  consolidate.py  write path Call 2 (batch ops ADD/REINFORCE/SUPERSEDE/DROP)
  translate.py    read path + request-segment patch (content reattached mechanically)
  pipeline.py     orchestration
demo/             FastAPI + single-page chat demo
tests/            mechanical-layer tests (FakeLLM) + live-API e2e smoke
```

## Run

```bash
uv sync
uv run pytest                # 29 mechanical tests, no API key needed
source ~/.zshrc && uv run pytest   # + live e2e smoke (ANTHROPIC_API_KEY)

# demo (http://127.0.0.1:8123): translator+write path on haiku, downstream on sonnet
source ~/.zshrc && PYTHONPATH=src uv run uvicorn demo.app:app --port 8123
```

Demo flow: chat normally → correct the assistant ("我不是要总结…") → **End session** runs the write path and the extracted requirement appears in the right panel → next request, hit **Translate** and the polished request lands in the composer, editable, with applied-memory chips and a restore link. Demo state persists in `demo/state/` (gitignored) — delete it to reset.
