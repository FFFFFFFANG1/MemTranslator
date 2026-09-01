"""Pending Write provenance consumed only by an explicit Learn action."""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from memtranslator.hotkey.models import FeedbackEvent, InputSnapshot


@dataclass(frozen=True)
class LearnPlan:
    """Immutable attribution captured before Learn forwards Enter.

    A plan for another composer has no generation and leaves the pending Write
    untouched.  A matching plan must be committed after Enter is forwarded;
    its generation prevents an old asynchronous action from consuming a newer
    Write on the same composer.
    """

    generation: int | None = None
    translate_id: str | None = None
    feedback: FeedbackEvent | None = None
    stale: bool = False


@dataclass(frozen=True)
class _PendingWrite:
    generation: int
    first_translate_id: str
    latest_translate_id: str
    latest_original: str
    latest_written: str
    feedback_deadline: float


class PendingWrites:
    """Keep independent composer-bound Write provenance without polling."""

    def __init__(self, feedback_timeout_s: float = 5 * 60):
        self.feedback_timeout_s = feedback_timeout_s
        self._lock = threading.Lock()
        self._generation = 0
        self._states: dict[str, _PendingWrite] = {}

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._states)

    def matches(self, snapshot: InputSnapshot) -> bool:
        with self._lock:
            return snapshot.identity in self._states

    def start(self, snapshot: InputSnapshot, *, translate_id: str,
              original: str, written: str,
              now: float | None = None) -> int:
        at = time.monotonic() if now is None else now
        with self._lock:
            current = self._states.get(snapshot.identity)
            first_translate_id = (
                current.first_translate_id
                if current is not None
                else translate_id
            )
            self._generation += 1
            self._states[snapshot.identity] = _PendingWrite(
                generation=self._generation,
                first_translate_id=first_translate_id,
                latest_translate_id=translate_id,
                latest_original=original,
                latest_written=written,
                feedback_deadline=at + self.feedback_timeout_s,
            )
            return self._generation

    def plan_learn(self, snapshot: InputSnapshot, *,
                   now: float | None = None) -> LearnPlan:
        at = time.monotonic() if now is None else now
        with self._lock:
            state = self._states.get(snapshot.identity)
            if state is None:
                return LearnPlan()
            if at >= state.feedback_deadline:
                if snapshot.full_text != state.latest_written:
                    return LearnPlan(stale=True)
                return LearnPlan(
                    generation=state.generation,
                    translate_id=state.first_translate_id,
                )
            return LearnPlan(
                generation=state.generation,
                translate_id=state.first_translate_id,
                feedback=FeedbackEvent(
                    translate_id=state.latest_translate_id,
                    original=state.latest_original,
                    polished=state.latest_written,
                    final_text=snapshot.full_text,
                    trigger="learn_hotkey",
                    input_context=snapshot.context(),
                ),
            )

    def commit(self, plan: LearnPlan) -> bool:
        if plan.generation is None:
            return False
        with self._lock:
            identity = next((identity for identity, state in self._states.items()
                             if state.generation == plan.generation), None)
            if identity is None:
                return False
            del self._states[identity]
            return True

    def dismiss(self, snapshot: InputSnapshot) -> bool:
        """Clear only when an event belongs to the pending Write composer."""
        with self._lock:
            return self._states.pop(snapshot.identity, None) is not None

    def cancel(self) -> None:
        with self._lock:
            self._states.clear()
