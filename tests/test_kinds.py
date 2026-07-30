"""Work-kind tagging and matching (kinds.py) + recall integration."""
import sys

import pytest

sys.path.insert(0, "src")

from memtranslator import kinds as K
from memtranslator.recall import recall
from memtranslator.schema import Requirement


# ---------------------------------------------------------------- matching
def test_untagged_always_matches():
    assert K.kind_matches([], "email")
    assert K.kind_matches([], None)


def test_any_and_exact_match():
    assert K.kind_matches(["any"], "code")
    assert K.kind_matches(["email"], "email")
    assert not K.kind_matches(["email"], "code")


def test_unknown_task_kind_matches_everything():
    assert K.kind_matches(["code"], None)


def test_prose_family_bridges_report_and_postmortem():
    assert K.kind_matches(["report"], "postmortem")
    assert K.kind_matches(["postmortem"], "report")
    assert not K.kind_matches(["report"], "email")
    assert not K.kind_matches(["report"], "code")


# ---------------------------------------------------------------- inference
def test_context_task_wins_over_text():
    assert K.infer_task_kind("帮我写个脚本", {"task": "email"}) == "email"


def test_context_code_write_maps_to_code():
    assert K.infer_task_kind("x", {"task": "code-write"}) == "code"


def test_lexicon_earliest_marker_wins():
    assert K.infer_task_kind("帮我写封邮件说明这段代码的问题", {}) == "email"


def test_no_marker_gives_none():
    assert K.infer_task_kind("帮我处理一下这个", {}) is None


# ---------------------------------------------------------------- annotate
def test_annotate_parses_and_filters_labels(monkeypatch):
    monkeypatch.setattr(
        K.llm, "complete",
        lambda *a, **kw: '{"1": ["email"], "2": ["any", "bogus"]}')
    out = K.annotate_kinds(["a", "b"])
    assert out == [["email"], ["any"]]


def test_annotate_failure_degrades_to_untagged(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr(K.llm, "complete", boom)
    assert K.annotate_kinds(["a", "b"]) == [[], []]


def test_backfill_tags_only_untagged(monkeypatch):
    class FakeStore:
        def __init__(self, reqs):
            self._r = reqs

        def active(self):
            return self._r

    tagged = Requirement(text="t1", kinds=["code"])
    fresh = Requirement(text="t2")
    monkeypatch.setattr(K, "_annotate_raw", lambda texts: ([["email"]], False))
    n = K.backfill_kinds(FakeStore([tagged, fresh]))
    assert n == 1 and fresh.kinds == ["email"] and tagged.kinds == ["code"]


def test_backfill_retries_only_on_call_failure(monkeypatch):
    class FakeStore:
        def __init__(self, reqs):
            self._r = reqs

        def active(self):
            return self._r

    calls = []
    monkeypatch.setattr(K, "_annotate_raw",
                        lambda texts: (calls.append(1) or ([[]], False)))
    monkeypatch.setattr("time.sleep", lambda s: None)
    K.backfill_kinds(FakeStore([Requirement(text="t")]))
    assert len(calls) == 1          # successful-but-empty: no retry

    calls.clear()
    monkeypatch.setattr(K, "_annotate_raw",
                        lambda texts: (calls.append(1) or ([[]], True)))
    K.backfill_kinds(FakeStore([Requirement(text="t")]))
    assert len(calls) == 3          # call failures: two backoff retries


# ---------------------------------------------------------------- recall
def test_recall_drops_other_kind_rules():
    email_rule = Requirement(text="rule for mail", kinds=["email"])
    code_rule = Requirement(text="rule for programs", kinds=["code"])
    universal = Requirement(text="rule for everything", kinds=["any"])
    legacy = Requirement(text="untagged rule")
    out = recall([email_rule, code_rule, universal, legacy],
                 query="帮我写封邮件催一下进度", context={})
    texts = {r.text for r in out}
    assert texts == {"rule for mail", "rule for everything", "untagged rule"}


def test_recall_unknown_kind_keeps_all():
    rules = [Requirement(text=f"r{i}", kinds=["code"]) for i in range(3)]
    out = recall(rules, query="帮我处理一下", context={})
    assert len(out) == 3


def test_backfill_persists_tags(monkeypatch, tmp_path):
    from memtranslator.store import Store
    s = Store(tmp_path / "s.jsonl")
    s.add("emails stay short", key="email.length")
    monkeypatch.setattr(K, "_annotate_raw", lambda texts: ([["email"]], False))
    K.backfill_kinds(s)
    reloaded = Store(tmp_path / "s.jsonl")
    assert reloaded.active()[0].kinds == ["email"]
