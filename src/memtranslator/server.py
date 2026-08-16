"""FastAPI shell for the v0 product surface (anchor §2.2):

hotkey → polish in the composer → human edits → send. The downstream agent
only ever sees the text the user confirmed; requirements never enter its
context. Sends are logged with their edit diff (recorded in v0, learned
from in v1).
"""
import json
import hashlib
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from memtranslator import config, llm
from memtranslator.consolidate import run_consolidation, should_consolidate
from memtranslator.pipeline import Pipeline
from memtranslator.signals import (attribute_diff, classify_submit,
                                   patch_diff, screen_message)
from memtranslator.store import EventLog, Store
from memtranslator.translate import translate
from memtranslator.vocabulary import (VocabularyStore, apply_vocabulary,
                                      vocabulary_replacements)

DOWNSTREAM_SYSTEM = "You are a helpful assistant."


class RequirementIn(BaseModel):
    text: str


class RequirementPatch(BaseModel):
    text: str | None = None
    status: str | None = None


class TranslateIn(BaseModel):
    text: str
    context: dict | None = None


class ChatIn(BaseModel):
    messages: list[dict]
    translate_id: str | None = None


class SubmitIn(BaseModel):
    text: str
    source: str
    session_id: str | None = None
    cwd: str | None = None


class DesktopFeedbackIn(BaseModel):
    translate_id: str
    final_text: str
    trigger: str
    source: str = "macos-accessibility"
    input_context: dict | None = None


class VocabularyIn(BaseModel):
    term: str
    alias: str = ""


class VocabularyPatch(BaseModel):
    term: str | None = None
    status: str | None = None


