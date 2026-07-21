"""Typeless-style demo of the memory-grounded user translator.

Flow per message:
  1. POST /translate — the translator compiles applicable requirement memories
     into the request; the polished text is returned to the composer where the
     user can EDIT it freely (that is the typeless-style loop: model output
     lands back in the input box, the user stays in control).
  2. POST /send — whatever text the user confirmed goes to the downstream
     agent, which never sees the memory store.
  3. POST /end_session — runs the ≤2-call write path over this session's
     transcript and reports extracted/consolidated ops.

Run:  uv run uvicorn demo.app:app --port 8123  (needs ANTHROPIC_API_KEY)
State lives in demo/state/ (gitignored).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from memtranslator import AnthropicLLM, MemoryStore, run_translate, run_write_path
from memtranslator.llm import DOWNSTREAM_MODEL
from memtranslator.schema import now_iso

STATE_DIR = Path(__file__).parent / "state"
app = FastAPI(title="MemTranslator demo")

store = MemoryStore(STATE_DIR / "memory.jsonl")
flash = AnthropicLLM()  # write path + translator
downstream = AnthropicLLM(model=DOWNSTREAM_MODEL)

transcript: list[dict] = []  # this session's turns, write-path input at session end
session_id = f"demo-{now_iso()}"


class TranslateReq(BaseModel):
    request: str
    content: str = ""


class SendReq(BaseModel):
    text: str            # what the user actually confirmed in the composer
    original: str = ""   # pre-edit original, kept for the transcript


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/translate")
def translate(req: TranslateReq):
    t = run_translate(flash, req.request, store, content=req.content)
    return {
        "noop": t.noop,
        "polished_request": t.polished_request,
        "polished_input": t.polished_input,
        "applied": [{"mid": e.mid, "requirement": e.requirement} for e in t.applied],
        "rationale": t.rationale,
    }


@app.post("/send")
def send(req: SendReq):
    transcript.append({"role": "user", "text": req.text, "original": req.original})
    # Sonnet 5 runs adaptive thinking by default; leave headroom so the
    # text answer isn't squeezed out by thinking tokens (max_tokens caps both).
    reply = downstream.complete(
        system="You are a helpful assistant.", user=req.text, max_tokens=8000)
    transcript.append({"role": "assistant", "text": reply})
    return {"reply": reply}


@app.post("/end_session")
def end_session():
    global transcript, session_id
    if not transcript:
        return {"ops": [], "note": "empty session"}
    lines = []
    for i, turn in enumerate(t for t in transcript):
        # Write path sees what the user TYPED (post-edit text), the honest signal.
        lines.append(f"{turn['role'].upper()} (turn {i}): {turn['text']}")
    applied = run_write_path(flash, "\n".join(lines), store, session_id=session_id)
    result = [{"op": op.op, "target": op.target_mid, "requirement": cand.requirement,
               "signal": cand.signal, "quote": cand.quote} for cand, op in applied]
    transcript = []
    session_id = f"demo-{now_iso()}"
    return {"ops": result}


@app.get("/memories")
def memories():
    return {"entries": [
        {"mid": e.mid, "requirement": e.requirement, "status": e.status,
         "strength": e.strength, "scope": e.scope.condition, "polarity": e.polarity,
         "quotes": [p.quote for p in e.provenance], "last_applied_at": e.last_applied_at}
        for e in sorted(store.all(), key=lambda e: e.created_at, reverse=True)
    ]}


if __name__ == "__main__":
    import uvicorn

    assert "ANTHROPIC_API_KEY" in os.environ, "source your shell profile first"
    uvicorn.run(app, host="127.0.0.1", port=8123)
