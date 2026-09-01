from memtranslator.signals import classify_feedback


def _tr(tid, original, polished):
    return {"kind": "translate", "translate_id": tid,
            "original": original, "polished": polished, "decision": "apply"}


def test_exact_match_is_accepted_verbatim():
    tr = _tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件")
    out = classify_feedback("给房东写封不超过120词的邮件", tr)
    assert out["classification"] == "accepted_verbatim"
    assert out["matched_translate_id"] == "tr-1"


def test_edited_after_polish():
    tr = _tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件")
    out = classify_feedback("给房东写封不超过120词的英文邮件，语气强硬点", tr)
    assert out["classification"] == "edited_after_polish"
    assert out["matched_translate_id"] == "tr-1"
    assert 0 < out["similarity"] < 1


def test_reverted_to_original():
    tr = _tr("tr-1", "给房东写邮件催修暖气", "给房东写封不超过120词的邮件催修暖气")
    out = classify_feedback("给房东写邮件催修暖气", tr)
    assert out["classification"] == "reverted"
    assert out["matched_translate_id"] == "tr-1"


def test_large_replacement_remains_linked_by_translate_id():
    tr = _tr("tr-1", "给房东写邮件", "给房东写封不超过120词的邮件")
    out = classify_feedback("看一下这个函数为什么panic", tr)
    assert out["classification"] == "edited_after_polish"
    assert out["matched_translate_id"] == "tr-1"


# ---------- M1 / B1: attribute_diff (0-token span attribution) ----------

from memtranslator.signals import (attribute_diff, compact_message,  # noqa: E402
                                   estimate_input_tokens, patch_diff)

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
    assert hunks and "120" in hunks[0]["old"] and "80" in hunks[0]["new"]


def test_patch_diff_uses_coherent_token_level_replacement():
    """A semantic swap is one replacement, not an unrelated add and delete —
    the shape that made the feedback extractor misread edits."""
    hunks = patch_diff("Meeting notes for today's standup, using bullet points.",
                       "Meeting notes for today's standup, using a table.")
    assert len(hunks) == 1
    assert "bullet points" in hunks[0]["old"]
    assert "a table" in hunks[0]["new"]


def test_patch_diff_keeps_complete_sentence_at_128_tokens():
    prefix = " ".join(f"before{i}" for i in range(63))
    suffix = " ".join(f"after{i}" for i in range(63))
    hunks = patch_diff(f"{prefix} formal {suffix}.", f"{prefix} casual {suffix}.")
    assert len(hunks) == 1
    assert "[truncated]" not in hunks[0]["old"]
    assert hunks[0]["old"].startswith("before0 ")
    assert "formal" in hunks[0]["old"]
    assert hunks[0]["old"].endswith("after62.")


def test_patch_diff_over_128_tokens_keeps_56_tokens_each_side():
    prefix = " ".join(f"before{i}" for i in range(64))
    suffix = " ".join(f"after{i}" for i in range(63))
    hunks = patch_diff(f"{prefix} formal {suffix}.", f"{prefix} casual {suffix}.")
    assert len(hunks) == 1
    assert "formal" in hunks[0]["old"]
    assert "casual" in hunks[0]["new"]
    assert "[truncated]" in hunks[0]["old"]
    # 129 tokens → exactly 56 context tokens each side of the replacement
    assert "before7 " not in hunks[0]["old"]
    assert "before8 " in hunks[0]["old"]
    assert "after55" in hunks[0]["old"]
    assert "after56" not in hunks[0]["old"]


def test_compact_message_keeps_fenced_material_under_budget():
    text = "BEGIN\n```python\nSECRET = 'do not send'\n```\nEND"
    assert compact_message(text, max_tokens=100) == text


def test_compact_message_truncates_the_middle_and_keeps_both_edges():
    text = "BEGIN-" + "甲" * 80 + "MIDDLE-SENTINEL" + "乙" * 80 + "-END"
    compacted = compact_message(text, max_tokens=80)
    assert compacted.startswith("BEGIN-") and compacted.endswith("-END")
    assert "MIDDLE-SENTINEL" not in compacted
    assert "[truncated]" in compacted
    assert estimate_input_tokens(compacted) <= 80
