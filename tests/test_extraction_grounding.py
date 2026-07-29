"""The grounding guard: destructive ops (contradict/retire) must target an
entry sharing vocabulary with what the user said this batch. Offline —
exercises _ground_destructive_ops directly, no LLM."""
from memtranslator.extraction import _ground_destructive_ops
from memtranslator.schema import Requirement


def _store():
    return [Requirement(text="会议纪要一律按时间倒序排列", key="meeting.format")]


def test_ungrounded_contradict_downgrades_to_new():
    store = _store()
    ops = [{"kind": "contradict", "target_id": store[0].id,
            "text": "实验设计和postmortem分析直接给结论，不用免责声明。",
            "key": "analysis.structure", "scope": {}, "salience": 4,
            "bucket": "", "polarity": "", "evidence_id": ""}]
    kept, flags = _ground_destructive_ops(
        ops, ["以后都别用原来那条指令里的免责声明和结构了，直接给结论。"], [], store)
    assert flags and "ungrounded contradict" in flags[0]
    assert len(kept) == 1 and kept[0]["kind"] == "new"      # content survives
    assert kept[0]["target_id"] is None                     # the kill does not


def test_ungrounded_retire_dropped_entirely():
    store = _store()
    ops = [{"kind": "retire", "target_id": store[0].id}]
    kept, flags = _ground_destructive_ops(
        ops, ["之前那条不用了"], [], store)
    assert kept == [] and flags


def test_grounded_contradict_passes():
    store = [Requirement(text="我让你写的邮件一律不超过120词", key="email.length")]
    ops = [{"kind": "contradict", "target_id": store[0].id,
            "text": "邮件放宽到78词以内", "key": "email.length", "scope": {},
            "salience": 4, "bucket": "", "polarity": "", "evidence_id": ""}]
    kept, flags = _ground_destructive_ops(
        ops, ["邮件别卡120词了，78词以内就行"], [], store)
    assert flags == []
    assert kept[0]["kind"] == "contradict"


def test_grounded_retire_passes():
    store = [Requirement(text="我让你写的邮件一律不超过120词", key="email.length")]
    ops = [{"kind": "retire", "target_id": store[0].id}]
    kept, flags = _ground_destructive_ops(
        ops, ["邮件不用卡120词了，想写多长写多长"], [], store)
    assert flags == [] and kept[0]["kind"] == "retire"


def test_diff_channel_signals_also_ground():
    store = [Requirement(text="我让你写的邮件一律不超过120词", key="email.length")]
    ops = [{"kind": "retire", "target_id": store[0].id}]
    kept, flags = _ground_destructive_ops(
        ops, [], [{"raw": "写封邮件催发票", "polished": "写封邮件催发票（不超过120词）",
                   "final": "写封邮件催发票，长度随意"}], store)
    assert flags == [] and kept


def test_non_destructive_ops_untouched():
    store = _store()
    ops = [{"kind": "new", "text": "无关的新规则", "key": "", "scope": {},
            "salience": 4, "bucket": "", "polarity": "", "evidence_id": ""},
           {"kind": "reinforce", "target_id": store[0].id}]
    kept, flags = _ground_destructive_ops(ops, ["随便什么信号"], [], store)
    assert len(kept) == 2 and flags == []
