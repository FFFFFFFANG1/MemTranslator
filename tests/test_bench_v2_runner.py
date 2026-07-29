"""Offline shakedown of the v2 trace runner: mocked LLM, no network. The
live suite should only ever discover product facts, never runner bugs."""
import json

import pytest

import bench.runner as br


class _FakeLLM:
    """Applies any rule whose text shares a number or a CJK bigram with
    nothing — simplistic: echoes the first store rule as an appended
    constraint, or noops on an empty block."""

    def complete(self, model, system, user, max_tokens=1024,
                 temperature=None):
        block = user.split(":\n", 1)[-1].split("\n\nUser request:")[0]
        req = user.split("User request:\n")[-1].split("\n\nJSON:")[0]
        rules = [l[l.find("]") + 1:].strip() for l in block.splitlines()
                 if l.strip().startswith("- [")]
        if not rules or "帮我" not in req and "draft" not in req:
            return json.dumps({"decision": "noop"})
        return json.dumps({"decision": "apply", "applied_ids": [],
                           "polished": f"{req}（{rules[0]}）"},
                          ensure_ascii=False)


@pytest.fixture(autouse=True)
def wire(monkeypatch):
    fake = _FakeLLM()
    import memtranslator.translate as tr
    monkeypatch.setattr(tr.llm, "complete", fake.complete)
    monkeypatch.setattr(br, "judge", lambda crit, ctx: (True, False))


def test_act_check_passes_with_anchor():
    r = br.run_check({
        "id": "x",
        "store": [{"text": "邮件一律不超过78词"}],
        "task": {"text": "帮我写封邮件给房东"},
        "expect": {"behavior": "act", "must_contain": ["78"]}})
    assert r["pass"], r


def test_noop_expected_but_acted_fails():
    r = br.run_check({
        "id": "x",
        "store": [{"text": "邮件一律不超过78词"}],
        "task": {"text": "帮我写封邮件给房东"},
        "expect": {"behavior": "noop"}})
    assert not r["pass"]


def test_must_not_contain_catches_leak():
    r = br.run_check({
        "id": "x",
        "store": [{"text": "邮件一律不超过120词"}],
        "task": {"text": "帮我写封邮件给房东"},
        "expect": {"behavior": "act", "must_not_contain": ["120"]}})
    assert not r["pass"] and any("leaked" in f for f in r["fails"])


def test_equiv_group_divergence_fails_both():
    a = br.run_check({
        "id": "a", "equiv_group": "g",
        "store": [{"text": "邮件一律不超过78词"}],
        "task": {"text": "帮我写封邮件给房东"},
        "expect": {"behavior": "act", "must_contain": ["78"]}})
    b = br.run_check({
        "id": "b", "equiv_group": "g",
        "store": [{"text": "会议纪要按时间倒序"}],   # different anchor hits
        "task": {"text": "帮我写封邮件给房东"},
        "expect": {"behavior": "act", "must_contain": ["78"]}})
    extra = br.check_equiv_groups([a, b])
    assert not extra[0]["pass"]
    assert not a["pass"] and not b["pass"]


def test_store_age_rank_orders_created_at():
    reqs = br.build_store([{"text": "old", "age_rank": 0},
                           {"text": "new", "age_rank": 5}])
    assert reqs[1].created_at > reqs[0].created_at


def test_all_trace_files_parse_and_validate():
    seen_ids = set()
    for p in sorted(br.TRACES.glob("trace_id_read_*.json")):
        fam = json.loads(p.read_text())
        assert fam["family"] and fam["checks"], p.name
        for c in fam["checks"]:
            assert c["id"] not in seen_ids, f"duplicate id {c['id']}"
            seen_ids.add(c["id"])
            assert "task" in c and "store" in c and "expect" in c
            if c.get("mode") == "instantiation":
                assert c["store"], "instantiation needs store[0] = rule"
                assert "min_tier" in c["expect"]
            else:
                assert c["expect"].get("behavior") or \
                    c["expect"].get("judge") or \
                    c["expect"].get("must_contain") or \
                    c["expect"].get("must_not_contain"), c["id"]
    assert len(seen_ids) >= 30
