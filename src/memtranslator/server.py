"""FastAPI shell for the v0 product surface (anchor §2.2):

hotkey → polish in the composer → human edits → send. The downstream agent
only ever sees the text the user confirmed; requirements never enter its
context. Sends are logged with their edit diff (recorded in v0, learned
from in v1).
"""
import json
import hashlib
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from memtranslator import config, llm
from memtranslator.pipeline import Pipeline
from memtranslator.runtime_settings import RuntimeSettings
from memtranslator.scopes import normalize_kind
from memtranslator.signals import attribute_diff, classify_feedback, patch_diff
from memtranslator.source_policy import SourceAllowlist, route_a_source_allowed
from memtranslator.store import EventLog, Store
from memtranslator.translate import translate

DOWNSTREAM_SYSTEM = "You are a helpful assistant."


class RequirementIn(BaseModel):
    text: str
    work_kind: str | list[str] | None = None
    scope_text: str | None = None


class RequirementPatch(BaseModel):
    text: str | None = None
    status: str | None = None
    work_kind: str | list[str] | None = None
    scope_text: str | None = None


class TranslateIn(BaseModel):
    text: str
    context: dict | None = None


class ChatIn(BaseModel):
    messages: list[dict]
    translate_id: str | None = None


class DesktopFeedbackIn(BaseModel):
    translate_id: str
    final_text: str
    trigger: str
    source: str = "macos-accessibility"
    input_context: dict | None = None


class SourceAllowlistIn(BaseModel):
    label: str
    kind: str
    patterns: str | list[str]


class SourceAllowlistPatch(BaseModel):
    label: str | None = None
    kind: str | None = None
    patterns: str | list[str] | None = None


class LLMSettingsIn(BaseModel):
    api_format: str
    model: str
    base_url: str = ""
    api_key: str | None = None


class EmbeddingSettingsIn(BaseModel):
    model: str
    base_url: str = ""
    api_key: str = ""


