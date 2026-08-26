from fastapi.testclient import TestClient

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
