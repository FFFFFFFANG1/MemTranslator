from dataclasses import replace

import pytest

from memtranslator.hotkey.controller import DesktopController
from memtranslator.hotkey.models import InputSnapshot, TextRange, WriteResult
from memtranslator.hotkey.session import PendingWrites


def _snapshot(text: str, identity: str = "box") -> InputSnapshot:
    return InputSnapshot(
        identity=identity,
        full_text=text,
        target_range=TextRange(0, len(text)),
        app_name="Slack",
        app_bundle_id="com.tinyspeck.slackmacgap",
        role="AXTextArea",
    )


class Adapter:
    def __init__(self):
        self.snapshot = _snapshot("raw")
        self.sent = []

    def capture(self):
        return self.snapshot

    def capture_once(self):
        return self.snapshot

    def write(self, _snapshot_before, text):
        self.snapshot = _snapshot(text, _snapshot_before.identity)
        return WriteResult(True, "paste", expected_full_text=text)

    def send_enter(self, snapshot):
        self.sent.append(snapshot.full_text)
        self.snapshot = _snapshot("", snapshot.identity)
        return True


class Client:
    def __init__(self):
        self.feedback_events = []
        self.learn_events = []

    def translate(self, text, context):
        assert text == "raw" and context["app_name"] == "Slack"
        return {
            "decision": "apply",
            "polished": "written",
            "translate_id": "tr-1",
            "applied": [],
        }

    def feedback(self, event):
        self.feedback_events.append(event)
        return {"classification": "edited_after_polish"}

    def learn(self, event):
        self.learn_events.append(event)
        return {"queued": True}


def _controller(*, pending_writes=None):
    adapter, client = Adapter(), Client()
    controller = DesktopController(
        adapter,
        client,
        pending_writes=pending_writes,
        source_entries=lambda: [
            {"kind": "app", "patterns": ["Slack"]},
        ],
    )
    return controller, adapter, client


def test_controller_runs_write_then_explicit_learn_loop():
    controller, adapter, client = _controller()
    progress = []
    controller.on_progress = lambda state, snapshot: progress.append(
        (state, snapshot.identity))

    written = controller.write()
    adapter.snapshot = _snapshot("written, human-edited")
    prepared = controller.prepare_learn(adapter.snapshot)

    assert written["status"] == "written"
    assert written["write"].strategy == "paste"
    assert progress == [("translating", "box"), ("writing", "box")]
    assert prepared["status"] == "learn_ready"
    assert prepared["event"].text == "written, human-edited"
    assert prepared["event"].translate_id == "tr-1"
    assert prepared["event"].feedback.trigger == "learn_hotkey"
    assert client.learn_events == client.feedback_events == []

    committed = controller.commit_learn(prepared["event"])

    assert committed["status"] == "learned"
    assert client.learn_events == [prepared["event"]]
    assert client.feedback_events == [prepared["event"].feedback]


def test_controller_writes_on_stream_ready_before_background_audit_finishes():
    controller, adapter, client = _controller()
    timeline = []
    original_write = adapter.write

    def write(snapshot, text):
        timeline.append("textbox_write")
        return original_write(snapshot, text)

    def stream(_text, _context, on_ready):
        timeline.append("plan")
        on_ready({"type": "rewrite_ready", "decision": "apply",
                  "polished": "written", "translate_id": "tr-stream"})
        timeline.append("audit")
        return {"decision": "apply", "polished": "written",
                "translate_id": "tr-stream", "applied": []}

    adapter.write = write
    client.translate_stream = stream

    result = controller.write()

    assert result["status"] == "written"
    assert timeline == ["plan", "textbox_write", "audit"]
    assert controller.has_pending_write is True


def test_controller_rejects_stale_write_failure():
    controller, adapter, _client = _controller()
    adapter.write = lambda snapshot, text: WriteResult(
        False, "none", reason="stale_snapshot")

    assert controller.write()["status"] == "write_failed"
    assert controller.has_pending_write is False


def test_controller_can_use_a_pre_captured_snapshot():
    controller, adapter, _client = _controller()
    captured = adapter.snapshot
    captures = []

    def capture_after_write():
        captures.append(adapter.snapshot.full_text)
        return adapter.snapshot

    adapter.capture = capture_after_write

    assert controller.write(snapshot=captured)["status"] == "written"
    assert captures == ["written"]


