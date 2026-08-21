import json
import memtranslator.llm as llm
from memtranslator.schema import Requirement
from memtranslator.translate import parse_patch, recall, translate


def _reqs(*texts, status="active"):
    return [Requirement(text=t, status=status) for t in texts]


# ---- parse_patch -----------------------------------------------------------

def test_parse_noop():
    patch, err = parse_patch('{"decision": "noop"}')
    assert patch == {"decision": "noop"} and err is False


def test_parse_apply():
    patch, err = parse_patch(
        '{"decision": "apply", "applied_ids": ["req-1"], '
        '"hunks": [{"old": "x", "new": "y"}]}')
    assert patch["decision"] == "apply" and patch["hunks"][0]["new"] == "y"
    assert err is False


def test_parse_fenced_json():
    patch, err = parse_patch(
        '```json\n{"decision": "apply", "applied_ids": [], '
        '"hunks": [{"old": "x", "new": "y"}]}\n```')
    assert patch["decision"] == "apply" and err is False


def test_parse_trailing_prose():
    # observed flash-model pattern: valid JSON followed by chatter
    patch, err = parse_patch(
        '{"decision": "noop"}\n\nI kept the request unchanged because...')
    assert patch == {"decision": "noop"} and err is False


def test_parse_garbage_degrades_to_noop():
    patch, err = parse_patch("not json at all")
    assert patch == {"decision": "noop"} and err is True


def test_parse_apply_without_hunks_is_noop():
    patch, err = parse_patch('{"decision": "apply"}')
    assert patch == {"decision": "noop"} and err is True


def test_parse_entry_verdicts_derives_applied_numbers():
    patch, err = parse_patch(json.dumps({
        "decision": "apply",
        "entries": [
            {"entry": 1, "verdict": "apply"},
            {"entry": 2, "verdict": "already_satisfied"},
            {"entry": 3, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"},
        ],
        "hunks": [{"old": "x", "new": "y"}],
    }))

    assert err is False
    assert patch["applied"] == [1]
    assert patch["entry_verdicts"] == [
        {"entry": 1, "verdict": "apply"},
        {"entry": 2, "verdict": "already_satisfied"},
        {"entry": 3, "verdict": "not_applicable",
         "reason": "work_kind_mismatch"},
    ]


def test_parse_noop_preserves_entry_verdicts():
    patch, err = parse_patch(json.dumps({
        "decision": "noop",
        "entries": [{"entry": 1, "verdict": "already_satisfied"}],
    }))

    assert err is False
    assert patch == {
        "decision": "noop",
        "entry_verdicts": [
            {"entry": 1, "verdict": "already_satisfied"}],
    }


def test_parse_rejects_duplicate_or_unknown_entry_verdicts():
    duplicate = json.dumps({
        "decision": "noop",
        "entries": [
            {"entry": 1, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"},
            {"entry": 1, "verdict": "already_satisfied"},
        ],
    })
    unknown = json.dumps({
        "decision": "noop",
        "entries": [{"entry": 1, "verdict": "maybe"}],
    })

    assert parse_patch(duplicate) == ({"decision": "noop"}, True)
    assert parse_patch(unknown) == ({"decision": "noop"}, True)


def test_parse_requires_valid_not_applicable_reason():
    missing = json.dumps({
        "decision": "noop",
        "entries": [{"entry": 1, "verdict": "not_applicable"}],
    })
    invalid = json.dumps({
        "decision": "noop",
        "entries": [{"entry": 1, "verdict": "not_applicable",
                     "reason": "does_not_feel_relevant"}],
    })

    assert parse_patch(missing) == ({"decision": "noop"}, True)
    assert parse_patch(invalid) == ({"decision": "noop"}, True)


# ---- recall ----------------------------------------------------------------

def test_recall_filters_retired_without_count_capping_short_globals():
    reqs = [Requirement(text=f"r{i}", kinds=["any"], scope_mode="global",
                        created_at=float(i),
                        updated_at=float(i)) for i in range(40)]
    reqs += _reqs("retired one", status="retired")
    got = recall(reqs)
    assert len(got) == 40
    assert all(r.status == "active" for r in got)
    assert got[0].text == "r0"


# ---- translate -------------------------------------------------------------

def test_translate_apply(monkeypatch):
    reqs = _reqs("Emails under 120 words.")
    rid = reqs[0].id
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps({
        "decision": "apply", "applied_ids": [rid],
        "hunks": [{"old": "Draft an email to my landlord.",
                   "new": "Draft a short email (under 120 words) to my landlord."}]}))
    out = translate("Draft an email to my landlord.", reqs)
    assert out["decision"] == "apply"
    assert out["applied_ids"] == [rid]
    assert out["applied_entries"][0]["id"] == rid
    assert out["applied_entries"][0]["text"] == "Emails under 120 words."
    assert "120 words" in out["polished"]
    assert out["parse_error"] is False


def test_translate_maps_entry_verdicts_to_applied_snapshots(monkeypatch):
    reqs = _reqs("Emails under 120 words.", "Use a professional tone.")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps({
        "decision": "apply",
        "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "under 120 words"},
            {"entry": 2, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"},
        ],
        "hunks": [{"old": "Draft an email.",
                   "new": "Draft an email under 120 words."}],
    }))

    out = translate("Draft an email.", reqs)

    assert out["decision"] == "apply"
    assert out["applied_ids"] == [reqs[0].id]
    assert out["applied_entries"][0]["text"] == "Emails under 120 words."
    assert out["entry_verdicts"][1]["verdict"] == "not_applicable"


