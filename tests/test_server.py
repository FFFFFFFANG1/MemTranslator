import json

import memtranslator.llm as llm
import memtranslator.config as config
from fastapi.testclient import TestClient
from memtranslator.embedding import LOCAL_MODEL_FILES
from memtranslator.runtime_settings import RuntimeSettings, read_env
from memtranslator.server import create_app
from memtranslator.source_policy import DEFAULT_SOURCE_ENTRIES, SourceAllowlist
from memtranslator.store import Store


def make_client(tmp_path):
    app = create_app(store_path=tmp_path / "s.jsonl",
                     events_path=tmp_path / "e.jsonl")
    return TestClient(app), app


def add_requirement(client, text, *, work_kind="any", scope="global",
                    bucket=""):
    return client.post("/api/requirements", json={
        "text": text, "work_kind": work_kind, "scope_text": scope,
        "bucket": bucket,
    })


def translator_apply_records(old: str, new: str, evidence: str):
    return [
        {"type": "plan", "decision": "apply", "apply": [1],
         "satisfied": [], "skip_kind": [], "skip_condition": [],
         "skip_superseded": []},
        {"type": "patch", "hunks": [{"old": old, "new": new}]},
        {"type": "audit", "entries": [{
            "entry": 1, "verdict": "apply", "evidence": evidence}]},
    ]


def test_requirement_crud(tmp_path):
    client, app = make_client(tmp_path)
    r = add_requirement(client, "Emails under 120 words.",
                        work_kind="email", scope="audience=client",
                        bucket="output_contract")
    assert r.status_code == 200
    rid = r.json()["id"]

    r = client.patch(f"/api/requirements/{rid}",
                     json={"text": "Emails under 80 words.",
                           "work_kind": "email, report",
                           "scope_text": "audience=client, language=English",
                           "bucket": "communication_style"})
    assert r.status_code == 200
    assert r.json()["text"] == "Emails under 80 words."
    assert r.json()["kinds"] == ["email", "report"]
    assert r.json()["scope"] == {"audience": "client",
                                  "language": "english"}
    assert r.json()["bucket"] == "communication_style"

    r = client.delete(f"/api/requirements/{rid}")
    assert r.status_code == 200
    assert r.json()["status"] == "retired"
    assert app.state.store.active() == []
    persisted = Store(app.state.store.path).get(rid)
    assert persisted.text == "Emails under 80 words."
    assert persisted.status == "retired"
    assert persisted.bucket == "communication_style"

    r = client.get("/api/requirements")
    assert len(r.json()["requirements"]) == 1
    assert r.json()["requirements"][0]["text"] == "Emails under 80 words."
    assert r.json()["requirements"][0]["status"] == "retired"
    assert r.json()["requirements"][0]["kinds"] == ["email", "report"]
    assert r.json()["buckets"] == [
        "task_goal", "reasoning_policy", "deliverables",
        "output_contract", "communication_style", "execution_policy",
    ]

    kinds = [event["kind"] for event in app.state.events.read_all()]
    assert "requirement_added" in kinds
    assert "requirement_updated" in kinds
    assert "requirement_deleted" in kinds

    assert client.patch("/api/requirements/req-nope",
                        json={"status": "retired"}).status_code == 404
    assert client.delete("/api/requirements/req-nope").status_code == 404
    assert client.post("/api/requirements", json={"text": "  "}).status_code == 400


def test_requirement_bucket_is_a_closed_api_choice(tmp_path):
    client, _ = make_client(tmp_path)

    invalid = add_requirement(
        client, "Use a made-up bucket.", bucket="whatever_the_user_types")
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "unknown bucket: whatever_the_user_types"

    created = add_requirement(
        client, "Return a checklist.", bucket="output_contract")
    req_id = created.json()["id"]
    cleared = client.patch(
        f"/api/requirements/{req_id}", json={"bucket": ""})
    assert cleared.status_code == 200
    assert cleared.json()["bucket"] == ""
    invalid_patch = client.patch(
        f"/api/requirements/{req_id}", json={"bucket": "free-form"})
    assert invalid_patch.status_code == 400


def test_control_center_exposes_theme_and_controlled_bucket_ui(tmp_path):
    client, _ = make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'data-theme-choice="system"' in html
    assert 'data-theme-choice="light"' in html
    assert 'data-theme-choice="dark"' in html
    assert "prefers-color-scheme:dark" in html
    assert 'id="add-bucket"' in html
    assert 'class="bucket-select edit-bucket"' in html
    assert "payload.buckets" in html


