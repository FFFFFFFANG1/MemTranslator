import bench.runner.run_extraction as rx
from bench.runner.providers import NullProvider
from bench.runner.schema import ExtractionCase


def _case(**kw):
    base = dict(id="l-1", category="natural-explicit", source="handwritten",
                existing=[], events=[{"type": "natural", "text": "以后周报都用 bullet"}],
                expect_ops=[{"kind": "new", "target": None,
                             "gist": "weekly reports in bullets"}])
    base.update(kw)
    return ExtractionCase(**base)


def test_null_provider_fails_extraction_case(monkeypatch):
    r = rx.run_case(_case(), NullProvider())
    assert r["pass"] is False


def test_null_provider_passes_noise_case():
    r = rx.run_case(_case(category="noise-reject-content", expect_ops=[]),
                    NullProvider())
    assert r["pass"] is True


class _OneShot:
    def __init__(self, ops): self.ops = ops
    def extract(self, events, existing): return self.ops


def test_matching_op_passes(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    ops = [{"kind": "new", "target_id": None, "text": "周报用 bullet points"}]
    assert rx.run_case(_case(), _OneShot(ops))["pass"] is True


def test_spurious_op_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    ops = [{"kind": "new", "target_id": None, "text": "周报用 bullet points"},
           {"kind": "new", "target_id": None, "text": "用户不吃麸质"}]
    r = rx.run_case(_case(), _OneShot(ops))
    assert r["pass"] is False


def test_wrong_kind_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="relation",
              existing=["代码只给代码，不解释。"],
              expect_ops=[{"kind": "reinforce", "target": 0,
                           "gist": "code without explanations"}])
    ops = [{"kind": "new", "target_id": None, "text": "代码不要解释"}]
    assert rx.run_case(c, _OneShot(ops))["pass"] is False


def test_retire_matches_mechanically(monkeypatch):
    monkeypatch.setattr(rx, "judge",
                        lambda *a: (_ for _ in ()).throw(AssertionError))
    c = _case(category="revoke", existing=["邮件不超过120词。"],
              events=[{"type": "natural", "text": "邮件不用卡120词了"}],
              expect_ops=[{"kind": "retire", "target": 0}])

    class _Retire:
        def extract(self, events, existing):
            return [{"kind": "retire", "target_id": existing[0].id}]
    assert rx.run_case(c, _Retire())["pass"] is True


def test_retire_wrong_target_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="revoke", existing=["邮件不超过120词。", "代码只给代码。"],
              events=[{"type": "natural", "text": "邮件不用卡120词了"}],
              expect_ops=[{"kind": "retire", "target": 0}])

    class _WrongRetire:
        def extract(self, events, existing):
            return [{"kind": "retire", "target_id": existing[1].id}]
    assert rx.run_case(c, _WrongRetire())["pass"] is False


def test_empty_events_routes_to_consolidate(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="dedup",
              existing=["邮件写短点，120词以内。",
                        "Emails must stay under 120 words.",
                        "代码只给代码。"],
              events=[],
              expect_ops=[{"kind": "merge", "targets": [0, 1],
                           "gist": "emails under 120 words"}])

    class _Merger:
        def extract(self, events, existing):
            raise AssertionError("must call consolidate, not extract")
        def consolidate(self, existing):
            return [{"kind": "merge",
                     "target_ids": [existing[0].id, existing[1].id],
                     "text": "Emails under 120 words."}]
    assert rx.run_case(c, _Merger())["pass"] is True


def test_merge_wrong_target_set_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="dedup", existing=["a", "b", "c"], events=[],
              expect_ops=[{"kind": "merge", "targets": [0, 1], "gist": "ab"}])

    class _OverMerge:
        def consolidate(self, existing):
            return [{"kind": "merge",
                     "target_ids": [r.id for r in existing],   # merged c too
                     "text": "abc"}]
    assert rx.run_case(c, _OverMerge())["pass"] is False


def test_schema_rejects_bad_retire_and_merge(tmp_path):
    import json
    from bench.runner.schema import load_extraction_cases
    base = dict(category="revoke", source="handwritten", existing=["x"],
                events=[], expect_ops=[{"kind": "retire", "target": None}])
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({**base, "id": "b1"}, ensure_ascii=False))
    try:
        load_extraction_cases(p)
        raise AssertionError("retire without target must be rejected")
    except ValueError:
        pass
    p.write_text(json.dumps({**base, "id": "b2", "expect_ops":
                             [{"kind": "merge", "targets": [0]}]},
                            ensure_ascii=False))
    try:
        load_extraction_cases(p)
        raise AssertionError("merge with <2 targets must be rejected")
    except ValueError:
        pass
