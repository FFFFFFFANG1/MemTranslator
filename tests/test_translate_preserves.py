"""The composer text is the user's own words: a rewrite may only ADD.

Regression cover for a real P0 found on 2026-07-25. With several answer-shaped
requirements stored at once ("keep answers short" / "no bullet points" /
"don't restate my question"), the flash translator flipped from rewriting the
request to ANSWERING it — the user's question in the composer would have been
replaced by an answer and then sent onward as if they had typed it. A milder
variant satisfied "don't restate my question" by deleting words out of the
question itself ("环境变量里的 PATH 是怎么被查找的" → "PATH 是怎么被查找的").
"""
import json

import memtranslator.llm as llm
from memtranslator.schema import Requirement
from memtranslator.translate import (_translate_legacy as translate,
                                     preserves_request)


def _reqs(*texts):
    return [Requirement(text=t) for t in texts]


def _patch(monkeypatch, original, polished):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(
        {"decision": "apply", "applied": [],
         "hunks": [{"old": original, "new": polished}]}))


# ---------- the predicate ----------

def test_additive_rewrite_preserved():
    assert preserves_request("给房东写封邮件催修暖气",
                             "给房东写封不超过120词的邮件催修暖气")


def test_light_rewording_tolerated():
    assert preserves_request("给房东写封邮件催修暖气",
                             "给房东写封不超过120词的邮件，催他尽快修暖气")


def test_truncation_rejected():
    assert not preserves_request("环境变量里的 PATH 是怎么被查找的",
                                 "PATH 是怎么被查找的")


def test_answer_substitution_rejected():
    assert not preserves_request(
        "浏览器的同源策略管什么",
        "浏览器的同源策略限制不同源的网页互相访问对方的数据，比如脚本、DOM "
        "或 Cookie，防止恶意网站盗取用户信息。同源指协议、域名和端口都相同。")


def test_long_pasted_material_preserved():
    original = ("把下面的记录整理成周报：周一对了评测口径；周二跑数据管线；"
                "周三写单元测试；周四搭 spike；周五跑通 demo。")
    assert preserves_request(original, original + " 用 bullet points。")


def test_empty_original_is_vacuously_fine():
    assert preserves_request("", "anything")


# ---------- wired into translate ----------

def test_translate_degrades_to_noop_on_destroyed_request(monkeypatch):
    original = "环境变量里的 PATH 是怎么被查找的"
    _patch(monkeypatch, original, "PATH 是怎么被查找的")
    out = translate(original, _reqs("别复述我的问题"))
    assert out["decision"] == "noop" and out["polished"] is None
    assert out["reason"] == "rewrite_dropped_user_text"


def test_translate_degrades_unchanged_apply_to_noop(monkeypatch):
    original = "帮我写封邮件给房东，热水器坏了让他找人来修，全文控制在78词以内"
    _patch(monkeypatch, original, original)
    out = translate(original, _reqs("我让你写的邮件一律不超过78词"))
    assert out["decision"] == "noop" and out["polished"] is None
    assert out["reason"] == "rewrite_unchanged"


def test_translate_keeps_a_legitimate_rewrite(monkeypatch):
    original = "给房东写封邮件催修暖气"
    _patch(monkeypatch, original, "给房东写封不超过120词的邮件，催他尽快修暖气")
    out = translate(original, _reqs("邮件不超过120词"))
    assert out["decision"] == "apply"
    assert "120" in out["polished"]


def test_prompt_keeps_core_meaning_specialization_and_language():
    from memtranslator.translate import TRANSLATOR_SYSTEM
    low = TRANSLATOR_SYSTEM.lower()
    assert "core meaning" in low
    assert "specialize" in low
    assert "language of the request" in low
