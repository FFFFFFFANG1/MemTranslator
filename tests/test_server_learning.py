"""The desktop feedback loop feeds both memory-write channels safely."""
import json

from fastapi.testclient import TestClient

import memtranslator.llm as llm
from memtranslator.config import BATCH_N
from memtranslator.llm import LLMUnavailable
from memtranslator.server import create_app


def _client(tmp_path):
    app = create_app(store_path=tmp_path / "store.jsonl",
                     events_path=tmp_path / "events.jsonl")
    return TestClient(app), app


def _seed_translate(app, original, polished, applied_ids,
                    applied_entries=None, *, translate_id="tr-t1",
                    context=None):
    payload = {
        "translate_id": translate_id, "original": original,
        "decision": "apply", "polished": polished,
        "applied_ids": applied_ids, "parse_error": False, "latency_ms": 5,
    }
    if applied_entries is not None:
        payload["applied_entries"] = applied_entries
    if context is not None:
        payload["context"] = context
    app.state.events.append("translate", payload)


def _feedback(client, translate_id, final_text):
    return client.post("/api/desktop/feedback", json={
        "translate_id": translate_id,
        "final_text": final_text,
        "trigger": "enter",
    })


def _accepted_feedback(client, app, text, ordinal=1):
    translate_id = f"tr-accepted-{ordinal}"
    polished = f"{text} [polished]"
    _seed_translate(
        app, text, polished, [], translate_id=translate_id,
        context={"app_bundle_id": "com.openai.codex"})
    return _feedback(client, translate_id, polished)


def test_raw_rule_setting_queues_candidate_after_feedback(tmp_path):
    client, app = _client(tmp_path)
    response = _accepted_feedback(
        client, app, "以后我让你写周报，一律用 bullet points")
    assert response.status_code == 200
    assert response.json()["classification"] == "accepted_verbatim"
    assert app.state.pipeline.pending_count() == 1


def test_plain_task_from_allowed_app_enters_extractor_a(tmp_path):
    client, app = _client(tmp_path)
    _accepted_feedback(client, app, "帮我给房东写封邮件催修暖气")
    assert app.state.pipeline._a == ["帮我给房东写封邮件催修暖气"]


def test_input_from_unlisted_app_does_not_enter_extractor_a(tmp_path):
    client, app = _client(tmp_path)
    _seed_translate(
        app, "ordinary task", "ordinary task [polished]", [],
        context={"app_bundle_id": "com.apple.TextEdit"})
    _feedback(client, "tr-t1", "ordinary task [polished]")
    assert app.state.pipeline.pending_count("a") == 0


def test_allowed_ai_webpage_enters_extractor_a(tmp_path):
    client, app = _client(tmp_path)
    _seed_translate(
        app, "ordinary web task", "ordinary web task [polished]", [],
        context={"app_bundle_id": "com.google.Chrome",
                 "web_domain": "gemini.google.com"})
    _feedback(client, "tr-t1", "ordinary web task [polished]")
    assert app.state.pipeline._a == ["ordinary web task"]


def test_browser_without_allowed_domain_does_not_enter_a(tmp_path):
    client, app = _client(tmp_path)
    _seed_translate(
        app, "mail task", "mail task [polished]", [],
        context={"app_bundle_id": "com.google.Chrome",
                 "web_domain": "mail.google.com"})
    _feedback(client, "tr-t1", "mail task [polished]")
    assert app.state.pipeline.pending_count("a") == 0


def test_allowlist_crud_changes_route_a_without_restart(tmp_path):
    client, app = _client(tmp_path)

    removed = client.delete("/api/source-allowlist/source-app-codex")
    assert removed.status_code == 200
    _seed_translate(
        app, "codex task", "codex task [polished]", [],
        translate_id="tr-removed-codex",
        context={"app_bundle_id": "com.openai.codex"})
    _feedback(client, "tr-removed-codex", "codex task [polished]")
    assert app.state.pipeline.pending_count("a") == 0

    created = client.post("/api/source-allowlist", json={
        "label": "My Agent",
        "kind": "app",
        "patterns": ["com.example.my-agent", "My Agent"],
    })
    assert created.status_code == 200
    _seed_translate(
        app, "custom task", "custom task [polished]", [],
        translate_id="tr-custom-agent",
        context={"app_bundle_id": "com.example.my-agent"})
    _feedback(client, "tr-custom-agent", "custom task [polished]")
    assert app.state.pipeline._a == ["custom task"]


