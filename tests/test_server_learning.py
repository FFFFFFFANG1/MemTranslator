"""M6: the learning loop wired into the server — submits feed the pipeline,
strength rules fire, batch flush lands ops, outages never break the API."""
import json

from fastapi.testclient import TestClient

import memtranslator.llm as llm
from memtranslator.config import BATCH_N
from memtranslator.llm import LLMUnavailable
from memtranslator.server import create_app


def _client(tmp_path, monkeypatch=None):
    app = create_app(store_path=tmp_path / "store.jsonl",
                     events_path=tmp_path / "events.jsonl")
    return TestClient(app), app


def _seed_translate(app, original, polished, applied_ids,
                    applied_entries=None):
    payload = {
        "translate_id": "tr-t1", "original": original, "decision": "apply",
        "polished": polished, "applied_ids": applied_ids,
        "parse_error": False, "latency_ms": 5}
    if applied_entries is not None:
        payload["applied_entries"] = applied_entries
    app.state.events.append("translate", payload)


def test_natural_rule_setting_queues_candidate(tmp_path):
    client, app = _client(tmp_path)
    r = client.post("/api/events/submit",
                    json={"text": "以后我让你写周报，一律用 bullet points",
                          "source": "hook"})
    assert r.status_code == 200
    assert app.state.pipeline.pending_count() == 1


def test_plain_task_submit_queues_for_extractor_admission(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/events/submit",
                json={"text": "帮我给房东写封邮件催修暖气", "source": "hook"})
    assert app.state.pipeline.pending_count() == 1


def test_translate_does_not_receive_unflushed_natural_messages(
        tmp_path, monkeypatch):
    prompts = []

    def fake(_model, _system, user, **_kwargs):
        prompts.append(user)
        return json.dumps({"decision": "noop"})

    monkeypatch.setattr(llm, "complete", fake)
    client, _app = _client(tmp_path)
    client.post("/api/events/submit", json={
        "text": "以后我让你写邮件，一律保持专业语气", "source": "hook"})

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
    client.post("/api/events/submit", json={"text": polished, "source": "hook"})
    assert app.state.store.get(req.id).strength == 2
    assert app.state.pipeline._a == [original]
    assert polished not in app.state.pipeline._a
    assert app.state.pipeline._b == []


def test_edited_submit_feeds_diff_batch(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    original = "给房东写邮件催修暖气"
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, original, polished, [req.id])
    client.post("/api/events/submit",
                json={"text": polished + "，用英文写", "source": "hook"})
    assert app.state.pipeline.pending_count("a") == 1
    assert app.state.pipeline.pending_count("b") == 1
    assert app.state.pipeline._a == [original]
    assert polished not in app.state.pipeline._a
    assert app.state.store.get(req.id).strength == 2   # injections kept → +1


def test_reverted_submit_sends_original_to_a_and_feedback_to_b(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    original = "给房东写邮件催修暖气"
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, original, polished, [req.id])

    client.post("/api/events/submit",
                json={"text": original, "source": "hook"})

    assert app.state.pipeline._a == [original]
    assert polished not in app.state.pipeline._a
    assert app.state.pipeline.pending_count("b") == 1
    assert app.state.store.get(req.id).strength == 0


def test_edited_submit_uses_entry_snapshot_from_translate_time(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    snapshot = req.to_dict()
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, "给房东写邮件催修暖气", polished, [req.id],
                    applied_entries=[snapshot])

    app.state.store.update(req.id, text="邮件不超过80词")
    client.post("/api/events/submit",
                json={"text": polished + "，用英文写", "source": "hook"})

    queued = app.state.pipeline._b[0]["entries"]
    assert queued[0]["text"] == "邮件不超过120词"


def test_batch_full_flush_lands_learned_requirement(tmp_path, monkeypatch):
    def fake(_model, _system, user, **_kwargs):
        if "SIGNALS-A:" in user:
            return json.dumps([{"decision": "candidate",
                                "kind": "potential_new", "item": {
                "text": "Format recurring documents as Markdown.",
                    "bucket": "output_contract", "scope_mode": "scoped",
                    "applies_when": None,
                "work_kinds": ["report"], "key": "document.format", "confidence": 8},
                "change_candidate": None, "sources": [1]}])
        return json.dumps([{"case": 1, "action": "add", "targets": []}])
    monkeypatch.setattr(llm, "complete", fake)
    client, app = _client(tmp_path)
    for i in range(BATCH_N):
        client.post("/api/events/submit",
                    json={"text": f"以后第{i}类文档一律用 markdown 格式",
                          "source": "hook"})
    learned = [r for r in app.state.store.active() if r.source == "learned"]
    assert learned and learned[0].text == "Format recurring documents as Markdown."
    assert learned[0].kinds == ["report"]
    assert learned[0].sources == ["以后第0类文档一律用 markdown 格式"]
    assert app.state.pipeline.pending_count() == 0


def test_flush_outage_keeps_queue_and_returns_200(tmp_path, monkeypatch):
    def dead(*a, **k):
        raise LLMUnavailable("connection")
    monkeypatch.setattr(llm, "complete", dead)
    client, app = _client(tmp_path)
    for i in range(BATCH_N):
        r = client.post("/api/events/submit",
                        json={"text": f"以后第{i}类文档一律用 markdown 格式",
                              "source": "hook"})
        assert r.status_code == 200                    # outage never breaks the API
    assert app.state.pipeline.pending_count() == BATCH_N   # queue survives