def create_app(store_path: Path | None = None,
               events_path: Path | None = None,
               allowlist_path: Path | None = None,
               settings_path: Path | None = None) -> FastAPI:
    resolved_store_path = store_path or config.STORE_FILE
    resolved_events_path = events_path or config.EVENTS_FILE
    resolved_allowlist_path = (allowlist_path
                               or resolved_store_path.parent
                               / config.SOURCE_ALLOWLIST_FILE.name)
    resolved_settings_path = (settings_path
                              or (resolved_store_path.parent / ".env"
                                  if store_path is not None
                                  else config.ENV_FILE))
    store = Store(resolved_store_path)
    events = EventLog(resolved_events_path)
    source_allowlist = SourceAllowlist(resolved_allowlist_path)
    runtime_settings = RuntimeSettings(resolved_settings_path)
    pipeline = Pipeline(store)
    app = FastAPI(title="MemTranslator")
    app.state.store = store
    app.state.events = events
    app.state.pipeline = pipeline
    app.state.source_allowlist = source_allowlist
    app.state.runtime_settings = runtime_settings
    translate_counter = {"n": 0}

    def _work_kinds(value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        raw = re.split(r"[,，]", value) if isinstance(value, str) else value
        kinds = [str(item).strip() for item in raw if str(item).strip()]
        return list(dict.fromkeys(kinds))

    def _scope_fields(value: str) -> tuple[dict, str, str]:
        text = " ".join(value.split())
        if text.lower() in {"global", "all", "any", "全局"}:
            return {}, "", "global"
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("scope JSON is invalid") from exc
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("scope JSON must be a non-empty object")
            return parsed, "", "scoped"
        parts = [part.strip() for part in re.split(r"[,，]", text)
                 if part.strip()]
        filters: dict[str, str] = {}
        if parts and all("=" in part or ":" in part for part in parts):
            for part in parts:
                key, separator, item = part.partition("=")
                if not separator:
                    key, separator, item = part.partition(":")
                if not key.strip() or not item.strip():
                    raise ValueError("scope filters must use key=value")
                filters[key.strip()] = item.strip()
            return filters, "", "scoped"
        return {}, text, "scoped"

    def _source_patterns(value: str | list[str]) -> list[str]:
        raw = re.split(r"[,，\n]", value) if isinstance(value, str) else value
        return [str(item).strip() for item in raw if str(item).strip()]

    def _source_event(entry: dict) -> dict:
        return {
            "entry_id": entry["id"],
            "label": entry["label"],
            "source_kind": entry["kind"],
            "patterns": entry["patterns"],
            "is_default": entry["is_default"],
        }

    def _learn_from_feedback(text: str, verdict: dict, now: float) -> bool:
        """The v1 learning loop (design §4/§5): classify → mechanical
        strength → queue → lazy flush. Learning must never break the API —
        an unreachable LLM leaves candidates queued for the next flush."""
        cls = verdict["classification"]
        matched_id = verdict.get("matched_translate_id")
        if not matched_id:
            return False
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
        tr = next((e for e in reversed(events.read_all())
                   if e.get("translate_id") == matched_id
                   and e["kind"] == "translate"), None)
        if tr is None:
            return False

        # Route A learns only the raw text authored before translation. The
        # full polished/final text and polished→final fragments are never A
        # evidence. Human changes remain Route-B feedback for now.
        original = tr.get("original")
        if (isinstance(original, str) and original.strip()
                and route_a_source_allowed(
                    tr.get("context"), source_allowlist.list())):
            pipeline.add_natural([original], now)
        applied = tr.get("applied_ids", [])
        attr = attribute_diff(tr["original"], tr["polished"], text)
        if attr["strength_delta"]:
            store.bump_strength(applied, attr["strength_delta"])
        if cls in ("reverted", "edited_after_polish"):
            # Route B judges the entries this patch used, so it gets their
            # snapshots as recorded at translate time. Older events fall back
            # to the current Store.
            entries = tr.get("applied_entries")
            if not isinstance(entries, list):
                entries = [store.get(i).to_dict() for i in applied
                           if i in store._items]
            pipeline.add_feedback(
                entries, patch_diff(tr["polished"], text), now)
        try:
            pipeline.maybe_flush(now)
        except llm.LLMUnavailable:
            pass          # queue survives; the next submit retries the flush
        return True

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

    @app.get("/api/settings")
    def get_settings():
        return runtime_settings.snapshot()

    @app.put("/api/settings/llm")
    def update_llm_settings(body: LLMSettingsIn):
        try:
            result = runtime_settings.update_llm(
                api_format=body.api_format, model=body.model,
                base_url=body.base_url, api_key=body.api_key)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        events.append("llm_settings_updated", {
            "api_format": result["llm"]["api_format"],
            "model": result["llm"]["model"],
            "base_url": result["llm"]["base_url"],
            "has_api_key": result["llm"]["has_api_key"],
        })
        return result

    @app.put("/api/settings/embedding")
    def update_embedding_settings(body: EmbeddingSettingsIn):
        try:
            result = runtime_settings.update_remote_embedding(
                model=body.model, base_url=body.base_url,
                api_key=body.api_key)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        events.append("embedding_settings_updated", {
            "mode": "remote", "model": result["embedding"]["model"],
            "uses_llm_api_key": result["embedding"]["uses_llm_api_key"],
            "uses_llm_base_url": result["embedding"]["uses_llm_base_url"],
        })
        return result

    @app.post("/api/settings/embedding/default")
    def use_default_embedding():
        from memtranslator.embedding import EmbeddingUnavailable
        try:
            result, downloaded = runtime_settings.use_default_embedding()
        except EmbeddingUnavailable as exc:
            raise HTTPException(502, str(exc))
        events.append("embedding_settings_updated", {
            "mode": "local", "model": result["embedding"]["model"],
            "downloaded": downloaded,
        })
        return {**result, "downloaded": downloaded}

    @app.post("/api/demo/seed")
    def seed_demo():
        from memtranslator.demo import seed_demo_requirements
        result = seed_demo_requirements(store)
        events.append("demo_seeded", result)
        return result

    @app.get("/api/requirements")
    def list_requirements():
        return {"requirements": [r.to_dict() for r in store.list()]}

    @app.get("/api/source-allowlist")
    def list_source_allowlist():
        return {"entries": source_allowlist.list()}

    @app.post("/api/source-allowlist")
    def add_source_allowlist(body: SourceAllowlistIn):
        try:
            entry = source_allowlist.add(
                label=body.label, kind=body.kind,
                patterns=_source_patterns(body.patterns))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        events.append("source_allowlist_added", _source_event(entry))
        return entry

    @app.patch("/api/source-allowlist/{entry_id}")
    def patch_source_allowlist(entry_id: str, body: SourceAllowlistPatch):
        try:
            entry = source_allowlist.update(
                entry_id, label=body.label, kind=body.kind,
                patterns=(_source_patterns(body.patterns)
                          if body.patterns is not None else None))
        except KeyError:
            raise HTTPException(404, "unknown source allowlist entry")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        events.append("source_allowlist_updated", _source_event(entry))
        return entry

    @app.delete("/api/source-allowlist/{entry_id}")
    def delete_source_allowlist(entry_id: str):
        try:
            entry = source_allowlist.delete(entry_id)
        except KeyError:
            raise HTTPException(404, "unknown source allowlist entry")
        events.append("source_allowlist_deleted", _source_event(entry))
        return entry

    @app.post("/api/requirements")
    def add_requirement(body: RequirementIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "requirement text is empty")
        kinds = _work_kinds(body.work_kind)
        scope_text = (body.scope_text or "").strip()
        if not kinds or not scope_text:
            now = time.time()
            pipeline.add_natural([text], now)
            events.append("manual_message_queued", {
                "text": text,
                "provided_work_kind": kinds,
                "provided_scope": scope_text,
                "route": "extractor_a",
            })
            try:
                flushed = pipeline.maybe_flush(now)
            except llm.LLMUnavailable:
                flushed = None
            return {
                "queued": True,
                "route": "extractor_a",
                "pending": pipeline.pending_count("a"),
                "processed": flushed is not None,
            }
        try:
            scope, applies_when, scope_mode = _scope_fields(scope_text)
            if (scope_mode == "global"
                    and "any" not in {normalize_kind(kind) for kind in kinds}):
                raise ValueError("global scope requires work kind any")
            req = store.add(text, kinds=kinds, scope=scope,
                            applies_when=applies_when,
                            scope_mode=scope_mode)
        except ValueError as e:
            raise HTTPException(400, str(e))
        events.append("requirement_added", {
            "id": req.id, "text": req.text, "kinds": req.kinds,
            "scope": req.scope, "applies_when": req.applies_when,
            "scope_mode": req.scope_mode,
        })
        return req.to_dict()

    @app.patch("/api/requirements/{req_id}")
    def patch_requirement(req_id: str, body: RequirementPatch):
        try:
            current = store.get(req_id)
            updates = {"text": body.text, "status": body.status}
            if body.work_kind is not None:
                kinds = _work_kinds(body.work_kind)
                if not kinds:
                    raise ValueError("work kind is empty")
                updates["kinds"] = kinds
            if body.scope_text is not None:
                scope_text = body.scope_text.strip()
                if not scope_text:
                    raise ValueError("scope is empty")
                scope, applies_when, scope_mode = _scope_fields(scope_text)
                updates.update({
                    "scope": scope,
                    "applies_when": applies_when,
                    "scope_mode": scope_mode,
                })
            pending_kinds = updates.get("kinds", current.kinds)
            pending_scope_mode = updates.get("scope_mode", current.scope_mode)
            if (pending_scope_mode == "global"
                    and "any" not in {
                        normalize_kind(kind) for kind in pending_kinds}):
                raise ValueError("global scope requires work kind any")
            req = store.update(req_id, **updates)
        except KeyError:
            raise HTTPException(404, "unknown requirement")
        except ValueError as e:
            raise HTTPException(400, str(e))
        events.append("requirement_updated",
                      {"id": req.id, "text": req.text, "status": req.status,
                       "kinds": req.kinds, "scope": req.scope,
                       "applies_when": req.applies_when,
                       "scope_mode": req.scope_mode})
        return req.to_dict()

    @app.delete("/api/requirements/{req_id}")
    def delete_requirement(req_id: str):
        try:
            req = store.get(req_id)
        except KeyError:
            raise HTTPException(404, "unknown requirement")
        # The store is intentionally append-only. A user deletion therefore
        # persists a retired version: it disappears from active memory
        # immediately while remaining recoverable from the control center.
        if req.status != "retired":
            req = store.update(req_id, status="retired")
            events.append("requirement_deleted", {
                "id": req.id, "text": req.text, "status": req.status,
            })
        return req.to_dict()

    @app.post("/api/translate")
    def translate_endpoint(body: TranslateIn):
        text = body.text.strip()
        if not text:
            raise HTTPException(400, "empty request")
        try:
            result = translate(text, store.list(), context=body.context)
        except llm.LLMUnavailable:
            raise HTTPException(502, "llm_unreachable")
        applied = result.get("applied_entries")
        if not isinstance(applied, list):
            # Compatibility for tests/adapters that still return only ids.
            applied = [store.get(i).to_dict() for i in result["applied_ids"]
                       if i in store._items]
        polished = result.get("polished") or text
        translate_counter["n"] += 1
        translate_id = f"tr-{translate_counter['n']}-{int(len(text))}"
        events.append("translate", {
            "translate_id": translate_id,
            "original": text,
            "decision": result["decision"],
            "polished": polished,
            "applied_ids": result["applied_ids"],
            "applied_entries": applied,
            "parse_error": result["parse_error"],
            "latency_ms": result["latency_ms"],
            "context": body.context or {},
        })
        return {"translate_id": translate_id, "decision": result["decision"],
                "polished": polished, "applied": applied,
                "parse_error": result["parse_error"],
                "latency_ms": result["latency_ms"]}

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
        verdict = classify_feedback(text, translated)
        diffs = patch_diff(translated.get("polished") or "", text)
        events.append("desktop_feedback", {
            "text": text,
            "source": body.source,
            "trigger": body.trigger,
            "input_context": body.input_context or {},
            "classification": verdict["classification"],
            "matched_translate_id": verdict["matched_translate_id"],
            "similarity": verdict["similarity"],
            "diff": diffs,
        })
        learned = _learn_from_feedback(text, verdict, now)
        return {**verdict, "diff": diffs, "learning_applied": learned}

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
            verdict = classify_feedback(sent_text, translated)
            events.append("web_feedback", {
                "text": sent_text,
                "classification": verdict["classification"],
                "matched_translate_id": verdict["matched_translate_id"],
                "similarity": verdict["similarity"],
            })
            _learn_from_feedback(sent_text, verdict, now)

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