def test_source_allowlist_crud_and_persistence(tmp_path):
    client, app = make_client(tmp_path)

    listed = client.get("/api/source-allowlist")
    assert listed.status_code == 200
    assert len(listed.json()["entries"]) == len(DEFAULT_SOURCE_ENTRIES)
    assert any(row["label"] == "Codex" for row in listed.json()["entries"])

    created = client.post("/api/source-allowlist", json={
        "label": "My Assistant",
        "kind": "web",
        "patterns": "https://www.assistant.example/chat, api.assistant.example",
    })
    assert created.status_code == 200
    assert created.json()["patterns"] == [
        "assistant.example", "api.assistant.example"]
    entry_id = created.json()["id"]

    updated = client.patch(f"/api/source-allowlist/{entry_id}", json={
        "label": "My Coding Assistant",
        "kind": "app",
        "patterns": ["com.example.agent", "My Agent"],
    })
    assert updated.status_code == 200
    assert updated.json()["kind"] == "app"
    assert updated.json()["label"] == "My Coding Assistant"

    deleted = client.delete(f"/api/source-allowlist/{entry_id}")
    assert deleted.status_code == 200
    assert deleted.json()["id"] == entry_id
    assert client.patch(
        "/api/source-allowlist/source-missing", json={"label": "x"}
    ).status_code == 404
    assert client.delete(
        "/api/source-allowlist/source-missing").status_code == 404

    bad = client.post("/api/source-allowlist", json={
        "label": "Bad", "kind": "web", "patterns": "not-a-domain",
    })
    assert bad.status_code == 400

    reloaded = SourceAllowlist(app.state.source_allowlist.path)
    assert all(row["id"] != entry_id for row in reloaded.list())
    event_kinds = [event["kind"] for event in app.state.events.read_all()]
    assert "source_allowlist_added" in event_kinds
    assert "source_allowlist_updated" in event_kinds
    assert "source_allowlist_deleted" in event_kinds


def test_control_center_exposes_allowlist_page(tmp_path):
    client, _app = make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="nav-allowlist"' in response.text
    assert 'id="allowlist-page"' in response.text
    assert 'id="allowlist-add-form"' in response.text
    assert 'requestJSON("/api/source-allowlist")' in response.text


def test_control_center_exposes_runtime_settings_page(tmp_path):
    client, _app = make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="nav-settings"' in response.text
    assert 'id="settings-page"' in response.text
    assert 'id="llm-api-format"' in response.text
    assert 'id="llm-provider"' not in response.text
    assert response.text.count('value="openai-compatible"') == 1
    assert response.text.count('value="anthropic"') == 1
    assert 'id="llm-api-key"' in response.text
    assert 'id="embedding-default-btn"' in response.text
    assert 'requestJSON("/api/settings")' in response.text
    assert "Stored locally" in response.text


