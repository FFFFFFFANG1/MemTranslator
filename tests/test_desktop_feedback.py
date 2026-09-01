from fastapi.testclient import TestClient
import pytest

from memtranslator.server import create_app


def _client(tmp_path):
    app = create_app(store_path=tmp_path / "store.jsonl",
                     events_path=tmp_path / "events.jsonl")
    return TestClient(app), app


def test_desktop_edit_routes_to_requirement_feedback(tmp_path):
    client, app = _client(tmp_path)
    requirement = app.state.store.add("Messages should be polite.")
    app.state.events.append("translate", {
        "translate_id": "tr-1",
        "original": "send the result",
        "decision": "apply",
        "polished": "Please send the result.",
        "applied_ids": [requirement.id],
        "parse_error": False,
        "latency_ms": 5,
    })
    response = client.post("/api/desktop/feedback", json={
        "translate_id": "tr-1",
        "final_text": "Please send the result today.",
        "trigger": "enter",
        "input_context": {
            "app_bundle_id": "com.tinyspeck.slackmacgap",
        },
    })
    assert response.status_code == 200
    body = response.json()
    assert body["classification"] == "edited_after_polish"
    assert body["diff"]
    assert app.state.pipeline.pending_count("a") == 0
    assert app.state.pipeline.pending_count("b") == 1
    assert app.state.pipeline._a == []


def test_duplicate_desktop_feedback_only_learns_once(tmp_path):
    client, app = _client(tmp_path)
    app.state.events.append("translate", {
        "translate_id": "tr-1", "original": "raw", "decision": "apply",
        "polished": "raw, politely", "applied_ids": [],
        "parse_error": False, "latency_ms": 5,
    })
    payload = {"translate_id": "tr-1", "final_text": "raw, politely please",
               "trigger": "enter"}
    first = client.post("/api/desktop/feedback", json=payload).json()
    second = client.post("/api/desktop/feedback", json=payload).json()
    assert first["learning_applied"] is True
    assert second["learning_applied"] is False


def test_large_replacement_uses_exact_id_without_plain_task_in_route_a(tmp_path):
    client, app = _client(tmp_path)
    requirement = app.state.store.add("Messages should be polite.")
    raw = "send the result"
    polished = "Please send the result."
    final = "Instead, review the crash log."
    app.state.events.append("translate", {
        "translate_id": "tr-replaced",
        "original": raw,
        "decision": "apply",
        "polished": polished,
        "applied_ids": [requirement.id],
        "applied_entries": [requirement.to_dict()],
        "parse_error": False,
        "latency_ms": 5,
    })

    response = client.post("/api/desktop/feedback", json={
        "translate_id": "tr-replaced",
        "final_text": final,
        "trigger": "focus_changed",
    })

    assert response.status_code == 200
    assert response.json()["classification"] == "edited_after_polish"
    assert response.json()["matched_translate_id"] == "tr-replaced"
    assert app.state.pipeline._a == []
    assert polished not in app.state.pipeline._a
    assert final not in app.state.pipeline._a
    assert app.state.pipeline.pending_count("b") == 1


def _capture_payload(**changes):
    return {"capture_id": "cap-1", "text": "以后请用中文回答",
            "input_context": {"app_bundle_id": "com.openai.codex"},
            **changes}


def test_explicit_capture_needs_no_translate_or_llm_call(tmp_path, monkeypatch):
    from memtranslator import llm

    def unexpected(*_args, **_kwargs):
        pytest.fail("Capture below the batch threshold must not call an LLM")

    monkeypatch.setattr(llm, "complete", unexpected)
    client, app = _client(tmp_path)
    response = client.post("/api/desktop/capture", json=_capture_payload())
    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert app.state.pipeline._a == ["以后请用中文回答"]
    assert app.state.store.active() == []
    assert [event["kind"] for event in app.state.events.read_all()] == ["desktop_capture"]


def test_capture_retries_are_idempotent_but_identical_new_messages_are_allowed(tmp_path):
    client, app = _client(tmp_path)
    payload = _capture_payload()
    first = client.post("/api/desktop/capture", json=payload)
    retry = client.post("/api/desktop/capture", json=payload)
    collision = client.post("/api/desktop/capture", json={**payload, "text": "different"})
    new_message = client.post("/api/desktop/capture", json={**payload, "capture_id": "cap-2"})
    assert first.json()["duplicate"] is False
    assert retry.json()["duplicate"] is True
    assert collision.status_code == 409
    assert new_message.json()["duplicate"] is False
    assert app.state.pipeline._a == [payload["text"], payload["text"]]


@pytest.mark.parametrize("context", [
    {}, {"app_bundle_id": "com.apple.TextEdit"},
    {"app_bundle_id": "com.google.Chrome"},
    {"app_bundle_id": "com.google.Chrome", "web_domain": "chatgpt.com.evil.test"},
    {"app_bundle_id": "com.openai.codex", "secure": True},
    {"app_bundle_id": "com.openai.codex", "editable": False},
])
def test_explicit_capture_fails_closed_before_logging_content(tmp_path, context):
    client, app = _client(tmp_path)
    response = client.post("/api/desktop/capture", json=_capture_payload(input_context=context))
    assert response.status_code == 403
    assert app.state.events.read_all() == []
    assert app.state.pipeline.pending_count() == 0


