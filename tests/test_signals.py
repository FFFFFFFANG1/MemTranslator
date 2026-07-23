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
