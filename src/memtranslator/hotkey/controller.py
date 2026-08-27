"""Testable orchestration between Accessibility, daemon, and edit tracker."""
from __future__ import annotations

import threading
import uuid

from memtranslator.config import SOURCE_ALLOWLIST_FILE
from memtranslator.hotkey.models import CaptureEvent, WriteResult
from memtranslator.hotkey.profiles import resolve_profile
from memtranslator.hotkey.tracker import EditTracker
from memtranslator.source_policy import SourceAllowlist, route_a_source_allowed


class DesktopController:
    def __init__(self, adapter, client, tracker: EditTracker | None = None,
                 on_feedback=None, on_progress=None, source_entries=None):
        self.adapter = adapter
        self.client = client
        self.tracker = tracker or EditTracker()
        self.on_feedback = on_feedback
        self.on_progress = on_progress
        self._lock = threading.Lock()
        self._source_entries = source_entries or (
            lambda: SourceAllowlist(SOURCE_ALLOWLIST_FILE).list())
        # Keep the first raw request across repeated rewrites. A finished
        # feedback session can still identify an unchanged, unsent draft.
        self._origins: dict[str, tuple[str, str]] = {}

    @property
    def has_pending_draft(self) -> bool:
        return self.tracker.active or bool(self._origins)

    def shortcut_allowed(self, snapshot) -> bool:
        if (snapshot is None or snapshot.secure or not snapshot.editable
                or snapshot.role not in {"AXTextArea", "AXTextField", "AXComboBox"}
                or not resolve_profile(snapshot).enabled):
            return False
        try:
            return route_a_source_allowed(snapshot.context(), self._source_entries())
        except (OSError, ValueError):
            return False

    def _remember_origin(self, snapshot, translate_id: str) -> None:
        first_id = self._origins.get(snapshot.identity, (translate_id, ""))[0]
        self._origins[snapshot.identity] = (first_id, snapshot.full_text)

    def _progress(self, state: str, snapshot=None) -> None:
        if self.on_progress is not None:
            self.on_progress(state, snapshot)

    def polish(self, snapshot=None) -> dict:
        with self._lock:
            snapshot = snapshot or self.adapter.capture()
            if snapshot is None or not snapshot.target_text.strip():
                return {"status": "empty"}
            if snapshot.secure or not snapshot.editable:
                return {"status": "unsupported"}
            self._progress("translating", snapshot)
            try:
                translated = self.client.translate(snapshot.target_text,
                                                   snapshot.context())
            except Exception:
                return {"status": "daemon_down"}
            if translated.get("decision") != "apply":
                # Keep attribution for explicit capture and edit feedback,
                # but ordinary sends no longer queue the raw text in Route A.
                self._remember_origin(snapshot, translated["translate_id"])
                self.tracker.start(
                    snapshot,
                    translate_id=translated["translate_id"],
                    original=snapshot.target_text,
                    polished=translated.get("polished")
                    or snapshot.target_text,
                )
                return {"status": "noop_tracking", "translate": translated,
                        "snapshot": snapshot}
            self._progress("writing", snapshot)
            result = self.adapter.write(snapshot, translated["polished"])
            if not result.ok:
                return {"status": "write_failed", "write": result}
            post_write = self.adapter.capture()
            if post_write is None:
                return {
                    "status": "write_failed",
                    "write": WriteResult(
                        False, result.strategy,
                        reason="post_write_capture_failed"),
                }
            self.tracker.start(
                post_write,
                translate_id=translated["translate_id"],
                original=snapshot.target_text,
                polished=translated["polished"],
            )
            self._remember_origin(post_write, translated["translate_id"])
            return {"status": "tracking", "translate": translated,
                    "write": result, "snapshot": post_write}

    def observe(self, *, key: str = "") -> dict | None:
        with self._lock:
            if not self.has_pending_draft:
                return None
            snapshot = self.adapter.capture()
            if snapshot is not None and snapshot.identity in self._origins:
                if not snapshot.full_text.strip() or key == "Enter":
                    self._origins.pop(snapshot.identity, None)
                elif self.tracker.matches(snapshot):
                    self._remember_origin(snapshot, "")
            event = self.tracker.observe(snapshot, key=key)
            if key == "Enter" and event is not None:
                self._origins.pop(event.input_context.get("identity", ""), None)
        if event is None:
            return None
        return self._send_feedback(event)

    def _send_feedback(self, event, *, notify: bool = True) -> dict:
        try:
            response = self.client.feedback(event)
            out = {"status": "feedback_sent", "event": event,
                   "response": response}
        except Exception:
            out = {"status": "feedback_failed", "event": event}
        if notify and self.on_feedback is not None:
            self.on_feedback(out)
        return out

    def prepare_send(self, snapshot) -> dict:
        """Forward Enter once, before any daemon/LLM work, with a stale guard."""
        with self._lock:
            if not self.shortcut_allowed(snapshot):
                return {"status": "unsupported"}
            if not snapshot.full_text.strip():
                return {"status": "empty"}
            origin = self._origins.get(snapshot.identity)
            if (origin is not None and origin[1] != snapshot.full_text
                    and not self.tracker.matches(snapshot)):
                # After tracking expired, changed text could be a different
                # message. Do not attribute it to an old request or learn our
                # own generated text as a fresh human preference.
                return {"status": "unverified_origin"}
            if not self.adapter.send_enter(snapshot):
                return {"status": "send_failed"}
            feedback = (self.tracker.observe(snapshot, key="Enter")
                        if self.tracker.matches(snapshot) else None)
            self._origins.pop(snapshot.identity, None)
            return {"status": "sent", "event": CaptureEvent(
                capture_id=f"cap-{uuid.uuid4().hex}",
                text=snapshot.full_text, input_context=snapshot.context(),
                translate_id=origin[0] if origin else None,
                feedback=feedback,
            )}

    def save_capture(self, event: CaptureEvent) -> dict:
        """May run in a worker; retrying this event never re-sends Enter."""
        try:
            response = self.client.capture(event)
            result = {"status": "captured", "response": response}
        except Exception:
            result = {"status": "capture_failed"}
        if event.feedback is not None:
            result["feedback"] = self._send_feedback(event.feedback, notify=False)
        return result
