from memtranslator.signals import classify_submit


def _tr(tid, original, polished, at):
    return {"kind": "translate", "translate_id": tid, "at": at,
            "original": original, "polished": polished, "decision": "apply"}


def test_exact_match_is_accepted_verbatim():
    trs = [_tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("给房东写封不超过120词的邮件", 1100.0, trs)
    assert out["classification"] == "accepted_verbatim"
    assert out["matched_translate_id"] == "tr-1"


def test_edited_after_polish():
    trs = [_tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("给房东写封不超过120词的英文邮件，语气强硬点", 1100.0, trs)
    assert out["classification"] == "edited_after_polish"
    assert out["matched_translate_id"] == "tr-1"
    assert 0 < out["similarity"] < 1


def test_reverted_to_original():
    trs = [_tr("tr-1", "给房东写邮件催修暖气", "给房东写封不超过120词的邮件催修暖气", 1000.0)]
    out = classify_submit("给房东写邮件催修暖气", 1100.0, trs)
    assert out["classification"] == "reverted"
    assert out["matched_translate_id"] == "tr-1"


def test_unrelated_text_is_natural():
    trs = [_tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("看一下这个函数为什么panic", 1100.0, trs)
    assert out["classification"] == "natural"
    assert out["matched_translate_id"] is None


def test_out_of_window_is_natural():
    trs = [_tr("tr-1", "a", "给房东写封不超过120词的邮件", 1000.0)]
    out = classify_submit("给房东写封不超过120词的邮件", 1000.0 + 3600, trs)
    assert out["classification"] == "natural"


def test_latest_matching_translate_wins():
    trs = [_tr("tr-1", "x", "版本一的润色结果", 1000.0),
           _tr("tr-2", "x", "版本二的润色结果", 1200.0)]
    out = classify_submit("版本二的润色结果", 1300.0, trs)
    assert out["matched_translate_id"] == "tr-2"


# ---------- M1 / B1: attribute_diff (0-token span attribution) ----------

from memtranslator.signals import (attribute_diff, patch_diff,  # noqa: E402
                                   screen_message)

RAW = "给房东写封邮件催修暖气"
POLISHED = "给房东写封不超过120词的邮件，催他尽快修暖气"


def test_attr_accepted_verbatim():
    a = attribute_diff(RAW, POLISHED, POLISHED)
    assert a["verdict"] == "accepted" and a["strength_delta"] == +1


def test_attr_reverted():
    a = attribute_diff(RAW, POLISHED, RAW)
    assert a["verdict"] == "reverted" and a["strength_delta"] == -1


def test_attr_partial_injection_removed():
    final = "给房东写封邮件，催他修暖气，语气强硬点"
    a = attribute_diff(RAW, POLISHED, final)
    assert a["verdict"] == "partial"
    assert a["injection_survival"] == "removed"
    assert a["strength_delta"] == -1


def test_attr_partial_injection_kept_with_additions():
    final = POLISHED + "，用英文写"
    a = attribute_diff(RAW, POLISHED, final)
    assert a["verdict"] == "partial"
    assert a["injection_survival"] == "kept"
    assert a["strength_delta"] == +1
    assert any("英文" in s for s in a["user_added"])


def test_attr_no_injection_noop_translate():
    a = attribute_diff(RAW, RAW, RAW + "，谢谢")
    assert a["verdict"] == "partial" and a["strength_delta"] == 0


# ---------- Route B: patch_diff (0-token sentence-level human edits) ----------

def test_patch_diff_is_empty_until_user_changes_agent_patch():
    assert patch_diff(POLISHED, POLISHED) == []
    hunks = patch_diff(POLISHED, POLISHED.replace("120", "80"))
    assert hunks and hunks[0]["op"] == "replace"
    assert "<changed>120</changed>" in hunks[0]["before_sentence"]
    assert "<changed>80</changed>" in hunks[0]["after_sentence"]


def test_patch_diff_uses_coherent_token_level_replacement():
    """A semantic swap is one replacement, not an unrelated add and delete —
    the shape that made the feedback extractor misread edits."""
    hunks = patch_diff("Meeting notes for today's standup, using bullet points.",
                       "Meeting notes for today's standup, using a table.")
    assert len(hunks) == 1 and hunks[0]["op"] == "replace"
    assert "<changed>bullet points</changed>" in hunks[0]["before_sentence"]
    assert "<changed>a table</changed>" in hunks[0]["after_sentence"]


def test_patch_diff_keeps_complete_sentence_at_128_tokens():
    prefix = " ".join(f"before{i}" for i in range(63))
    suffix = " ".join(f"after{i}" for i in range(63))
    hunks = patch_diff(f"{prefix} formal {suffix}.", f"{prefix} casual {suffix}.")
    assert len(hunks) == 1
    assert "[truncated]" not in hunks[0]["before_sentence"]
    assert hunks[0]["before_sentence"].startswith("before0 ")
    assert "<changed>formal</changed>" in hunks[0]["before_sentence"]
    assert hunks[0]["before_sentence"].endswith("after62.")


def test_patch_diff_over_128_tokens_keeps_56_tokens_each_side():
    prefix = " ".join(f"before{i}" for i in range(64))
    suffix = " ".join(f"after{i}" for i in range(63))
    hunks = patch_diff(f"{prefix} formal {suffix}.", f"{prefix} casual {suffix}.")
    assert len(hunks) == 1
    assert "<changed>formal</changed>" in hunks[0]["before_sentence"]
    assert "<changed>casual</changed>" in hunks[0]["after_sentence"]
    assert "[truncated]" in hunks[0]["before_sentence"]
    # 129 tokens → exactly 56 context tokens each side of the replacement
    assert "before7 " not in hunks[0]["before_sentence"]
    assert "before8 " in hunks[0]["before_sentence"]
    assert "after55" in hunks[0]["before_sentence"]
    assert "after56" not in hunks[0]["before_sentence"]


# ---------- M1 / Route A: screen_message (0-token sentence screening) ----------

def test_scr_rule_setting_sentence_hits():
    spans = screen_message("以后我让你写周报，一律用 bullet points，别写大段落")
    assert spans and "bullet" in spans[0]


def test_scr_plain_task_request_does_not_hit():
    assert screen_message("帮我给房东写封邮件，催他修一下暖气") == []
    assert screen_message("write a python function that dedupes a list") == []


def test_scr_correction_inside_pasted_document_is_localized():
    doc_lines = [f"第{i}段：这一部分是文档正文，讲的是系统架构的背景介绍，"
                 f"篇幅比较长，只是粘贴进来的材料而不是对话。"
                 for i in range(8)]
    msg = ("帮我把下面的文档整理一下。"
           + "".join(doc_lines)
           + "对了，以后整理文档一律输出成 markdown 格式。")
    spans = screen_message(msg)
    assert len(spans) >= 1
    joined = "".join(spans)
    assert "markdown" in joined
    assert "第3段" not in joined          # material zone stays out
    assert sum(len(s) for s in spans) <= 600


def test_scr_code_block_is_material():
    msg = ("这个函数帮我看看：\n```\nfor i in range(10):\n"
           "    print('以后都要 记住 必须')\n```\n谢谢")
    spans = screen_message(msg)
    assert all("print" not in s for s in spans)


def test_scr_english_rule_setting_hits():
    spans = screen_message(
        "From now on, always include type hints in python code you write.")
    assert spans


def test_scr_existing_key_mention_boosts():
    weak = "邮件的语气这块正式一点吧"
    assert screen_message(weak) == []
    assert screen_message(weak, existing_keys=["email.tone"]) != []


def test_scr_withdrawal_hits_with_meta_but_not_alone():
    assert screen_message("邮件不用卡120词了，正常写就行") != []
    assert screen_message("不用谢") == []
    assert screen_message("这个不用了，换下一个话题") == []


def test_scr_english_correction_phrasings_hit():
    assert screen_message("You made it too formal; I need a friendly tone.") != []
    assert screen_message(
        "I said give me key points, not a summary of everything. Be concise.") != []


def test_scr_restatement_hits():
    assert screen_message("又来了，说了多少次代码别带解释，直接给代码") != []
    assert screen_message("我再说一遍，提交信息里不要加表情符号，烦死了") != []


# ---------- 2026-07-29 write-path fixes: en screening + store-aware boost ----


def test_scr_en_multisentence_rule_not_masked_as_material():
    """Three ordinary English sentences used to trip the pasted-material
    mask (80 chars ≈ one normal en sentence) and hide the rule; measured
    as the en-persona extraction collapse (assert recall 0.57 vs zh 0.97)."""
    msg = ("Could you put together the quarterly figures for the sales team "
           "and add a short intro paragraph on methodology? "
           "That last summary you sent was way too formal for an internal "
           "update, we are a small team and it read like a legal filing. "
           "From now on keep internal updates casual and skip the "
           "boilerplate disclaimers entirely please.")
    spans = screen_message(msg)
    assert spans and any("casual" in s for s in spans)


def test_scr_en_period_splits_sentences():
    """Latin full stops end sentences (before whitespace only), so one
    rule-bearing sentence no longer drags a whole unsplit turn through."""
    msg = ("Never use abbreviations in changelog entries. The deploy went "
           "fine yesterday and the metrics dashboard is back up.")
    spans = screen_message(msg)
    assert spans and "abbreviations" in spans[0]
    # decimals and filenames survive unsplit
    assert screen_message("run perf.py and report 0.85 as the ratio") == []


def test_scr_withdrawal_by_quotation_needs_store_to_fire():
    """A withdrawal that quotes a stored rule scores WITHDRAW only — one
    short of the threshold — unless the store overlap boost recognises the
    quoted vocabulary (retire screening recall was 0.59-0.64 without it)."""
    msg = "之前那条「结尾附上参考链接清单」的规则不用了"
    assert screen_message(msg) == []
    assert screen_message(msg, existing_texts=["结尾附上参考链接清单"]) != []


def test_scr_store_overlap_handles_plural_and_long_word():
    msg = "Cancel that rule, I no longer need the notification timing restriction."
    assert screen_message(
        msg, existing_texts=["Notifications must be sent before 5pm."]) != []


def test_scr_store_overlap_does_not_fire_plain_tasks():
    assert screen_message(
        "write a python function that dedupes a list",
        existing_texts=["always include type hints in python code"]) == []
    assert screen_message(
        "不用谢", existing_texts=["邮件一律不超过120词"]) == []


def test_scr_reinforce_idiom_hits():
    assert screen_message("对了，结尾要附参考链接这条继续保持啊") != []


def test_referent_hints_annotate_prompt():
    from memtranslator.extraction import build_user_prompt
    from memtranslator.schema import Requirement
    existing = [Requirement(text="周报每条进展要附数据链接"),
                Requirement(text="代码注释一律用英文写")]
    prompt = build_user_prompt(["周报的数据链接不用附了"], [], existing)
    assert "[shares vocabulary with entries [1]]" in prompt
    prompt2 = build_user_prompt(["以后开会纪要按时间排"], [], existing)
    assert "shares vocabulary" not in prompt2
