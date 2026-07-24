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


def _seed_translate(app, original, polished, applied_ids):
    app.state.events.append("translate", {
        "translate_id": "tr-t1", "original": original, "decision": "apply",
        "polished": polished, "applied_ids": applied_ids,
        "parse_error": False, "latency_ms": 5})


def test_natural_rule_setting_queues_candidate(tmp_path):
    client, app = _client(tmp_path)
    r = client.post("/api/events/submit",
                    json={"text": "以后我让你写周报，一律用 bullet points",
                          "source": "hook"})
    assert r.status_code == 200
    assert app.state.pipeline.pending_count() == 1


def test_plain_task_submit_queues_nothing(tmp_path):
    client, app = _client(tmp_path)
    client.post("/api/events/submit",
                json={"text": "帮我给房东写封邮件催修暖气", "source": "hook"})
    assert app.state.pipeline.pending_count() == 0


def test_accepted_verbatim_bumps_strength(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, "给房东写邮件催修暖气", polished, [req.id])
    client.post("/api/events/submit", json={"text": polished, "source": "hook"})
    assert app.state.store.get(req.id).strength == 2


def test_edited_submit_feeds_diff_batch(tmp_path):
    client, app = _client(tmp_path)
    req = app.state.store.add("邮件不超过120词")
    polished = "给房东写封不超过120词的邮件，催他尽快修暖气"
    _seed_translate(app, "给房东写邮件催修暖气", polished, [req.id])
    client.post("/api/events/submit",
                json={"text": polished + "，用英文写", "source": "hook"})
    assert app.state.pipeline.pending_count() == 1     # diff triple queued
    assert app.state.store.get(req.id).strength == 2   # injections kept → +1


def test_batch_full_flush_lands_learned_requirement(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(
        [{"op": "new", "text": "周报要用 bullet points",
          "key": "report.format", "salience": 4}]))
    client, app = _client(tmp_path)
    for i in range(BATCH_N):
        client.post("/api/events/submit",
                    json={"text": f"以后第{i}类文档一律用 markdown 格式",
                          "source": "hook"})
    learned = [r for r in app.state.store.active() if r.source == "learned"]
    assert learned and learned[0].text == "周报要用 bullet points"
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
