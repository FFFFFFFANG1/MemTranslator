"""M5: V1Provider adapter — routing, style filtering, silent-batch property."""
import json

import memtranslator.llm as llm
from bench.runner.providers import V1Provider
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
    seen = {}

    def fake(model, system, user, max_tokens=1024):
        seen["user"] = user
        return json.dumps([
            {"op": "reinforce", "target": 1, "salience": 4},
            {"op": "style_rule", "text": "约束以从句追加", "salience": 4},
        ])
    monkeypatch.setattr(llm, "complete", fake)
    ops = V1Provider().extract(
        [{"type": "natural", "text": "说过了，周报一律用 bullet points"},
         {"type": "edited_diff", "raw": "r", "polished": "rp",
          "final": "rpf"}],
        existing)
    # style op filtered; reinforce translated to the real id AND carries the
    # reinforced rule's text for the bench gist check
    assert ops == [{"kind": "reinforce", "target_id": existing[0].id,
                    "text": "周报要用 bullet points"}]
    assert "SIGNALS-A" in seen["user"] and "SIGNALS-B" in seen["user"]


def test_consolidate_uses_bucketed_path(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: calls.append(1) or "[]")
    # unique keys → no buckets → zero calls
    existing = [Requirement(text="a", key="email.length"),
                Requirement(text="b", key="code.explanation")]
    assert V1Provider().consolidate(existing) == []
    assert calls == []