def test_verified_write_keeps_provenance_when_post_write_capture_is_missing():
    controller, adapter, _client = _controller()
    original = adapter.snapshot
    adapter.capture = lambda: None

    written = controller.write(snapshot=original)
    prepared = controller.prepare_learn(adapter.snapshot)

    assert written["status"] == "written"
    assert written["snapshot"].full_text == "written"
    assert prepared["status"] == "learn_ready"
    assert prepared["event"].translate_id == "tr-1"
    assert prepared["event"].feedback is not None


def test_noop_write_never_writes_or_learns_until_explicit_learn():
    controller, adapter, client = _controller()
    writes = []
    adapter.write = lambda *_args: writes.append(True)
    client.translate = lambda _text, _context: {
        "decision": "noop",
        "polished": None,
        "translate_id": "tr-noop",
        "applied": [],
    }

    written = controller.write()

    assert written["status"] == "write_noop"
    assert writes == []
    assert client.learn_events == client.feedback_events == []

    prepared = controller.prepare_learn(adapter.snapshot)
    controller.commit_learn(prepared["event"])

    assert client.learn_events == [prepared["event"]]
    assert client.feedback_events[0].translate_id == "tr-noop"
    assert client.feedback_events[0].original == "raw"
    assert client.feedback_events[0].final_text == "raw"


def test_learn_without_write_never_calls_translate():
    controller, adapter, client = _controller()
    client.translate = lambda *_args: pytest.fail("Learn must not Write")

    prepared = controller.prepare_learn(adapter.snapshot)

    assert prepared["status"] == "learn_ready"
    assert adapter.sent == ["raw"]
    assert prepared["event"].text == "raw"
    assert prepared["event"].translate_id is None
    assert prepared["event"].feedback is None
    assert client.learn_events == []

    assert controller.commit_learn(prepared["event"])["status"] == "learned"
    assert client.learn_events == [prepared["event"]]
    assert client.feedback_events == []


def test_learn_outage_and_retry_never_send_enter_again():
    controller, adapter, client = _controller()
    prepared = controller.prepare_learn(adapter.snapshot)

    def unavailable(_event):
        raise OSError("daemon offline")

    client.learn = unavailable
    assert controller.commit_learn(prepared["event"])["status"] == "learn_failed"
    client.learn = lambda event: {"queued": True, "learn_id": event.learn_id}
    assert controller.commit_learn(prepared["event"])["status"] == "learned"
    assert adapter.sent == ["raw"]


@pytest.mark.parametrize("changes,status", [
    ({"full_text": ""}, "empty"),
    ({"secure": True}, "unsupported"),
    ({"editable": False}, "unsupported"),
    ({"role": "AXStaticText"}, "unsupported"),
    ({"app_name": "TextEdit"}, "unsupported"),
])
def test_unsafe_learn_neither_sends_nor_learns(changes, status):
    controller, adapter, client = _controller()

    result = controller.prepare_learn(replace(adapter.snapshot, **changes))

    assert result["status"] == status
    assert adapter.sent == client.learn_events == client.feedback_events == []


def test_send_guard_failure_keeps_pending_write():
    controller, adapter, client = _controller()
    controller.write()
    adapter.send_enter = lambda _snapshot: False

    assert controller.prepare_learn(adapter.snapshot)["status"] == "send_failed"
    assert controller.has_pending_write is True
    assert client.learn_events == client.feedback_events == []


def test_plain_enter_dismisses_matching_write_without_learning():
    controller, adapter, client = _controller()
    controller.write()

    assert controller.dismiss(adapter.snapshot) is True
    assert controller.has_pending_write is False
    assert client.learn_events == client.feedback_events == []

    adapter.snapshot = _snapshot("next raw message")
    prepared = controller.prepare_learn(adapter.snapshot)
    assert prepared["event"].translate_id is None


def test_other_composer_does_not_dismiss_and_return_can_learn():
    controller, adapter, client = _controller()
    controller.write()
    other = _snapshot("unrelated", identity="box-2")

    assert controller.dismiss(other) is False
    assert controller.has_pending_write is True

    adapter.snapshot = _snapshot("written after returning")
    prepared = controller.prepare_learn(adapter.snapshot)
    controller.commit_learn(prepared["event"])

    assert prepared["event"].translate_id == "tr-1"
    assert prepared["event"].feedback.final_text == "written after returning"
    assert controller.has_pending_write is False
    assert len(client.learn_events) == len(client.feedback_events) == 1