def create_app(store_path: Path | None = None,
               events_path: Path | None = None,
               vocab_path: Path | None = None) -> FastAPI:
    resolved_store_path = store_path or config.STORE_FILE
    resolved_events_path = events_path or config.EVENTS_FILE
    resolved_vocab_path = vocab_path or (
        resolved_store_path.parent / "vocabulary.jsonl"
        if store_path is not None else config.VOCAB_FILE)
    store = Store(resolved_store_path)
    events = EventLog(resolved_events_path)
    vocabulary = VocabularyStore(resolved_vocab_path)
    pipeline = Pipeline(store)
    app = FastAPI(title="MemTranslator")
    app.state.store = store
    app.state.events = events
    app.state.pipeline = pipeline
    app.state.vocabulary = vocabulary
    translate_counter = {"n": 0}

    def _learn_from_submit(text: str, verdict: dict, now: float) -> bool:
        """The v1 learning loop (design §4/§5): classify → mechanical
        strength → queue → lazy flush. Learning must never break the API —
        an unreachable LLM leaves candidates queued for the next flush."""
        cls = verdict["classification"]
        matched_id = verdict.get("matched_translate_id")
        if matched_id:
            digest = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
            duplicate = any(
                event.get("kind") == "learning_feedback"
                and event.get("translate_id") == matched_id
                and event.get("text_hash") == digest
                for event in events.read_all())
            if duplicate:
                return False
            events.append("learning_feedback", {
                "translate_id": matched_id,
                "text_hash": digest,
                "classification": cls,
            })
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
                    # Route B judges the entries this patch used, so it gets
                    # their snapshots as recorded at translate time — not a
                    # store index it would have to search.
                    pipeline.add_feedback(
                        [store.get(i).to_dict() for i in applied
                         if i in store._items],
                        patch_diff(tr["polished"], text), now)
        try:
            if pipeline.maybe_flush(now) is not None:
                if should_consolidate(store, pipeline.adds_since_consolidate):
                    run_consolidation(store)
                    pipeline.adds_since_consolidate = 0
        except llm.LLMUnavailable:
            pass          # queue survives; the next submit retries the flush
        return True

    @app.get("/")
    def index():
        return FileResponse(config.WEB_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/demo")
    def demo():
        return FileResponse(config.WEB_DIR / "demo.html",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health():
        return {"ok": True, "models": config.MODELS}

    @app.get("/api/pipeline/state")
    def pipeline_state():
        return {"pending": pipeline.pending_count(),
                "adds_since_consolidate": pipeline.adds_since_consolidate,
                "active_requirements": len(store.active()),
                "active_vocabulary": len(vocabulary.list(
                    include_retired=False))}

    @app.get("/api/vocabulary")
    def list_vocabulary():
        return {"vocabulary": [entry.to_dict()
                               for entry in vocabulary.list()]}

    @app.post("/api/vocabulary")
    def add_vocabulary(body: VocabularyIn):
        try:
            entry, created = vocabulary.upsert(
                body.term, alias=body.alias, source="manual")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        events.append("vocabulary_added", {
            "id": entry.id, "term": entry.term, "alias": entry.alias,
            "created": created, "source": "manual",
        })
        return {**entry.to_dict(), "created": created}

    @app.patch("/api/vocabulary/{entry_id}")
    def patch_vocabulary(entry_id: str, body: VocabularyPatch):
        try:
            return vocabulary.update(entry_id, term=body.term,
                                     status=body.status).to_dict()
        except KeyError:
            raise HTTPException(404, "unknown vocabulary entry")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

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
        normalized, vocabulary_ids = apply_vocabulary(
            text, vocabulary.list(include_retired=False))
        try:
            result = translate(normalized, store.list(), context=body.context)
        except llm.LLMUnavailable:
            if not vocabulary_ids:
                raise HTTPException(502, "llm_unreachable")
            result = {"decision": "noop", "polished": None,
                      "applied_ids": [], "parse_error": False,
                      "latency_ms": 0, "reason": "vocabulary_only"}
        if vocabulary_ids and result["decision"] == "noop":
            result = {**result, "decision": "apply", "polished": normalized,
                      "reason": "vocabulary_only"}
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
            "context": body.context or {},
            "vocabulary_applied": vocabulary_ids,
        })
        applied = [store.get(i).to_dict() for i in result["applied_ids"]]
        vocabulary_applied = [vocabulary.get(entry_id).to_dict()
                              for entry_id in vocabulary_ids]
        return {"translate_id": translate_id, "decision": result["decision"],
                "polished": result["polished"], "applied": applied,
                "vocabulary_applied": vocabulary_applied,
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

    @app.post("/api/desktop/feedback")
    def desktop_feedback(body: DesktopFeedbackIn):
        text = body.final_text.strip()
        if not text:
            raise HTTPException(400, "empty final text")
        translated = next((event for event in reversed(events.read_all())
                           if event.get("kind") == "translate"
                           and event.get("translate_id") == body.translate_id),
                          None)
        if translated is None:
            raise HTTPException(404, "unknown translate_id")
        now = time.time()
        verdict = classify_submit(text, now, [translated])
        diffs = patch_diff(translated.get("polished") or "", text)
        added = []
        if verdict["classification"] == "edited_after_polish":
            bundle_id = (body.input_context or {}).get("app_bundle_id", "")
            for candidate in vocabulary_replacements(
                    translated.get("polished") or "", text):
                entry, created = vocabulary.upsert(
                    candidate["term"], alias=candidate["alias"],
                    source="desktop-edit", app_bundle_id=bundle_id)
                if created:
                    added.append(entry.to_dict())
                    events.append("vocabulary_added", {
                        "id": entry.id, "term": entry.term,
                        "alias": entry.alias, "created": True,
                        "source": "desktop-edit",
                        "translate_id": body.translate_id,
                    })
        events.append("desktop_feedback", {
            "text": text,
            "source": body.source,
            "trigger": body.trigger,
            "input_context": body.input_context or {},
            "classification": verdict["classification"],
            "matched_translate_id": verdict["matched_translate_id"],
            "similarity": verdict["similarity"],
            "diff": diffs,
            "vocabulary_added": [entry["id"] for entry in added],
        })
        learned = _learn_from_submit(text, verdict, now)
        return {**verdict, "diff": diffs, "vocabulary_added": added,
                "learning_applied": learned}

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
            translated = next(
                (e for e in reversed(app.state.events.read_all())
                 if e.get("translate_id") == body.translate_id
                 and e["kind"] == "translate"), None)
            polished = translated.get("polished") if translated else None
            send_event["polished"] = polished
            send_event["edited_after_polish"] = (
                polished is not None and polished != sent_text)
        events.append("send", send_event)
        if body.translate_id and translated is not None:
            now = time.time()
            verdict = classify_submit(sent_text, now, [translated])
            events.append("web_feedback", {
                "text": sent_text,
                "classification": verdict["classification"],
                "matched_translate_id": verdict["matched_translate_id"],
                "similarity": verdict["similarity"],
            })
            if verdict["classification"] == "edited_after_polish":
                for candidate in vocabulary_replacements(
                        translated.get("polished") or "", sent_text):
                    entry, created = vocabulary.upsert(
                        candidate["term"], alias=candidate["alias"],
                        source="web-edit")
                    if created:
                        events.append("vocabulary_added", {
                            "id": entry.id, "term": entry.term,
                            "alias": entry.alias, "created": True,
                            "source": "web-edit",
                            "translate_id": body.translate_id,
                        })
            _learn_from_submit(sent_text, verdict, now)

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
