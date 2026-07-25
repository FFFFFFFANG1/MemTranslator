"""M4: deterministic recall — scope filter, cap ordering, style separation."""
import json

import memtranslator.llm as llm
from memtranslator.config import RECALL_CAP
from memtranslator.recall import recall, style_block
from memtranslator.schema import Requirement
from memtranslator.translate import translate


def _r(text, **kw):
    return Requirement(text=text, **kw)


def test_scope_filter_excludes_mismatched_task():
    reqs = [_r("邮件写短", scope={"task": "email"}),
            _r("代码只给代码", scope={"task": "code"}),
            _r("全局规则")]
    got = recall(reqs, context={"task": "email"})
    texts = [r.text for r in got]
    assert "邮件写短" in texts and "全局规则" in texts
    assert "代码只给代码" not in texts


def test_missing_context_dimension_keeps_scoped_entries():
    reqs = [_r("邮件写短", scope={"task": "email"})]
    assert len(recall(reqs, context={})) == 1
    assert len(recall(reqs)) == 1


def test_style_rules_never_join_recall():
    reqs = [_r("正常规则"), _r("style", kind="style_rule")]
    assert [r.text for r in recall(reqs)] == ["正常规则"]


def test_over_cap_prefers_key_hits_then_recency():
    old_hit = _r("邮件规则", key="email.length", created_at=1.0)
    fillers = [_r(f"规则{i}", key=f"f{i}.a", created_at=100.0 + i)
               for i in range(RECALL_CAP)]
    got = recall([old_hit] + fillers, query="帮我写封邮件给教授")
    assert len(got) == RECALL_CAP
    assert old_hit in got                     # key hit beats pure recency


def test_style_block_caps_and_formats():
    reqs = [_r(f"style rule {i}", kind="style_rule") for i in range(12)]
    block = style_block(reqs)
    assert block.count("- ") == 10            # STYLE_RULE_CAP
    assert style_block([_r("普通规则")]) == ""


def test_translate_injects_style_rules(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["system"] = system
        return json.dumps({"decision": "noop"})
    monkeypatch.setattr(llm, "complete", fake)
    reqs = [_r("邮件写短"),
            _r("保留用户原句式，约束以从句追加", kind="style_rule")]
    translate("帮我写封邮件", reqs)
    assert "保留用户原句式" in seen["system"]


def test_translate_system_unchanged_without_styles(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["system"] = system
        return json.dumps({"decision": "noop"})
    monkeypatch.setattr(llm, "complete", fake)
    from memtranslator.translate import TRANSLATOR_SYSTEM
    translate("帮我写封邮件", [_r("邮件写短")])
    assert seen["system"] == TRANSLATOR_SYSTEM