@pytest.mark.parametrize("changes,status", [
    ({"text": " \n "}, 400), ({"capture_id": ""}, 422),
    ({"translate_id": "missing"}, 404),
])
def test_invalid_capture_does_not_enter_memory(tmp_path, changes, status):
    client, app = _client(tmp_path)
    assert client.post("/api/desktop/capture", json=_capture_payload(**changes)).status_code == status
    assert app.state.pipeline.pending_count() == 0


def test_capture_after_rewrite_uses_original_and_keeps_feedback_independent(tmp_path):
    client, app = _client(tmp_path)
    context = {"app_bundle_id": "com.openai.codex", "identity": "composer"}
    app.state.events.append("translate", {
        "translate_id": "tr-1", "original": "Explain the bug", "polished": "Explain the bug in English",
        "decision": "apply", "applied_ids": [], "context": context,
    })
    response = client.post("/api/desktop/capture", json=_capture_payload(
        text="Explain the bug in English, briefly", translate_id="tr-1", input_context=context))
    assert response.status_code == 200
    assert app.state.pipeline._a == ["Explain the bug"]
    client.post("/api/desktop/feedback", json={
        "translate_id": "tr-1", "final_text": "Explain the bug in English, briefly", "trigger": "enter",
    })
    assert app.state.pipeline._a == ["Explain the bug"]
    moved = client.post("/api/desktop/capture", json=_capture_payload(
        capture_id="cap-moved", translate_id="tr-1",
        input_context={**context, "identity": "different-composer"}))
    assert moved.status_code == 403


def test_unflushed_capture_recovers_after_restart_without_duplicate(tmp_path):
    client, _app = _client(tmp_path)
    payload = _capture_payload()
    client.post("/api/desktop/capture", json=payload)
    restarted, app = _client(tmp_path)
    assert app.state.pipeline._a == [payload["text"]]
    assert restarted.post("/api/desktop/capture", json=payload).json()["duplicate"] is True
    assert app.state.pipeline._a == [payload["text"]]


def test_flushed_captures_are_not_replayed_after_restart(tmp_path, monkeypatch):
    from memtranslator import pipeline
    from memtranslator.config import A_BATCH_N

    monkeypatch.setattr(pipeline, "run_a_extraction", lambda *_args: {"ops": [], "flags": []})
    client, app = _client(tmp_path)
    for ordinal in range(A_BATCH_N):
        assert client.post("/api/desktop/capture", json=_capture_payload(
            capture_id=f"cap-{ordinal}")).status_code == 200
    assert app.state.pipeline.pending_count("a") == 0
    _restarted, restored = _client(tmp_path)
    assert restored.state.pipeline.pending_count("a") == 0


def test_concurrent_capture_retries_only_queue_one_copy(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    client, app = _client(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(
            lambda _index: client.post("/api/desktop/capture", json=_capture_payload()), range(4)))
    assert all(response.status_code == 200 for response in responses)
    assert sum(not response.json()["duplicate"] for response in responses) == 1
    assert app.state.pipeline._a == ["以后请用中文回答"]


def test_completed_capture_is_journaled_even_when_feedback_flush_fails(tmp_path, monkeypatch):
    from memtranslator import pipeline
    from memtranslator.llm import LLMUnavailable

    monkeypatch.setattr(pipeline, "A_BATCH_N", 1)
    monkeypatch.setattr(pipeline, "B_BATCH_N", 1)
    monkeypatch.setattr(pipeline, "run_a_extraction", lambda *_args: {"ops": [], "flags": []})

    def unavailable(*_args):
        raise LLMUnavailable("feedback model offline")

    monkeypatch.setattr(pipeline, "run_b_extraction", unavailable)
    client, app = _client(tmp_path)
    app.state.pipeline.add_feedback(
        [{"id": "req-1", "text": "Keep replies concise"}],
        [{"old": "x", "new": "y"}], now=0)
    assert client.post("/api/desktop/capture", json=_capture_payload()).status_code == 200
    assert app.state.pipeline.pending_count("a") == 0
    assert app.state.pipeline.pending_count("b") == 1
    _client_after_restart, restored = _client(tmp_path)
    assert restored.state.pipeline.pending_count("a") == 0


def test_translate_ids_cannot_collide_after_daemon_restart(tmp_path):
    client, _app = _client(tmp_path)
    context = {"app_bundle_id": "com.openai.codex"}
    original = client.post("/api/translate", json={"text": "first", "context": context}).json()
    restarted, app = _client(tmp_path)
    another = restarted.post("/api/translate", json={"text": "other", "context": context}).json()
    assert original["translate_id"] != another["translate_id"]
    response = restarted.post("/api/desktop/capture", json=_capture_payload(
        text="first", translate_id=original["translate_id"], input_context=context))
    assert response.status_code == 200
    assert app.state.pipeline._a == ["first"]
