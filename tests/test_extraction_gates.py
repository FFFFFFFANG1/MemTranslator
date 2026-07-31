"""Write gates on extraction ops (LightMem-style: delete only on explicit
revocation; same fact updates instead of duplicating). Measured diseases:
chained stores where task chatter grounded the death of live rules, and one
rule learned as four entries then supersede-chained and mass-retired."""
import sys

sys.path.insert(0, "src")

from memtranslator.extraction import (_dedup_against_store,
                                      _gate_destructive_intent)
from memtranslator.schema import Requirement


def test_retire_without_withdrawal_language_dropped():
    rule = Requirement(text="Keep every bullet point under 17 words.")
    ops = [{"kind": "retire", "target_id": rule.id}]
    # chatter mentions bullets but revokes nothing
    kept, flags = _gate_destructive_intent(
        ops, ["帮我把这周的进展写成 bullet point 列表"], [], [rule])
    assert kept == [] and any("withdrawal" in f for f in flags)


def test_retire_with_withdrawal_language_kept():
    rule = Requirement(text="Keep every bullet point under 17 words.")
    ops = [{"kind": "retire", "target_id": rule.id}]
    kept, _ = _gate_destructive_intent(
        ops, ["bullet point 那条字数限制不用了"], [], [rule])
    assert len(kept) == 1


def test_contradict_not_gated_by_withdrawal_shape():
    rule = Requirement(text="Keep responses under 83 words.")
    ops = [{"kind": "contradict", "target_id": rule.id,
            "text": "Keep responses under 22 words."}]
    kept, _ = _gate_destructive_intent(
        ops, ["以后回复控制在22词以内"], [], [rule])
    assert len(kept) == 1


def test_duplicate_new_becomes_reinforce():
    rule = Requirement(text="Keep responses brief and colloquial, "
                            "omitting needless words.")
    ops = [{"kind": "new",
            "text": "Keep responses brief and colloquial, omitting "
                    "needless words"}]
    kept, flags = _dedup_against_store(ops, [rule])
    assert kept == [{"kind": "reinforce", "target_id": rule.id}]
    assert any("duplicate new" in f for f in flags)


def test_genuinely_new_rule_stays_new():
    rule = Requirement(text="Keep responses brief and colloquial.")
    ops = [{"kind": "new", "text": "Never use emoji in commit messages."}]
    kept, _ = _dedup_against_store(ops, [rule])
    assert kept[0]["kind"] == "new"


def test_numeric_update_never_converted():
    rule = Requirement(text="Keep summaries under 2401 words.")
    ops = [{"kind": "contradict", "target_id": rule.id,
            "text": "Keep summaries under 5043 words."}]
    kept, _ = _dedup_against_store(ops, [rule])
    assert kept[0]["kind"] == "contradict"


def test_no_change_contradict_becomes_reinforce():
    rule = Requirement(text="Keep sentences plain and functional, "
                            "avoiding intricate structures.")
    ops = [{"kind": "contradict", "target_id": rule.id,
            "text": "Keep sentences plain and functional, avoiding "
                    "intricate structures"}]
    kept, flags = _dedup_against_store(ops, [rule])
    assert kept == [{"kind": "reinforce", "target_id": rule.id}]
    assert any("no-change contradict" in f for f in flags)


def test_cross_kind_contradict_downgraded_to_new():
    from memtranslator.extraction import _gate_contradict_facet
    email_cap = Requirement(text="Limit email length to a maximum of 11 "
                                 "sentences.", kinds=["email"])
    ops = [{"kind": "contradict", "target_id": email_cap.id,
            "text": "Write at least 17 complete sentences."}]
    spans = ["帮我写个postmortem，这次至少写17个完整的句子"]
    kept, flags = _gate_contradict_facet(ops, spans, [], [email_cap])
    assert kept[0]["kind"] == "new" and kept[0]["target_id"] is None
    assert any("cross-kind" in f for f in flags)


def test_same_kind_contradict_untouched():
    from memtranslator.extraction import _gate_contradict_facet
    email_cap = Requirement(text="Limit email length to a maximum of 11 "
                                 "sentences.", kinds=["email"])
    ops = [{"kind": "contradict", "target_id": email_cap.id,
            "text": "Limit email length to a maximum of 9 sentences."}]
    spans = ["以后邮件最多9句话"]
    kept, _ = _gate_contradict_facet(ops, spans, [], [email_cap])
    assert kept[0]["kind"] == "contradict"


def test_unknown_kind_never_blocks():
    from memtranslator.extraction import _gate_contradict_facet
    rule = Requirement(text="Keep replies short.")   # untagged, no marker
    ops = [{"kind": "contradict", "target_id": rule.id,
            "text": "Keep replies under 50 words."}]
    kept, _ = _gate_contradict_facet(ops, ["以后回复控制在50词"], [], [rule])
    assert kept[0]["kind"] == "contradict"


def test_polarity_inverted_op_dropped():
    from memtranslator.extraction import _gate_op_fidelity
    ops = [{"kind": "new", "text": "Write at least 11 sentences per email."}]
    spans = ["以后邮件最多11句话，别超过"]
    kept, flags = _gate_op_fidelity(ops, spans, [])
    assert kept == [] and any("polarity-inverted" in f for f in flags)


def test_direction_preserved_op_kept():
    from memtranslator.extraction import _gate_op_fidelity
    ops = [{"kind": "new", "text": "Keep emails to at most 11 sentences."}]
    spans = ["以后邮件最多11句话"]
    kept, _ = _gate_op_fidelity(ops, spans, [])
    assert len(kept) == 1


def test_min_source_min_op_kept():
    from memtranslator.extraction import _gate_op_fidelity
    ops = [{"kind": "new", "text": "Write at least 17 sentences."}]
    spans = ["postmortem 至少写17句"]
    kept, _ = _gate_op_fidelity(ops, spans, [])
    assert len(kept) == 1


def test_ambiguous_or_digitless_never_dropped():
    from memtranslator.extraction import _gate_op_fidelity
    ops = [{"kind": "new", "text": "Avoid emoji in commit messages."},
           {"kind": "new", "text": "Between 8 and 13 words per sentence."}]
    spans = ["别用emoji", "句子长度8到13个词"]
    kept, _ = _gate_op_fidelity(ops, spans, [])
    assert len(kept) == 2
