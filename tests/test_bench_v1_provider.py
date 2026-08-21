"""M5: V1Provider adapter — routing and style filtering."""
import json

import memtranslator.llm as llm
from bench.suites.providers import V1Provider
from memtranslator.schema import Requirement


def test_natural_message_reaches_a_without_mechanical_screen(monkeypatch):
    prompts = []
    monkeypatch.setattr(
        llm, "complete",
        lambda _model, _system, user, **_kwargs:
        prompts.append(user) or "[]")
    message = "帮我给房东写封邮件催修暖气"
    provider = V1Provider()
    ops = provider.extract(
        [{"type": "natural", "text": message}], [])
    assert ops == []
    assert len(prompts) == 1
    assert message in prompts[0]
    assert provider.last_trace["route_a"]["input_signals"] == [message]


def test_routes_and_translates_numbered_ops(monkeypatch):
    existing = [Requirement(text="周报要用 bullet points",
                            key="report.format")]
    prompts = []

    def fake(model, system, user, max_tokens=1024, **kw):
        prompts.append(user)
        if "SIGNALS:" in user:                       # route B
            return json.dumps([{"signal": 1, "entry": 1, "op": "update",
                                "text": "周报用编号列表"}])
        if "SIGNALS-A:" in user:
            return json.dumps([{"decision": "candidate",
                "kind": "potential_new", "item": {
                "text": "Use bullet points in weekly reports.",
                "bucket": "output_contract", "scope_mode": "scoped",
                "applies_when": None,
                "work_kinds": ["report"], "key": "format.structure",
                "confidence": 8},
                "change_candidate": None, "sources": [1]}])
        return json.dumps([{"case": 1, "action": "reaffirm",
                            "targets": [1]}])
    monkeypatch.setattr(llm, "complete", fake)
    ops = V1Provider().extract(
        [{"type": "natural", "text": "说过了，周报一律用 bullet points"},
         {"type": "edited_diff", "raw": "写周报",
          "polished": "写周报，用 bullet points",
          "final": "写周报，用编号列表", "applied": [0]}],
        existing)
    # style op filtered; reinforce translated to the real id AND carries the
    # reinforced rule's text for the bench gist check. Route B keeps its own
    # op vocabulary: an in-place update of the entry the patch used.
    assert ops[0]["kind"] == "reinforce"
    assert ops[0]["target_id"] == existing[0].id
    assert ops[0]["text"] == "周报要用 bullet points"
    assert ops[0]["sources"] == ["说过了，周报一律用 bullet points"]
    assert ops[0]["channel"] == "a"
    assert ops[1] == {"kind": "update", "target_id": existing[0].id,
                      "text": "周报用编号列表", "channel": "b"}
    # A has two calls; B remains one independent call.
    assert ["SIGNALS-A" in p for p in prompts] == [True, False, False]
    assert "CASE 1" in prompts[1] and "周报要用 bullet points" in prompts[1]
    assert '"translator_output"' in prompts[2] and "bullet points" in prompts[2]


def test_an_unedited_patch_never_reaches_route_b(monkeypatch):
    """No diff, no call: an accepted rewrite is not feedback."""
    calls = []
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: calls.append(1) or "[]")
    existing = [Requirement(text="周报要用 bullet points")]
    ops = V1Provider().extract(
        [{"type": "edited_diff", "raw": "写周报",
          "polished": "写周报，用 bullet points",
          "final": "写周报，用 bullet points", "applied": [0]}], existing)
    assert ops == [] and calls == []


def test_consolidate_uses_bucketed_path(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: calls.append(1) or "[]")
    # unique keys → no buckets → zero calls
    existing = [Requirement(text="a", key="email.length"),
                Requirement(text="b", key="code.explanation")]
    assert V1Provider().consolidate(existing) == []
    assert calls == []