def test_noop_transaction_still_sends_only_raw_to_extractor_a(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        llm, "complete", lambda *_args, **_kwargs: json.dumps({
            "decision": "noop",
        }))
    client, app = _client(tmp_path)
    raw = "以后周报都用 bullet points"

    translated = client.post("/api/translate", json={
        "text": raw,
        "context": {"app_bundle_id": "com.openai.codex"},
    }).json()
    response = _feedback(client, translated["translate_id"], raw)

    assert response.status_code == 200
    assert response.json()["classification"] == "accepted_verbatim"
    assert app.state.pipeline._a == [raw]
    assert app.state.pipeline._b == []


def test_translate_does_not_receive_unflushed_natural_messages(
        tmp_path, monkeypatch):
    prompts = []

    def fake(_model, _system, user, **_kwargs):
        prompts.append(user)
        return json.dumps({"decision": "noop"})

    monkeypatch.setattr(llm, "complete", fake)
    client, app = _client(tmp_path)
    _accepted_feedback(
        client, app, "以后我让你写邮件，一律保持专业语气")

    response = client.post("/api/translate", json={"text": "写封邮件催进度"})

    assert response.status_code == 200
    assert response.json()["decision"] == "noop"
    assert prompts == []


def test_accepted_verbatim_bumps_strength(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    original = "给房东写邮件催修暖气"
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, original, polished, [req.id])
    _feedback(client, "tr-t1", polished)
    assert app.state.store.get(req.id).strength == 2
    assert app.state.pipeline._a == []
    assert polished not in app.state.pipeline._a
    assert app.state.pipeline._b == []


def test_edited_feedback_feeds_diff_batch(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    original = "给房东写邮件催修暖气"
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, original, polished, [req.id])
    _feedback(client, "tr-t1", polished + "，用英文写")
    assert app.state.pipeline.pending_count("a") == 0
    assert app.state.pipeline.pending_count("b") == 1
    assert app.state.pipeline._a == []
    assert polished not in app.state.pipeline._a
    assert app.state.store.get(req.id).strength == 2


def test_reverted_feedback_sends_original_to_a_and_diff_to_b(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    original = "给房东写邮件催修暖气"
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, original, polished, [req.id])

    _feedback(client, "tr-t1", original)

    assert app.state.pipeline._a == []
    assert polished not in app.state.pipeline._a
    assert app.state.pipeline.pending_count("b") == 1
    assert app.state.store.get(req.id).strength == 0


def test_edited_feedback_uses_entry_snapshot_from_translate_time(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    snapshot = req.to_dict()
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, "给房东写邮件催修暖气", polished, [req.id],
                    applied_entries=[snapshot])

    app.state.store.update(req.id, text="邮件不超过80词")
    _feedback(client, "tr-t1", polished + "，用英文写")

    queued = app.state.pipeline._b[0]["entries"]
    assert queued[0]["text"] == "邮件不超过120词"


def test_batch_full_flush_lands_learned_requirement(tmp_path, monkeypatch):
    def fake(_model, _system, user, **_kwargs):
        if "SIGNALS-A:" in user:
            return json.dumps([{"decision": "candidate",
                                "kind": "potential_new", "item": {
                "text": "Format recurring documents as Markdown.",
                "bucket": "output_contract", "scope_mode": "scoped",
                "applies_when": None, "work_kinds": ["report"],
                "key": "document.format", "confidence": 8},
                "change_candidate": None, "sources": [1]}])
        return json.dumps([{"case": 1, "action": "add", "targets": []}])

    monkeypatch.setattr(llm, "complete", fake)
    client, app = _client(tmp_path)
    for i in range(BATCH_N):
        _accepted_feedback(
            client, app,
            f"以后第{i}类文档一律用 markdown 格式", ordinal=i)

    learned = [r for r in app.state.store.active() if r.source == "learned"]
    assert learned and learned[0].text == "Format recurring documents as Markdown."
    assert learned[0].kinds == ["report"]
    assert learned[0].sources == ["以后第0类文档一律用 markdown 格式"]
    assert app.state.pipeline.pending_count() == 0


def test_flush_outage_keeps_queue_and_returns_200(tmp_path, monkeypatch):
    def dead(*_args, **_kwargs):
        raise LLMUnavailable("connection")

    monkeypatch.setattr(llm, "complete", dead)
    client, app = _client(tmp_path)
    for i in range(BATCH_N):
        response = _accepted_feedback(
            client, app,
            f"以后第{i}类文档一律用 markdown 格式", ordinal=i)
        assert response.status_code == 200
    assert app.state.pipeline.pending_count() == BATCH_N
