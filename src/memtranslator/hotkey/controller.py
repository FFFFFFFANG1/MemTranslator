"""Orchestrate explicit Write and Learn actions for the macOS client."""
from __future__ import annotations

from dataclasses import replace
import threading
import uuid

from memtranslator.config import SOURCE_ALLOWLIST_FILE
from memtranslator.hotkey.models import LearnEvent, TextRange
from memtranslator.hotkey.profiles import resolve_profile
from memtranslator.hotkey.session import PendingWrites
from memtranslator.source_policy import SourceAllowlist, route_a_source_allowed


class DesktopController:
    """Deep interface for the desktop Write/Learn workflow.

    Write may create a pending session but never learns. Learn forwards Enter
    and is the only interface that creates Extractor A or B events. Ordinary
    Enter and click-to-send can only dismiss a matching pending Write.
    """

    def __init__(self, adapter, client,
                 pending_writes: PendingWrites | None = None,
                 on_progress=None, source_entries=None):
        self.adapter = adapter
        self.client = client
        self.pending_writes = pending_writes or PendingWrites()
        self.on_progress = on_progress
        self._lock = threading.Lock()
        self._source_entries = source_entries or (
            lambda: SourceAllowlist(SOURCE_ALLOWLIST_FILE).list())

    @property
    def has_pending_write(self) -> bool:
        return self.pending_writes.active

    def shortcut_allowed(self, snapshot) -> bool:
        if (snapshot is None or snapshot.secure or not snapshot.editable
                or snapshot.role not in {"AXTextArea", "AXTextField", "AXComboBox"}
                or not resolve_profile(snapshot).enabled):
            return False
        try:
            return route_a_source_allowed(snapshot.context(), self._source_entries())
        except (OSError, ValueError):
            return False

    def _progress(self, state: str, snapshot=None) -> None:
        if self.on_progress is not None:
            self.on_progress(state, snapshot)

    def write(self, snapshot=None) -> dict:
        """Apply remembered preferences and start a pending Write session."""
        with self._lock:
            snapshot = snapshot or self.adapter.capture()
            if snapshot is None or not snapshot.target_text.strip():
                return {"status": "empty"}
            if snapshot.secure or not snapshot.editable:
                return {"status": "unsupported"}
            self._progress("translating", snapshot)

            def apply_ready(written: str) -> tuple[object, object | None]:
                self._progress("writing", snapshot)
                write_result = self.adapter.write(snapshot, written)
                if not write_result.ok:
                    return write_result, None
                captured = self.adapter.capture()
                if captured is None:
                    # adapter.write already verified the same composer and
                    # exact value. Preserve provenance through a transient AX
                    # read failure.
                    expected = (write_result.expected_full_text
                                or snapshot.prefix + written + snapshot.suffix)
                    captured = replace(
                        snapshot,
                        full_text=expected,
                        target_range=TextRange(0, len(expected)),
                    )
                return write_result, captured

            early: dict = {}

            def on_ready(event: dict) -> None:
                if event.get("decision") != "apply" or early:
                    return
                early["written"] = event["polished"]
                early["write"], early["snapshot"] = apply_ready(
                    event["polished"])

            try:
                stream = getattr(self.client, "translate_stream", None)
                if (callable(stream)
                        and getattr(self.client, "streaming_enabled", True)):
                    translated = stream(
                        snapshot.target_text, snapshot.context(), on_ready)
                else:
                    translated = self.client.translate(
                        snapshot.target_text, snapshot.context())
            except Exception:
                return {"status": "daemon_down"}

            written = translated.get("polished") or snapshot.target_text
            if translated.get("decision") != "apply":
                self.pending_writes.start(
                    snapshot,
                    translate_id=translated["translate_id"],
                    original=snapshot.target_text,
                    written=written,
                )
                return {
                    "status": "write_noop",
                    "translate": translated,
                    "snapshot": snapshot,
                }

            if early:
                result = early["write"]
                post_write = early["snapshot"]
                written = early["written"]
            else:
                result, post_write = apply_ready(written)
            if not result.ok:
                return {"status": "write_failed", "write": result}
            self.pending_writes.start(
                post_write,
                translate_id=translated["translate_id"],
                original=snapshot.target_text,
                written=written,
            )
            return {
                "status": "written",
                "translate": translated,
                "write": result,
                "snapshot": post_write,
            }

    def dismiss(self, snapshot) -> bool:
        """End a matching pending Write without learning."""
        return bool(snapshot and self.pending_writes.dismiss(snapshot))

    def matches_pending(self, snapshot) -> bool:
        return bool(snapshot and self.pending_writes.matches(snapshot))

    def dismiss_if_empty(self, snapshot) -> bool:
        """Treat a post-click empty composer as a send/discard seam."""
        return bool(
            snapshot is not None
            and not snapshot.full_text.strip()
            and self.pending_writes.dismiss(snapshot)
        )

    def prepare_learn(self, snapshot) -> dict:
        """Forward Enter once and create the only desktop learning event."""
        with self._lock:
            if not self.shortcut_allowed(snapshot):
                return {"status": "unsupported"}
            if not snapshot.full_text.strip():
                return {"status": "empty"}

            plan = self.pending_writes.plan_learn(snapshot)
            if plan.stale:
                return {"status": "unverified_origin"}
            if not self.adapter.send_enter(snapshot):
                return {"status": "send_failed"}
            if plan.generation is not None and not self.pending_writes.commit(plan):
                # Enter was forwarded, but a newer Write replaced the plan.
                # Fail closed instead of learning with stale attribution.
                return {"status": "sent_unlearned"}

            return {
                "status": "learn_ready",
                "event": LearnEvent(
                    learn_id=f"learn-{uuid.uuid4().hex}",
                    text=snapshot.full_text,
                    input_context=snapshot.context(),
                    translate_id=plan.translate_id,
                    feedback=plan.feedback,
                ),
            }

    def commit_learn(self, event: LearnEvent) -> dict:
        """Persist a Learn event; retrying never forwards Enter again."""
        try:
            response = self.client.learn(event)
            result = {"status": "learned", "response": response}
        except Exception:
            result = {"status": "learn_failed"}
        if event.feedback is not None:
            result["feedback"] = self._send_feedback(event.feedback)
        return result

    def _send_feedback(self, event) -> dict:
        try:
            response = self.client.feedback(event)
            out = {
                "status": "feedback_sent",
                "event": event,
                "response": response,
            }
        except Exception:
            out = {"status": "feedback_failed", "event": event}
        return out