def test_translate_keeps_rewrite_but_drops_ungrounded_attribution(monkeypatch):
    req = Requirement(text="Emails must use a professional tone.",
                      kinds=["email"], confidence=8)
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps({
            "decision": "apply",
            "entries": [{"entry": 1, "verdict": "apply"}],
            "hunks": [{"old": "Draft an email.",
                       "new": "Draft a professional email."}],
        })

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", [req])

    assert out["decision"] == "apply"
    assert out["polished"] == "Draft a professional email."
    assert out["applied_ids"] == []
    assert out["entry_contract_warnings"]
    assert len(calls) == 2


def test_translate_does_not_attribute_evidence_that_was_not_added(monkeypatch):
    req = Requirement(text="Emails must use a professional tone.",
                      kinds=["email"], confidence=8)
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps({
            "decision": "apply",
            "entries": [{"entry": 1, "verdict": "apply",
                         "evidence": "email"}],
            "hunks": [{"old": "Draft an email.",
                       "new": "Draft a professional email."}],
        })

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", [req])

    assert out["decision"] == "apply"
    assert out["applied_ids"] == []
    assert out["entry_contract_warnings"]
    assert len(calls) == 2


def test_translate_evidence_matching_ignores_whitespace_only(monkeypatch):
    req = Requirement(text="Emails must stay under 63 words.",
                      kinds=["email"], confidence=8)
    monkeypatch.setattr(llm, "complete", lambda *_args, **_kwargs: json.dumps({
        "decision": "apply",
        "entries": [{"entry": 1, "verdict": "apply",
                     "evidence": "63 词以内"}],
        "hunks": [{"old": "帮我写封邮件",
                   "new": "帮我写封邮件，63词以内"}],
    }))

    out = translate("帮我写封邮件", [req])

    assert out["decision"] == "apply"
    assert out["applied_ids"] == [req.id]


