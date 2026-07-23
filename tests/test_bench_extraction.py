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