def test_runtime_settings_crud_and_local_default(tmp_path, monkeypatch):
    runtime_keys = (
        "MT_LLM_API_FORMAT", "MT_TRANSLATOR", "MT_WRITER",
        "MT_DOWNSTREAM", "LLM_MODEL",
        "LLM_BASE_URL", "LLM_API_KEY", "OPENROUTER_BASE_URL",
        "OPENROUTER_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
        "MT_EMBEDDING_MODE", "MT_EMBEDDING_MODEL",
        "MT_EMBEDDING_BASE_URL", "MT_EMBEDDING_API_KEY",
        "MT_EMBED_MODEL_DIR", "MT_EMBED_ONNX_FILE",
    )
    for key in runtime_keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in config.MODELS.items():
        monkeypatch.setitem(config.MODELS, key, value)
    monkeypatch.setattr(
        RuntimeSettings, "_refresh_services", staticmethod(lambda: None))
    settings_path = tmp_path / ".env"
    settings_path.write_text(
        "MT_TRANSLATOR=ark:first-model\n"
        "MT_WRITER=ark:first-model\n"
        "MT_DOWNSTREAM=ark:first-model\n"
        "LLM_API_KEY=visible-local-secret\n"
        "LLM_BASE_URL=https://llm.example/v1\n"
        "MT_EMBEDDING_MODE=remote\n"
        "MT_EMBEDDING_MODEL=embed-old\n"
        "MT_EMBED_ONNX_FILE=onnx/custom.onnx\n")
    app = create_app(store_path=tmp_path / "s.jsonl",
                     events_path=tmp_path / "e.jsonl",
                     settings_path=settings_path)
    client = TestClient(app)

    current = client.get("/api/settings").json()
    assert current["llm"]["api_key"] == "visible-local-secret"
    assert current["embedding"]["uses_llm_api_key"] is True
    assert current["embedding"]["uses_llm_base_url"] is True

    updated = client.put("/api/settings/llm", json={
        "api_format": "openai-compatible", "model": "openai/gpt-test",
        "base_url": "https://router.example/v1/", "api_key": "router-secret",
    })
    assert updated.status_code == 200
    assert updated.json()["llm"] == {
        "api_format": "openai-compatible", "model": "openai/gpt-test",
        "base_url": "https://router.example/v1",
        "api_key": "router-secret", "has_api_key": True,
    }
    values = read_env(settings_path)
    assert values["MT_TRANSLATOR"] == "openai/gpt-test"
    assert values["MT_LLM_API_FORMAT"] == "openai-compatible"
    assert values["LLM_API_KEY"] == "router-secret"
    assert "OPENROUTER_API_KEY" not in values

    remote = client.put("/api/settings/embedding", json={
        "model": "embed-new", "base_url": "", "api_key": "",
    }).json()["embedding"]
    assert remote["mode"] == "remote"
    assert remote["model"] == "embed-new"
    assert remote["uses_llm_api_key"] is True
    assert remote["uses_llm_base_url"] is True

    downloads = []

    def fake_download(path):
        downloads.append(path)
        for relative in LOCAL_MODEL_FILES:
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("model")
        return path

    monkeypatch.setattr(
        "memtranslator.runtime_settings.download_local_model", fake_download)
    first = client.post("/api/settings/embedding/default").json()
    second = client.post("/api/settings/embedding/default").json()
    assert first["downloaded"] is True
    assert second["downloaded"] is False
    assert first["embedding"]["mode"] == "local"
    assert first["embedding"]["local_model_ready"] is True
    assert downloads == [tmp_path / "models" / "multilingual-e5-small"]
    values = read_env(settings_path)
    assert values["MT_EMBEDDING_MODE"] == "local"
    assert "MT_EMBEDDING_MODEL" not in values
    assert "MT_EMBED_ONNX_FILE" not in values


def test_demo_seed_is_idempotent_and_exercises_lifecycle(tmp_path):
    client, app = make_client(tmp_path)

    first = client.post("/api/demo/seed")
    second = client.post("/api/demo/seed")

    assert first.json() == {"added": 10, "total": 10}
    assert second.json() == {"added": 0, "total": 10}
    requirements = app.state.store.list()
    assert len(requirements) == 10
    assert sum(item.scope_mode == "global" for item in requirements) == 1
    assert {item.status for item in requirements} == {"active", "retired"}
    old = app.state.store.get("demo-rule-09")
    current = app.state.store.get("demo-rule-10")
    assert old.superseded_by == current.id
    assert current.supersedes == old.id


def test_incomplete_manual_memory_is_queued_as_route_a_message(tmp_path):
    client, app = make_client(tmp_path)

    response = client.post("/api/requirements", json={
        "text": "以后写周报都使用 bullet points",
        "work_kind": "report",
    })

    assert response.status_code == 200
    assert response.json() == {
        "queued": True, "route": "extractor_a",
        "pending": 1, "processed": False,
    }
    assert app.state.store.list() == []
    assert app.state.pipeline._a == ["以后写周报都使用 bullet points"]
    event = app.state.events.read_all()[-1]
    assert event["kind"] == "manual_message_queued"
    assert event["route"] == "extractor_a"


def test_manual_memory_accepts_natural_language_scope(tmp_path):
    client, app = make_client(tmp_path)

    response = add_requirement(
        client, "Keep replies concise.", work_kind="email",
        scope="when replying to external clients")

    assert response.status_code == 200
    assert response.json()["kinds"] == ["email"]
    assert response.json()["scope"] == {}
    assert response.json()["applies_when"] == "when replying to external clients"
    assert response.json()["scope_mode"] == "scoped"
    assert app.state.pipeline.pending_count("a") == 0


def test_global_scope_requires_any_work_kind(tmp_path):
    client, _ = make_client(tmp_path)

    response = add_requirement(
        client, "Keep every response concise.",
        work_kind="email", scope="global")
    assert response.status_code == 400
    assert response.json()["detail"] == "global scope requires work kind any"

    created = add_requirement(
        client, "Keep every response concise.",
        work_kind="any", scope="global")
    response = client.patch(
        f"/api/requirements/{created.json()['id']}",
        json={"work_kind": "email"})
    assert response.status_code == 400
    assert response.json()["detail"] == "global scope requires work kind any"


