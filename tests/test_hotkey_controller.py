from dataclasses import replace
import time

import pytest

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
        self.sent = []

    def capture(self):
        return self.snapshot

    def write(self, _snapshot_before, text):
        self.snapshot = _snapshot(text)
        return WriteResult(True, "paste", expected_full_text=text)

    def send_enter(self, snapshot):
        self.sent.append(snapshot.full_text)
        self.snapshot = _snapshot("")
        return True


class Client:
    def __init__(self):
        self.feedback_events = []
        self.capture_events = []

    def translate(self, text, context):
        assert text == "raw" and context["app_name"] == "Slack"
        return {"decision": "apply", "polished": "polished",
                "translate_id": "tr-1", "applied": []}

    def feedback(self, event):
        self.feedback_events.append(event)
        return {"classification": "edited_after_polish"}

    def capture(self, event):
        self.capture_events.append(event)
        return {"queued": True}


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
    assert client.capture_events == []


def _capture_controller():
    adapter, client = Adapter(), Client()
    controller = DesktopController(adapter, client, source_entries=lambda: [
        {"kind": "app", "patterns": ["Slack"]},
    ])
    return controller, adapter, client


def test_explicit_send_captures_before_clear_and_never_calls_translate():
    controller, adapter, client = _capture_controller()
    client.translate = lambda *_args: pytest.fail("Capture must not rewrite")
    result = controller.prepare_send(adapter.snapshot)
    assert result["status"] == "sent"
    assert adapter.sent == ["raw"]
    assert client.capture_events == []  # Network happens after Enter.
    event = result["event"]
    assert event.text == "raw" and event.translate_id is None
    assert controller.save_capture(event)["status"] == "captured"
    assert client.capture_events == [event]
    assert client.feedback_events == []


def test_capture_outage_and_retry_never_send_enter_again():
    controller, adapter, client = _capture_controller()
    result = controller.prepare_send(adapter.snapshot)

    def unavailable(_event):
        raise OSError("daemon offline")

    client.capture = unavailable
    assert controller.save_capture(result["event"])["status"] == "capture_failed"
    client.capture = lambda event: {"queued": True, "capture_id": event.capture_id}
    assert controller.save_capture(result["event"])["status"] == "captured"
    assert adapter.sent == ["raw"]


@pytest.mark.parametrize("changes,status", [
    ({"full_text": ""}, "empty"), ({"secure": True}, "unsupported"),
    ({"editable": False}, "unsupported"), ({"role": "AXStaticText"}, "unsupported"),
    ({"app_name": "TextEdit"}, "unsupported"),
])
def test_unsafe_explicit_send_neither_sends_nor_captures(changes, status):
    controller, adapter, client = _capture_controller()
    result = controller.prepare_send(replace(adapter.snapshot, **changes))
    assert result["status"] == status
    assert adapter.sent == client.capture_events == []


def test_send_guard_failure_keeps_rewrite_feedback_session():
    controller, adapter, client = _capture_controller()
    controller.polish()
    adapter.send_enter = lambda _snapshot: False
    assert controller.prepare_send(adapter.snapshot)["status"] == "send_failed"
    assert controller.tracker.active is True
    assert client.capture_events == client.feedback_events == []


def test_rewrite_then_explicit_send_links_original_and_finishes_feedback_once():
    controller, adapter, client = _capture_controller()
    controller.polish()
    adapter.snapshot = _snapshot("polished edited")
    result = controller.prepare_send(adapter.snapshot)
    event = result["event"]
    assert event.translate_id == "tr-1" and event.text == "polished edited"
    assert event.feedback.original == "raw"
    controller.save_capture(event)
    assert controller.observe(key="Enter") is None
    assert len(client.feedback_events) == 1
    assert len(client.capture_events) == 1


def test_plain_send_only_reports_rewrite_feedback():
    controller, adapter, client = _capture_controller()
    controller.polish()
    controller.observe(key="Enter")
    assert client.capture_events == []
    assert len(client.feedback_events) == 1
    adapter.snapshot = _snapshot("next raw message")
    result = controller.prepare_send(adapter.snapshot)
    assert result["event"].translate_id is None


def test_repeated_rewrites_capture_first_original_but_feedback_last_rewrite():
    controller, adapter, client = _capture_controller()
    controller.polish()
    client.translate = lambda *_args: {
        "decision": "apply", "translate_id": "tr-2", "polished": "polished twice",
    }
    controller.polish()
    result = controller.prepare_send(adapter.snapshot)
    assert result["event"].translate_id == "tr-1"
    assert result["event"].feedback.translate_id == "tr-2"


def test_unchanged_draft_keeps_provenance_after_tracking_timeout():
    controller, adapter, client = _capture_controller()
    controller.polish()
    controller.tracker.observe(adapter.snapshot, now=time.monotonic() + 301)
    result = controller.prepare_send(adapter.snapshot)
    assert result["event"].translate_id == "tr-1"


def test_changed_draft_after_tracking_timeout_fails_closed():
    controller, adapter, client = _capture_controller()
    controller.polish()
    controller.tracker.observe(adapter.snapshot, now=time.monotonic() + 301)
    adapter.snapshot = _snapshot("possibly another message")
    assert controller.prepare_send(adapter.snapshot)["status"] == "unverified_origin"
    assert adapter.sent == client.capture_events == []


@pytest.mark.parametrize("rewrite,explicit", [(False, True), (True, True), (True, False)])
def test_controller_to_daemon_end_to_end(tmp_path, monkeypatch, rewrite, explicit):
    from fastapi.testclient import TestClient
    from memtranslator import server
    from memtranslator.hotkey.client import DaemonClient

    app = server.create_app(store_path=tmp_path / "store.jsonl",
                            events_path=tmp_path / "events.jsonl")
    app.state.source_allowlist.add(label="Slack", kind="app", patterns=["Slack"])
    api = TestClient(app)
    client = DaemonClient()

    def post(path, payload, timeout=20):
        response = api.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(server, "translate", lambda text, _items, **_kwargs: {
        "decision": "apply", "polished": text + " please", "applied_ids": [],
        "parse_error": False, "latency_ms": 0,
    })
    adapter = Adapter()
    controller = DesktopController(adapter, client,
                                   source_entries=app.state.source_allowlist.list)
    if rewrite:
        assert controller.polish()["status"] == "tracking"
    if explicit:
        result = controller.prepare_send(adapter.snapshot)
        assert result["status"] == "sent"
        assert controller.save_capture(result["event"])["status"] == "captured"
        assert app.state.pipeline._a == ["raw"]
        assert adapter.sent == ["raw please" if rewrite else "raw"]
        # HTTP retries preserve the ID and do not forward another Enter.
        assert client.capture(result["event"])["duplicate"] is True
        assert len(adapter.sent) == 1
        assert app.state.pipeline._a == ["raw"]
    else:
        controller.observe(key="Enter")
        assert app.state.pipeline._a == []
