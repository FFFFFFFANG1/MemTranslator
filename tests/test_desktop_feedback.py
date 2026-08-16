from fastapi.testclient import TestClient

from memtranslator.server import create_app


def _client(tmp_path):
    app = create_app(store_path=tmp_path / "store.jsonl",
                     events_path=tmp_path / "events.jsonl",
                     vocab_path=tmp_path / "vocabulary.jsonl")
    return TestClient(app), app


def test_desktop_edit_routes_to_vocabulary_and_requirement_feedback(tmp_path):
    client, app = _client(tmp_path)
    requirement = app.state.store.add("Messages should be polite.")
    app.state.events.append("translate", {
        "translate_id": "tr-1",
        "original": "ask Sirius for the result",
        "decision": "apply",
        "polished": "Please ask Sirius for the result.",
        "applied_ids": [requirement.id],
        "parse_error": False,
        "latency_ms": 5,
    })
    response = client.post("/api/desktop/feedback", json={
        "translate_id": "tr-1",
        "final_text": "Please ask siriux for the result.",
        "trigger": "enter",
        "input_context": {
            "app_bundle_id": "com.tinyspeck.slackmacgap",
        },
    })
    assert response.status_code == 200
    body = response.json()
    assert body["classification"] == "edited_after_polish"
    assert body["vocabulary_added"][0]["term"] == "siriux"
    assert app.state.pipeline.pending_count() == 1
    assert app.state.vocabulary.list()[0].alias == "Sirius"


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


def test_vocabulary_crud(tmp_path):
    client, _ = _client(tmp_path)
    created = client.post("/api/vocabulary", json={
        "term": "siriux", "alias": "Sirius"}).json()
    assert created["created"] is True
    listed = client.get("/api/vocabulary").json()["vocabulary"]
    assert len(listed) == 1 and listed[0]["term"] == "siriux"
    retired = client.patch(f"/api/vocabulary/{created['id']}",
                           json={"status": "retired"}).json()
    assert retired["status"] == "retired"


def test_vocabulary_is_applied_without_requirement_or_llm(tmp_path):
    client, _ = _client(tmp_path)
    created = client.post("/api/vocabulary", json={
        "term": "siriux", "alias": "Sirius"}).json()
    response = client.post("/api/translate", json={
        "text": "Ask Sirius for the result."})
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "apply"
    assert body["polished"] == "Ask siriux for the result."
    assert body["vocabulary_applied"][0]["id"] == created["id"]
