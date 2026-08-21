import bench.suites.judge as judge_mod
from bench.suites.judge import judge


def test_yes_verdict(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: '{"verdict": "yes", "reason": "ok"}')
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is True and flag is False


def test_no_verdict(monkeypatch):
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: '{"verdict": "no", "reason": "missing"}')
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is False and flag is False


def test_garbage_fails_closed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        judge_mod, "_complete",
        lambda *a, **k: calls.append(1) or "hmm, maybe?")
    ok, flag = judge("carries the constraint", {"polished": "x"})
    assert ok is False and flag is True
    assert len(calls) == 2


def test_unparseable_judge_final_retries_once(monkeypatch):
    replies = iter(["", '{"verdict":"yes","reason":"ok"}'])
    monkeypatch.setattr(judge_mod, "_complete",
                        lambda *a, **k: next(replies))

    assert judge("carries the constraint", {"polished": "x"}) == (True, False)


def test_glm_judge_enables_thinking_and_reasoning_headroom(monkeypatch):
    monkeypatch.setattr(judge_mod, "JUDGE_MODEL", "glm-5.3")
    monkeypatch.setattr(judge_mod, "JUDGE_MAX_TOKENS", 8192)

    payload = judge_mod._payload("system", "user")

    assert payload["model"] == "glm-5.3"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["max_tokens"] == 8192


def test_non_glm_judge_disables_thinking(monkeypatch):
    monkeypatch.setattr(judge_mod, "JUDGE_MODEL", "deepseek-v4-pro")
    monkeypatch.setattr(judge_mod, "JUDGE_MAX_TOKENS", 300)

    payload = judge_mod._payload("system", "user")

    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 300


def test_call_can_override_model_for_state_judging():
    payload = judge_mod._payload(
        "system", "user", model="deepseek-v4-pro", max_tokens=300)

    assert payload["model"] == "deepseek-v4-pro"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 300
