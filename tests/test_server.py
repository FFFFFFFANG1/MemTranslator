import json

import memtranslator.llm as llm
from fastapi.testclient import TestClient
from memtranslator.server import create_app


def make_client(tmp_path):
    app = create_app(store_path=tmp_path / "s.jsonl",
                     events_path=tmp_path / "e.jsonl")
    return TestClient(app), app


def test_requirement_crud(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.post("/api/requirements",
                    json={"text": "Emails under 120 words."})
    assert r.status_code == 200
    rid = r.json()["id"]

    r = client.patch(f"/api/requirements/{rid}", json={"status": "retired"})
    assert r.json()["status"] == "retired"

    r = client.get("/api/requirements")
    assert len(r.json()["requirements"]) == 1

    assert client.patch("/api/requirements/req-nope",
                        json={"status": "retired"}).status_code == 404
    assert client.post("/api/requirements", json={"text": "  "}).status_code == 400


def test_translate_endpoint_apply_and_event(tmp_path, monkeypatch):
    client, app = make_client(tmp_path)
    rid = client.post("/api/requirements",
                      json={"text": "Code without explanations."}).json()["id"]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (
        f'{{"decision": "apply", "applied_ids": ["{rid}"], '
        f'"polished": "Write the function; code only, no explanations."}}'))

    r = client.post("/api/translate", json={"text": "Write the function."})
    body = r.json()
    assert body["decision"] == "apply"
    assert body["applied"][0]["id"] == rid
    assert body["translate_id"]

    kinds = [e["kind"] for e in app.state.events.read_all()]
    assert "translate" in kinds


def test_chat_streams_and_logs_edit_diff(tmp_path, monkeypatch):
    client, app = make_client(tmp_path)
    rid = client.post("/api/requirements", json={"text": "Short."}).json()["id"]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (
        f'{{"decision": "apply", "applied_ids": ["{rid}"], '
        f'"polished": "polished text"}}'))
    tr = client.post("/api/translate", json={"text": "raw text"}).json()

    monkeypatch.setattr(llm, "stream_text", lambda *a, **k: iter(["Hel", "lo"]))
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "polished text EDITED"}],
        "translate_id": tr["translate_id"],
    })
    assert r.status_code == 200
    chunks = [json.loads(l[len("data: "):])
              for l in r.text.splitlines() if l.startswith("data: ")]
    assert "".join(c.get("text", "") for c in chunks) == "Hello"
    assert chunks[-1].get("done") is True

    send = [e for e in app.state.events.read_all() if e["kind"] == "send"][-1]
    assert send["translate_id"] == tr["translate_id"]
    assert send["polished"] == "polished text"
    assert send["edited_after_polish"] is True


def test_chat_rejects_bad_history(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.post("/api/chat", json={"messages": []}).status_code == 400
    assert client.post("/api/chat", json={
        "messages": [{"role": "assistant", "content": "hi"}],
    }).status_code == 400
