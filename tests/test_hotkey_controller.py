from dataclasses import replace

from memtranslator.hotkey.controller import DesktopController
from memtranslator.hotkey.models import (InputSnapshot, TextRange,
                                         WriteResult)


def _snapshot(text: str) -> InputSnapshot:
    return InputSnapshot(identity="box", full_text=text,
                         target_range=TextRange(0, len(text)),
                         app_name="Slack", role="AXTextArea")


class Adapter:
    def __init__(self):
        self.snapshot = _snapshot("raw")

    def capture(self):
        return self.snapshot

    def write(self, _snapshot_before, text):
        self.snapshot = _snapshot(text)
        return WriteResult(True, "paste", expected_full_text=text)


class Client:
    def __init__(self):
        self.feedback_events = []

    def translate(self, text, context):
        assert text == "raw" and context["app_name"] == "Slack"
        return {"decision": "apply", "polished": "polished",
                "translate_id": "tr-1", "applied": []}

    def feedback(self, event):
        self.feedback_events.append(event)
        return {"classification": "edited_after_polish"}


def test_controller_runs_write_track_feedback_loop():
    adapter, client = Adapter(), Client()
    progress = []
    controller = DesktopController(
        adapter, client,
        on_progress=lambda state, snapshot: progress.append(
            (state, snapshot.identity)))
    out = controller.polish()
    assert out["status"] == "tracking"
    assert out["write"].strategy == "paste"
    assert progress == [("translating", "box"), ("writing", "box")]
    adapter.snapshot = _snapshot("polished edited")
    observed = controller.observe(key="Enter")
    assert observed["status"] == "feedback_sent"
    assert client.feedback_events[0].final_text == "polished edited"


def test_controller_rejects_stale_write_failure():
    adapter, client = Adapter(), Client()
    adapter.write = lambda snapshot, text: WriteResult(
        False, "none", reason="stale_snapshot")
    out = DesktopController(adapter, client).polish()
    assert out["status"] == "write_failed"


def test_controller_can_use_a_pre_captured_snapshot():
    adapter, client = Adapter(), Client()
    captured = adapter.snapshot
    captures = []

    def capture_after_write():
        captures.append(adapter.snapshot.full_text)
        return adapter.snapshot

    adapter.capture = capture_after_write
    out = DesktopController(adapter, client).polish(snapshot=captured)
    assert out["status"] == "tracking"
    assert captures == ["polished"]


def test_noop_tracks_confirmed_raw_without_writing():
    adapter, client = Adapter(), Client()
    writes = []
    adapter.write = lambda *_args: writes.append(True)
    client.translate = lambda _text, _context: {
        "decision": "noop", "polished": "raw",
        "translate_id": "tr-noop", "applied": [],
    }
    controller = DesktopController(adapter, client)

    out = controller.polish()
    observed = controller.observe(key="Enter")

    assert out["status"] == "noop_tracking"
    assert writes == []
    assert observed["status"] == "feedback_sent"
    assert client.feedback_events[0].translate_id == "tr-noop"
    assert client.feedback_events[0].original == "raw"
    assert client.feedback_events[0].final_text == "raw"
