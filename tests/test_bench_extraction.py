import bench.suites.run_extraction as rx
from bench.suites.providers import NullProvider
from bench.suites.schema import ExtractionCase


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


def test_empty_events_with_candidate_routes_to_reconcile(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="dedup",
              existing=["邮件写短点，120词以内。",
                        "Emails must stay under 120 words.",
                        "代码只给代码。"],
              events=[],
              candidate={"kind": "potential_new",
                         "item": {"text": "Keep emails under 120 words.",
                                  "bucket": "output_contract", "scope": {},
                                  "work_kinds": ["email"], "key": "email.length",
                                  "confidence": 8},
                         "source_text": "继续120词"},
              expect_ops=[{"kind": "reinforce", "targets": [0, 1],
                           "gist": "emails under 120 words"}])

    class _Reconciler:
        def extract(self, events, existing):
            raise AssertionError("must call reconcile, not extract")
        def consolidate(self, existing):
            raise AssertionError("must call reconcile, not consolidate")
        def reconcile(self, candidate, existing):
            return [{"kind": "reinforce", "target_id": existing[1].id,
                     "text": existing[1].text}]
    assert rx.run_case(c, _Reconciler())["pass"] is True


def test_reinforce_outside_target_set_fails(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(category="dedup", existing=["a", "b", "c"], events=[],
              candidate={"kind": "potential_new",
                         "item": {"text": "a", "bucket": "output_contract",
                                  "scope": {}, "work_kinds": ["any"],
                                  "key": "x", "confidence": 8}},
              expect_ops=[{"kind": "reinforce", "targets": [0, 1],
                           "gist": "ab"}])

    class _Wrong:
        def reconcile(self, candidate, existing):
            return [{"kind": "reinforce", "target_id": existing[2].id,
                     "text": existing[2].text}]
    assert rx.run_case(c, _Wrong())["pass"] is False


def test_deduplicate_accepts_merge_or_reinforce(monkeypatch):
    monkeypatch.setattr(rx, "judge", lambda crit, ctx: (True, False))
    c = _case(
        category="dedup", existing=["same a", "other", "same b"], events=[],
        candidate={"kind": "potential_new",
                   "item": {"text": "same", "bucket": "output_contract",
                            "scope": {}, "work_kinds": ["any"],
                            "key": "format.output", "confidence": 8}},
        expect_ops=[{"kind": "deduplicate", "targets": [0, 2],
                     "gist": "same rule"}])

    class _Result:
        def __init__(self, kind): self.kind = kind
        def reconcile(self, candidate, existing):
            if self.kind == "merge":
                return [{"kind": "merge",
                         "target_ids": [existing[0].id, existing[2].id],
                         "text": "same"}]
            return [{"kind": "reinforce", "target_id": existing[2].id,
                     "text": "same"}]

    assert rx.run_case(c, _Result("merge"))["pass"] is True
    assert rx.run_case(c, _Result("reinforce"))["pass"] is True


def test_schema_rejects_bad_retire_and_merge(tmp_path):
    import json
    from bench.suites.schema import load_extraction_cases
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


def test_schema_rejects_dedup_without_candidate(tmp_path):
    import json
    from bench.suites.schema import load_extraction_cases
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({
        "id": "l-ddp-x", "category": "dedup", "source": "handwritten",
        "existing": ["a", "b"], "events": [],
        "expect_ops": [{"kind": "reinforce", "targets": [0, 1],
                        "gist": "ab"}],
    }, ensure_ascii=False))
    try:
        load_extraction_cases(p)
        raise AssertionError("dedup without candidate must be rejected")
    except ValueError:
        pass