def test_learn_in_other_composer_keeps_original_pending_write():
    controller, adapter, client = _controller()
    controller.write()
    other = _snapshot("other draft", identity="box-2")

    prepared = controller.prepare_learn(other)
    controller.commit_learn(prepared["event"])

    assert prepared["event"].translate_id is None
    assert prepared["event"].feedback is None
    assert controller.has_pending_write is True
    assert client.learn_events == [prepared["event"]]
    assert client.feedback_events == []


def test_writes_in_two_composers_keep_both_origins():
    controller, adapter, client = _controller()
    client.translate = lambda text, context: {
        "decision": "apply",
        "translate_id": f"tr-{context['identity']}",
        "polished": text.replace("raw", "written"),
    }
    adapter.snapshot = _snapshot("raw A", identity="box-a")
    controller.write()
    adapter.snapshot = _snapshot("raw B", identity="box-b")
    controller.write()

    adapter.snapshot = _snapshot("written A, edited", identity="box-a")
    prepared = controller.prepare_learn(adapter.snapshot)

    assert prepared["event"].translate_id == "tr-box-a"
    assert prepared["event"].feedback.translate_id == "tr-box-a"
    assert prepared["event"].feedback.original == "raw A"
    assert controller.has_pending_write is True  # box-b remains pending.


def test_repeated_write_keeps_first_origin_and_latest_feedback_target():
    controller, adapter, _client = _controller()
    controller.write()
    controller.client.translate = lambda *_args: {
        "decision": "apply",
        "translate_id": "tr-2",
        "polished": "written twice",
    }

    controller.write()
    prepared = controller.prepare_learn(adapter.snapshot)

    assert prepared["event"].translate_id == "tr-1"
    assert prepared["event"].feedback.translate_id == "tr-2"
    assert prepared["event"].feedback.original == "written"


def test_expired_unchanged_write_keeps_provenance_without_feedback():
    controller, adapter, _client = _controller(
        pending_writes=PendingWrites(feedback_timeout_s=-1))
    controller.write()

    prepared = controller.prepare_learn(adapter.snapshot)

    assert prepared["status"] == "learn_ready"
    assert prepared["event"].translate_id == "tr-1"
    assert prepared["event"].feedback is None


def test_expired_changed_write_fails_closed():
    controller, adapter, client = _controller(
        pending_writes=PendingWrites(feedback_timeout_s=-1))
    controller.write()
    adapter.snapshot = _snapshot("possibly another message")

    assert controller.prepare_learn(adapter.snapshot)["status"] == "unverified_origin"
    assert adapter.sent == []
    assert client.learn_events == client.feedback_events == []


@pytest.mark.parametrize("write,learn", [
    (False, True),
    (True, True),
    (True, False),
])
def test_controller_to_daemon_end_to_end(tmp_path, monkeypatch, write, learn):
    from fastapi.testclient import TestClient

    from memtranslator import server
    from memtranslator.hotkey.client import DaemonClient

    app = server.create_app(
        store_path=tmp_path / "store.jsonl",
        events_path=tmp_path / "events.jsonl",
    )
    app.state.source_allowlist.add(
        label="Slack", kind="app", patterns=["Slack"])
    api = TestClient(app)
    client = DaemonClient()

    def post(path, payload, timeout=20):
        response = api.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(server, "translate", lambda text, _items, **_kwargs: {
        "decision": "apply",
        "polished": text + " please",
        "applied_ids": [],
        "parse_error": False,
        "latency_ms": 0,
    })
    adapter = Adapter()
    controller = DesktopController(
        adapter,
        client,
        source_entries=app.state.source_allowlist.list,
    )

    if write:
        assert controller.write()["status"] == "written"
    if learn:
        prepared = controller.prepare_learn(adapter.snapshot)
        assert prepared["status"] == "learn_ready"
        assert controller.commit_learn(prepared["event"])["status"] == "learned"
        assert app.state.pipeline._a == ["raw"]
        assert adapter.sent == ["raw please" if write else "raw"]
        # Network retries preserve the ID and never forward another Enter.
        assert client.learn(prepared["event"])["duplicate"] is True
        assert len(adapter.sent) == 1
        assert app.state.pipeline._a == ["raw"]
    else:
        assert controller.dismiss(adapter.snapshot) is True
        assert app.state.pipeline._a == []