def test_translate_endpoint_apply_and_event(tmp_path, monkeypatch):
    client, app = make_client(tmp_path)
    rid = add_requirement(
        client, "Code without explanations.",
        work_kind="code", scope="all code tasks").json()["id"]
    records = translator_apply_records(
        "Write the function.",
        "Write the function; code only, no explanations.",
        "code only, no explanations")
    monkeypatch.setattr(
        llm, "stream_text",
        lambda *a, **k: iter(map(json.dumps, records)))

    r = client.post("/api/translate", json={"text": "Write the function."})
    body = r.json()
    assert body["decision"] == "apply"
    assert body["applied"][0]["id"] == rid
    assert body["translate_id"]

    kinds = [e["kind"] for e in app.state.events.read_all()]
    assert "translate" in kinds
    event = [e for e in app.state.events.read_all()
             if e["kind"] == "translate"][-1]
    assert event["applied_entries"][0]["id"] == rid
    assert event["applied_entries"][0]["text"] == "Code without explanations."


def test_translate_stream_exposes_ready_before_audit_and_logs_final(
        tmp_path, monkeypatch):
    client, app = make_client(tmp_path)
    rid = add_requirement(
        client, "Code without explanations.",
        work_kind="any", scope="global").json()["id"]
    records = [
        {"type": "plan", "decision": "apply", "apply": [1],
         "satisfied": [], "skip_kind": [], "skip_condition": [],
         "skip_superseded": []},
        {"type": "patch", "hunks": [{
            "old": "Write the function.",
            "new": "Write the function; code only, no explanations.",
        }]},
        {"type": "audit", "entries": [{
            "entry": 1, "verdict": "apply",
            "evidence": "code only, no explanations",
        }]},
    ]
    monkeypatch.setattr(
        llm, "stream_text",
        lambda *_args, **_kwargs: iter(map(json.dumps, records)))

    response = client.post(
        "/api/translate/stream", json={"text": "Write the function."})
    events = [json.loads(line) for line in response.text.splitlines()]

    assert [event["type"] for event in events] == [
        "plan", "rewrite_ready", "audit", "done"]
    assert events[1]["polished"].endswith("no explanations.")
    assert events[-1]["translation"]["applied"][0]["id"] == rid
    logged = [event for event in app.state.events.read_all()
              if event["kind"] == "translate"][-1]
    assert logged["translate_id"] == events[-1]["translate_id"]


def test_chat_streams_and_logs_edit_diff(tmp_path, monkeypatch):
    client, app = make_client(tmp_path)
    rid = add_requirement(client, "Short.").json()["id"]
    records = translator_apply_records(
        "raw text", "raw text, politely", "politely")
    monkeypatch.setattr(
        llm, "stream_text",
        lambda *a, **k: iter(map(json.dumps, records)))
    tr = client.post("/api/translate", json={"text": "raw text"}).json()

    monkeypatch.setattr(llm, "stream_text", lambda *a, **k: iter(["Hel", "lo"]))
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "raw text, politely EDITED"}],
        "translate_id": tr["translate_id"],
    })
    assert r.status_code == 200
    chunks = [json.loads(l[len("data: "):])
              for l in r.text.splitlines() if l.startswith("data: ")]
    assert "".join(c.get("text", "") for c in chunks) == "Hello"
    assert chunks[-1].get("done") is True

    send = [e for e in app.state.events.read_all() if e["kind"] == "send"][-1]
    assert send["translate_id"] == tr["translate_id"]
    assert send["polished"] == "raw text, politely"
    assert send["edited_after_polish"] is True


def test_chat_rejects_bad_history(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.post("/api/chat", json={"messages": []}).status_code == 400
    assert client.post("/api/chat", json={
        "messages": [{"role": "assistant", "content": "hi"}],
    }).status_code == 400


def test_translate_502_when_llm_unreachable(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path)
    add_requirement(client, "Short.")

    def down(*a, **k):
        raise llm.LLMUnavailable("connection")

    monkeypatch.setattr(llm, "stream_text", down)
    r = client.post("/api/translate", json={"text": "hello"})
    assert r.status_code == 502
    assert r.json()["detail"] == "llm_unreachable"


def test_events_endpoint_lists_newest_first(tmp_path):
    client, _app = make_client(tmp_path)
    add_requirement(client, "a")
    add_requirement(client, "b")
    events = client.get("/api/events?limit=1").json()["events"]
    assert len(events) == 1 and events[0]["text"] == "b"
