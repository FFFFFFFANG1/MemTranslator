"""Short-lived edit tracker inspired by Typeless's desktop client."""
from __future__ import annotations

import threading
import time

from memtranslator.hotkey.models import FeedbackEvent, InputSnapshot


class EditTracker:
    def __init__(self, timeout_s: float = 5 * 60):
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._state: dict | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._state is not None

    def start(self, snapshot: InputSnapshot, *, translate_id: str,
              original: str, polished: str, now: float | None = None) -> None:
        at = time.monotonic() if now is None else now
        with self._lock:
            self._state = {
                "identity": snapshot.identity,
                "snapshot": snapshot,
                "latest_nonempty": snapshot,
                "translate_id": translate_id,
                "original": original,
                "polished": polished,
                "deadline": at + self.timeout_s,
            }

    def cancel(self) -> None:
        with self._lock:
            self._state = None

    def matches(self, snapshot: InputSnapshot) -> bool:
        with self._lock:
            return (self._state is not None
                    and self._state["identity"] == snapshot.identity)

    def observe(self, snapshot: InputSnapshot | None, *, key: str = "",
                now: float | None = None) -> FeedbackEvent | None:
        at = time.monotonic() if now is None else now
        with self._lock:
            state = self._state
            if state is None:
                return None
            if at >= state["deadline"]:
                # Expiry is cleanup, not evidence that the rewritten draft
                # was sent.  Fail closed instead of caching feedback.
                self._state = None
                return None
            if snapshot is None or snapshot.identity != state["identity"]:
                # The user may temporarily work in an editor, terminal, or
                # another field.  Keep this composer parked; Enter elsewhere
                # must not finish or cache its feedback.
                return None
            if snapshot.full_text.strip():
                if snapshot.full_text != state["snapshot"].full_text:
                    state["deadline"] = at + self.timeout_s
                state["snapshot"] = snapshot
                state["latest_nonempty"] = snapshot
            else:
                # A clear may be a send-button transition, deletion, or UI
                # recreation.  Until those cases are distinguishable, do not
                # infer a send or cache feedback from it.
                self._state = None
                return None
            if key == "Enter":
                return self._finish_locked("enter")
            return None

    def _finish_locked(self, trigger: str) -> FeedbackEvent:
        state = self._state
        assert state is not None
        latest: InputSnapshot = state["latest_nonempty"]
        event = FeedbackEvent(
            translate_id=state["translate_id"],
            original=state["original"],
            polished=state["polished"],
            final_text=latest.full_text,
            trigger=trigger,
            input_context=latest.context(),
        )
        self._state = None
        return event
