"""FastAPI shell for the v0 product surface (anchor §2.2):

hotkey → polish in the composer → human edits → send. The downstream agent
only ever sees the text the user confirmed; requirements never enter its
context. Sends are logged with their edit diff (recorded in v0, learned
from in v1).
"""
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from memtranslator import config, llm
from memtranslator.consolidate import run_consolidation, should_consolidate
from memtranslator.pipeline import Pipeline
from memtranslator.signals import attribute_diff, classify_submit, screen_message
from memtranslator.store import EventLog, Store
from memtranslator.translate import translate

DOWNSTREAM_SYSTEM = "You are a helpful assistant."


class RequirementIn(BaseModel):
    text: str


class RequirementPatch(BaseModel):
    text: str | None = None
    status: str | None = None


class TranslateIn(BaseModel):
    text: str


class ChatIn(BaseModel):
    messages: list[dict]
    translate_id: str | None = None


class SubmitIn(BaseModel):
    text: str
    source: str
    session_id: str | None = None
    cwd: str | None = None


def create_app(store_path: Path | None = None,
               events_path: Path | None = None) -> FastAPI:
    store = Store(store_path or config.STORE_FILE)
    events = EventLog(events_path or config.EVENTS_FILE)
    pipeline = Pipeline(store)
    app = FastAPI(title="MemTranslator")
    app.state.store = store
    app.state.events = events
    app.state.pipeline = pipeline
    translate_counter = {"n": 0}

    def _learn_from_submit(text: str, verdict: dict, now: float) -> None:
        """The v1 learning loop (design §4/§5): classify → mechanical
        strength → queue → lazy flush. Learning must never break the API —
        an unreachable LLM leaves candidates queued for the next flush."""
        cls = verdict["classification"]
        if cls == "natural":
            active = store.active()
            keys = [r.key for r in active if r.key]
            pipeline.add_natural(
                screen_message(text, existing_keys=keys,
                               existing_texts=[r.text for r in active]), now)
        else:
            tr = next((e for e in reversed(events.read_all())
                       if e.get("translate_id") == verdict["matched_translate_id"]
                       and e["kind"] == "translate"), None)
            if tr:
                applied = tr.get("applied_ids", [])
                attr = attribute_diff(tr["original"], tr["polished"], text)
                if attr["strength_delta"]:
                    store.bump_strength(applied, attr["strength_delta"])
                if cls in ("reverted", "edited_after_polish"):
                    pipeline.add_diff({
                        "raw": tr["original"], "polished": tr["polished"],
                        "final": text,
                        "applied": [store.get(i).text for i in applied
                                    if i in store._items],
                        "survival": attr["injection_survival"]}, now)
        try:
            if pipeline.maybe_flush(now) is not None:
                if should_consolidate(store, pipeline.adds_since_consolidate):
                    run_consolidation(store)
                    pipeline.adds_since_consolidate = 0
        except llm.LLMUnavailable:
            pass          # queue survives; the next submit retries the flush

    @app.get("/")
    def index():
        return FileResponse(config.WEB_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health():
        return {"ok": True, "models": config.MODELS}

    @app.get("/api/pipeline/state")
    def pipeline_state():
        return {"pending": pipeline.pending_count(),
                "adds_since_consolidate": pipeline.adds_since_consolidate,
                "active_requirements": len(store.active())}

    @app.get("/api/requirements")
    def list_requirements():
        return {"requirements": [r.to_dict() for r in store.list()]}

    @app.post("/api/requirements")
    def add_requirement(body: RequirementIn):
        try:
            req = store.add(body.text)
        except ValueError as e:
            raise HTTPException(400, str(e))
        events.append("requirement_added", {"id": req.id, "text": req.text})
        return req.to_dict()

    @app.patch("/api/requirements/{req_id}")
    def patch_requirement(req_id: str, body: RequirementPatch):
        try:
            req = store.update(req_id, text=body.text, status=body.status)
        except KeyError:
            raise HTTPException(404, "unknown requirement")
        except ValueError as e:
            raise HTTPException(400, str(e))
        events.append("requirement_updated",
                      {"id": req.id, "text": req.text, "status": req.status})
        return req.to_dict()

    @app.post("/api/translate")
    def translate_endpoint(body: TranslateIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "empty request")
        try:
            result = translate(text, store.list())
        except llm.LLMUnavailable:
            raise HTTPException(502, "llm_unreachable")
        translate_counter["n"] += 1
        translate_id = f"tr-{translate_counter['n']}-{int(len(text))}"
        events.append("translate", {
            "translate_id": translate_id,
            "original": text,
            "decision": result["decision"],
            "polished": result["polished"],
            "applied_ids": result["applied_ids"],
            "parse_error": result["parse_error"],
            "latency_ms": result["latency_ms"],
        })
        applied = [store.get(i).to_dict() for i in result["applied_ids"]]
        return {"translate_id": translate_id, "decision": result["decision"],
                "polished": result["polished"], "applied": applied,
                "parse_error": result["parse_error"],
                "latency_ms": result["latency_ms"]}

    @app.post("/api/events/submit")
    def submit_event(body: SubmitIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "empty text")
        now = time.time()
        translates = [e for e in events.read_all() if e["kind"] == "translate"]
        verdict = classify_submit(text, now, translates)
        events.append("submit", {
            "text": text, "source": body.source,
            "session_id": body.session_id, "cwd": body.cwd,
            "classification": verdict["classification"],
            "matched_translate_id": verdict["matched_translate_id"],
            "similarity": verdict["similarity"],
        })
        _learn_from_submit(text, verdict, now)
        return verdict

    @app.get("/api/events")
    def list_events(limit: int = 50):
        return {"events": list(reversed(events.read_all()))[:limit]}

    @app.post("/api/chat")
    def chat(body: ChatIn):
        if not body.messages or body.messages[-1].get("role") != "user":
            raise HTTPException(400, "last message must be from the user")
        sent_text = body.messages[-1]["content"]

        # Send event: link back to the translate that produced the composer
        # text and record whether the human edited it (v1's learning signal).
        send_event = {"text": sent_text, "translate_id": body.translate_id}
        if body.translate_id:
            polished = next(
                (e.get("polished") for e in reversed(app.state.events.read_all())
                 if e.get("translate_id") == body.translate_id
                 and e["kind"] == "translate"), None)
            send_event["polished"] = polished
            send_event["edited_after_polish"] = (
                polished is not None and polished != sent_text)
        events.append("send", send_event)

        def sse():
            try:
                for chunk in llm.stream_text(config.MODELS["downstream"],
                                             DOWNSTREAM_SYSTEM, body.messages):
                    yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
                yield "data: {\"done\": true}\n\n"
            except llm.LLMUnavailable:
                yield "data: {\"error\": \"llm_unreachable\"}\n\n"
            except Exception as e:  # surface errors to the UI, never hang
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    return app


app = create_app()
