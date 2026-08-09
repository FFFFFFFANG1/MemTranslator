"""M5: V1Provider adapter — routing, style filtering, silent-batch property."""
import json

import memtranslator.llm as llm
from bench.suites.providers import V1Provider
from memtranslator.schema import Requirement


def test_silent_batch_makes_zero_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: calls.append(1) or "[]")
    ops = V1Provider().extract(
        [{"type": "natural", "text": "帮我给房东写封邮件催修暖气"}], [])
    assert ops == [] and calls == []          # screened out → no LLM call


def test_routes_and_translates_numbered_ops(monkeypatch):
    existing = [Requirement(text="周报要用 bullet points",
                            key="report.format")]
    prompts = []

    def fake(model, system, user, max_tokens=1024, **kw):
        prompts.append(user)
        if "SIGNALS:" in user:                       # route B
            return json.dumps([{"signal": 1, "entry": 1, "op": "update",
                                "text": "周报用编号列表"}])
        return json.dumps([
            {"op": "reinforce", "target": 1, "salience": 4},
            {"op": "style_rule", "text": "约束以从句追加", "salience": 4},
        ])
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
    assert ops == [{"kind": "reinforce", "target_id": existing[0].id,
                    "text": "周报要用 bullet points"},
                   {"kind": "update", "target_id": existing[0].id,
                    "text": "周报用编号列表"}]
    # one prompt per route, each carrying only its own signals
    assert ["SIGNALS-A" in p for p in prompts] == [True, False]
    assert "周报要用 bullet points" in prompts[1]
    assert "<changed>" in prompts[1]


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