def test_translate_retries_global_not_applicable_during_partial_apply(
        monkeypatch):
    global_rule = Requirement(
        text="Never use emojis in any response.", kinds=["any"],
        scope_mode="global", confidence=8, created_at=1.0)
    email_rule = Requirement(
        text="Emails must use a professional tone.", kinds=["email"],
        confidence=8, created_at=2.0)
    replies = iter([
        {
            "decision": "apply",
            "entries": [
                {"entry": 1, "verdict": "not_applicable",
                 "reason": "work_kind_mismatch"},
                {"entry": 2, "verdict": "apply",
                 "evidence": "professional"},
            ],
            "hunks": [{"old": "Draft an email.",
                       "new": "Draft a professional email."}],
        },
        {
            "decision": "apply",
            "entries": [
                {"entry": 1, "verdict": "apply",
                 "evidence": "without emojis"},
                {"entry": 2, "verdict": "apply",
                 "evidence": "professional"},
            ],
            "hunks": [{"old": "Draft an email.",
                       "new": "Draft a professional email without emojis."}],
        },
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", [email_rule, global_rule])

    assert out["decision"] == "apply"
    assert out["applied_ids"] == [global_rule.id, email_rule.id]
    assert len(users) == 2
    assert "global and cannot be not_applicable" in users[1]


def test_translate_preserves_other_entries_when_global_abstention_persists(
        monkeypatch):
    global_rule = Requirement(
        text="Never use emojis in any response.", kinds=["any"],
        scope_mode="global", confidence=8, created_at=1.0)
    email_rule = Requirement(
        text="Emails must use a professional tone.", kinds=["email"],
        confidence=8, created_at=2.0)
    reply = {
        "decision": "apply",
        "entries": [
            {"entry": 1, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"},
            {"entry": 2, "verdict": "apply", "evidence": "professional"},
        ],
        "hunks": [{"old": "Draft an email.",
                   "new": "Draft a professional email."}],
    }
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps(reply)

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", [email_rule, global_rule])

    assert len(calls) == 2
    assert out["decision"] == "apply"
    assert out["applied_ids"] == [email_rule.id]
    assert out["entry_contract_warnings"] == [
        "[entry 1] is global and cannot be not_applicable"]


def test_translate_fails_closed_on_partial_entry_verdicts(monkeypatch):
    reqs = _reqs("Emails under 120 words.", "Use a professional tone.")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps({
        "decision": "noop",
        "entries": [{"entry": 1, "verdict": "not_applicable",
                     "reason": "work_kind_mismatch"}],
    }))

    out = translate("Draft an email.", reqs)

    assert out["decision"] == "noop"
    assert out["parse_error"] is True
    assert out["reason"] == "entry_verdicts_invalid"


def test_translate_retries_high_confidence_structural_noop(monkeypatch):
    req = Requirement(text="Emails must use a professional tone.",
                      kinds=["email"], confidence=8)
    replies = iter([
        {"decision": "noop", "entries": [
            {"entry": 1, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "professional"}],
         "hunks": [{"old": "Draft an email to the editor.",
                    "new": "Draft a professional email to the editor."}]},
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email to the editor.", [req])

    assert out["decision"] == "apply"
    assert len(users) == 2
    assert "structurally applicable" in users[1]


def test_translate_rechecks_rejected_entry_during_partial_apply(monkeypatch):
    tone = Requirement(text="Emails must use a professional tone.",
                       kinds=["email"], confidence=8, created_at=1.0)
    punctuation = Requirement(text="Do not use hyphens in emails.",
                              kinds=["email"], confidence=8,
                              created_at=2.0)
    replies = iter([
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply", "evidence": "professional"},
            {"entry": 2, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"}],
         "hunks": [{"old": "Draft an email.",
                    "new": "Draft a professional email."}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply", "evidence": "professional"},
            {"entry": 2, "verdict": "apply", "evidence": "without hyphens"}],
         "hunks": [{"old": "Draft an email.",
                    "new": "Draft a professional email without hyphens."}]},
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", [tone, punctuation])

    assert out["decision"] == "apply"
    assert out["applied_ids"] == [tone.id, punctuation.id]
    assert len(users) == 2
    assert "structurally applicable" in users[1]


def test_translate_keeps_valid_apply_when_optional_recheck_is_invalid(
        monkeypatch):
    tone = Requirement(text="Emails must use a professional tone.",
                       kinds=["email"], confidence=8, created_at=1.0)
    punctuation = Requirement(text="Do not use hyphens in emails.",
                              kinds=["email"], confidence=8,
                              created_at=2.0)
    replies = iter([
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply", "evidence": "professional"},
            {"entry": 2, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"}],
         "hunks": [{"old": "Draft an email.",
                    "new": "Draft a professional email."}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply"},
            {"entry": 2, "verdict": "apply"}],
         "hunks": [{"old": "Draft an email.",
                    "new": "Draft a professional email without hyphens."}]},
    ])
    monkeypatch.setattr(
        llm, "complete", lambda *_args, **_kwargs: json.dumps(next(replies)))

    out = translate("Draft an email.", [tone, punctuation])

    assert out["decision"] == "apply"
    assert out["polished"] == "Draft a professional email."
    assert out["applied_ids"] == [tone.id]


def test_translate_does_not_recheck_plausible_false_condition(monkeypatch):
    req = Requirement(
        text="Spell out abbreviations on first use.", kinds=["any"],
        applies_when="when abbreviations appear", confidence=8)
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps({"decision": "noop", "entries": [
            {"entry": 1, "verdict": "not_applicable",
             "reason": "condition_false"}]})

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft a short greeting.", [req])

    assert out["decision"] == "noop"
    assert len(calls) == 1


def test_translate_does_not_retry_low_confidence_noop(monkeypatch):
    req = Requirement(text="Emails must use a professional tone.",
                      kinds=["email"], confidence=4)
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps({"decision": "noop", "entries": [
            {"entry": 1, "verdict": "not_applicable",
             "reason": "work_kind_mismatch"}]})

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email to the editor.", [req])

    assert out["decision"] == "noop"
    assert len(calls) == 1


def test_translate_rechecks_unsupported_numeric_already_satisfied(
        monkeypatch):
    req = Requirement(text="Emails must stay under 120 words.",
                      kinds=["email"], confidence=8)
    replies = iter([
        {"decision": "noop", "entries": [
            {"entry": 1, "verdict": "already_satisfied",
             "evidence": "an email"}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "under 120 words"}],
         "hunks": [{"old": "Draft an email to the editor.",
                    "new": "Draft an email under 120 words to the editor."}]},
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email to the editor.", [req])

    assert out["decision"] == "apply"
    assert len(users) == 2
    assert "not actually present" in users[1]


def test_translate_accepts_supported_numeric_already_satisfied(monkeypatch):
    req = Requirement(text="Emails must stay under 120 words.",
                      kinds=["email"], confidence=8)
    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return json.dumps({"decision": "noop", "entries": [
            {"entry": 1, "verdict": "already_satisfied",
             "evidence": "under 120 words"}]})

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email under 120 words.", [req])

    assert out["decision"] == "noop"
    assert len(calls) == 1


def test_translate_rechecks_numeric_unit_in_already_satisfied(monkeypatch):
    req = Requirement(text="Use at least 13 words.", kinds=["any"],
                      confidence=8)
    replies = iter([
        {"decision": "noop", "entries": [
            {"entry": 1, "verdict": "already_satisfied",
             "evidence": "13-character title"}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "at least 13 words"}],
         "hunks": [{"old": "Write a summary with a 13-character title.",
                    "new": "Write a summary with a 13-character title, "
                           "using at least 13 words in the body."}]},
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Write a summary with a 13-character title.", [req])

    assert out["decision"] == "apply"
    assert len(users) == 2
    assert "number-and-unit" in users[1]


def test_translate_rechecks_numeric_unit_after_apply(monkeypatch):
    req = Requirement(text="Use at least 13 words.", kinds=["any"],
                      confidence=8)
    replies = iter([
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "at least 13 characters"}],
         "hunks": [{"old": "Write a summary.",
                    "new": "Write a summary in at least 13 characters."}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "at least 13 words"}],
         "hunks": [{"old": "Write a summary.",
                    "new": "Write a summary using at least 13 words."}]},
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Write a summary.", [req])

    assert out["polished"] == "Write a summary using at least 13 words."
    assert len(users) == 2
    assert "number-and-unit" in users[1]


def test_translate_rechecks_short_evidence_for_multi_part_rule(monkeypatch):
    req = Requirement(text="Keep emails brief and colloquial.",
                      kinds=["email"], confidence=8)
    replies = iter([
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply", "evidence": "brief"}],
         "hunks": [{"old": "Draft an email.",
                    "new": "Draft a brief email."}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply",
             "evidence": "brief, colloquial"}],
         "hunks": [{"old": "Draft an email.",
                    "new": "Draft a brief, colloquial email."}]},
    ])
    users = []

    def fake(_model, _system, user, **_kwargs):
        users.append(user)
        return json.dumps(next(replies))

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", [req])

    assert out["polished"] == "Draft a brief, colloquial email."
    assert len(users) == 2
    assert "every obligation" in users[1]


def test_translate_freezes_prompt_local_entry_mapping(monkeypatch):
    reqs = _reqs("Emails under 120 words.")

    def fake(*_args, **_kwargs):
        reqs[0].text = "Emails under 80 words."
        return json.dumps({
            "decision": "apply", "applied": [1],
            "hunks": [{"old": "Draft an email.",
                       "new": "Draft an email under 120 words."}]})

    monkeypatch.setattr(llm, "complete", fake)
    out = translate("Draft an email.", reqs)

    assert out["applied_entries"][0]["text"] == "Emails under 120 words."


def test_translate_filters_unknown_applied_ids(monkeypatch):
    reqs = _reqs("A")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps({
        "decision": "apply", "applied_ids": ["req-fabricated"],
        "hunks": [{"old": "do something", "new": "do something, briefly"}]}))
    out = translate("do something", reqs)
    assert out["decision"] == "apply"
    assert out["applied_ids"] == []


def test_translate_no_requirements_short_circuits(monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        return "{}"

    monkeypatch.setattr(llm, "complete", boom)
    out = translate("hello", [])
    assert out["decision"] == "noop"
    assert out["reason"] == "no_active_requirements"
    assert called["n"] == 0  # no LLM call without requirements


def test_translate_prompt_contains_only_retrieved_memory_and_current_request(
        monkeypatch):
    seen = {}

    def fake(_model, system, user, **_kwargs):
        seen["system"] = system
        seen["user"] = user
        return json.dumps({"decision": "noop", "entries": [
            {"entry": 1, "verdict": "already_satisfied"}]})

    monkeypatch.setattr(llm, "complete", fake)
    req = Requirement(text="Emails stay under 120 words.", kinds=["email"])
    out = translate("Draft the launch email under 120 words.", [req])

    assert out["decision"] == "noop"
    assert "Retrieved stored requirements" in seen["user"]
    assert "Pending raw messages" not in seen["user"]
    assert "Pending raw messages" not in seen["system"]


def test_translate_malformed_output_noops(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "MALFORMED")
    out = translate("hello", _reqs("A"))
    assert out["decision"] == "noop"
    assert out["parse_error"] is True


def test_translate_retries_malformed_json_once(monkeypatch):
    replies = iter([
        "MALFORMED",
        json.dumps({
            "decision": "apply",
            "entries": [{"entry": 1, "verdict": "apply",
                         "evidence": "short"}],
            "hunks": [{"old": "Draft an email.",
                       "new": "Draft a short email."}],
        }),
    ])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: next(replies))

    out = translate("Draft an email.", _reqs("Keep emails short."))

    assert out["decision"] == "apply"
    assert out["polished"] == "Draft a short email."


# ---- apply_patch hunks -----------------------------------------------------

def test_apply_hunks_inserts_and_appends():
    from memtranslator.translate import apply_hunks
    out = apply_hunks("给房东写封邮件催修暖气",
                      [{"old": "写封邮件", "new": "写封邮件（不超过120词）"},
                       {"old": "催修暖气", "new": "催修暖气，语气客气点。"}])
    assert out == "给房东写封邮件（不超过120词）催修暖气，语气客气点。"


def test_apply_hunks_rejects_ambiguous_or_missing_old():
    from memtranslator.translate import apply_hunks
    assert apply_hunks("写邮件，再写邮件", [{"old": "写邮件", "new": "x"}]) is None
    assert apply_hunks("写周报", [{"old": "写邮件", "new": "x"}]) is None
    assert apply_hunks("写周报", [{"old": "", "new": "x"}]) is None


def test_translate_assembles_hunks(monkeypatch):
    reqs = _reqs("Emails stay under 120 words")

    def fake(model, system, user, max_tokens=1024, **kw):
        assert "hunks" in system
        return json.dumps({"decision": "apply", "applied": [1],
                           "hunks": [{"old": "写封邮件",
                                      "new": "写封邮件（不超过120词）"}]},
                          ensure_ascii=False)
    monkeypatch.setattr(llm, "complete", fake)
    out = translate("帮我给房东写封邮件催修暖气", reqs)
    assert out["decision"] == "apply"
    assert out["polished"] == "帮我给房东写封邮件（不超过120词）催修暖气"
    assert out["applied_ids"] == [reqs[0].id]


def test_translate_bad_hunk_retries_once_then_noops(monkeypatch):
    users = []

    def fake(model, system, user, max_tokens=1024, **kw):
        users.append(user)
        return json.dumps({"decision": "apply", "applied": [1],
                           "hunks": [{"old": "不存在的锚", "new": "x"}]},
                          ensure_ascii=False)
    monkeypatch.setattr(llm, "complete", fake)
    out = translate("帮我写封邮件", _reqs("Emails stay short"))
    assert out["decision"] == "noop"
    assert out["reason"] == "patch_apply_failed"
    assert len(users) == 2
    assert '[error] previous old "不存在的锚" not found in the request, tool failed' in users[1]
    assert users[1].rstrip().endswith("JSON:")


def test_translate_retries_ambiguous_old_and_applies(monkeypatch):
    users = []

    def fake(model, system, user, max_tokens=1024, **kw):
        users.append(user)
        if len(users) == 1:
            return json.dumps({"decision": "apply", "applied": [1],
                               "hunks": [{"old": "写邮件",
                                          "new": "写邮件（短）"}]},
                              ensure_ascii=False)
        return json.dumps({"decision": "apply", "applied": [1],
                           "hunks": [{"old": "再写邮件给房东",
                                      "new": "再写邮件给房东（短）"}]},
                          ensure_ascii=False)
    monkeypatch.setattr(llm, "complete", fake)
    out = translate("帮我写邮件，再写邮件给房东", _reqs("Emails stay short"))
    assert out["decision"] == "apply"
    assert out["polished"] == "帮我写邮件，再写邮件给房东（短）"
    assert '[error] previous old "写邮件" matched multiple times, tool failed' in users[1]


def test_hunk_retry_keeps_rewrite_when_only_attribution_remains_invalid(
        monkeypatch):
    replies = iter([
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply", "evidence": "短"}],
         "hunks": [{"old": "写邮件", "new": "写邮件（短）"}]},
        {"decision": "apply", "entries": [
            {"entry": 1, "verdict": "apply", "evidence": "email"}],
         "hunks": [{"old": "再写邮件给房东",
                    "new": "再写邮件给房东（短）"}]},
    ])
    monkeypatch.setattr(
        llm, "complete", lambda *_args, **_kwargs: json.dumps(
            next(replies), ensure_ascii=False))

    out = translate("帮我写邮件，再写邮件给房东", _reqs("Emails stay short"))

    assert out["decision"] == "apply"
    assert out["polished"] == "帮我写邮件，再写邮件给房东（短）"
    assert out["applied_ids"] == []
    assert out["entry_contract_warnings"]


def test_apply_hunks_rejects_span_inside_quoted_material():
    from memtranslator.translate import apply_hunks
    text = "帮我看下这段：「All test names use snake_case.」改改语病"
    assert apply_hunks(text, [{"old": "「All", "new": "「All（中文）"}]) is None
    out = apply_hunks(text, [{"old": "改改语病", "new": "改改语病，用简体中文回复"}])
    assert out is not None and "「All test names use snake_case.」" in out
