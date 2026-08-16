"""Testable orchestration between Accessibility, daemon, and edit tracker."""
from __future__ import annotations

import threading

from memtranslator.hotkey.tracker import EditTracker


class DesktopController:
    def __init__(self, adapter, client, tracker: EditTracker | None = None,
                 on_feedback=None, on_progress=None):
        self.adapter = adapter
        self.client = client
        self.tracker = tracker or EditTracker()
        self.on_feedback = on_feedback
        self.on_progress = on_progress
        self._lock = threading.Lock()

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
                return {"status": "noop", "translate": translated}
            self._progress("writing", snapshot)
            result = self.adapter.write(snapshot, translated["polished"])
            if not result.ok:
                return {"status": "write_failed", "write": result}
            post_write = self.adapter.capture()
            if post_write is None:
                return {"status": "write_failed", "write": result}
            self.tracker.start(
                post_write,
                translate_id=translated["translate_id"],
                original=snapshot.target_text,
                polished=translated["polished"],
            )
            return {"status": "tracking", "translate": translated,
                    "write": result, "snapshot": post_write}

    def observe(self, *, key: str = "") -> dict | None:
        if not self.tracker.active:
            return None
        snapshot = self.adapter.capture()
        event = self.tracker.observe(snapshot, key=key)
        if event is None:
            return None
        try:
            response = self.client.feedback(event)
            out = {"status": "feedback_sent", "event": event,
                   "response": response}
        except Exception:
            out = {"status": "feedback_failed", "event": event}
        if self.on_feedback is not None:
            self.on_feedback(out)
        return out
