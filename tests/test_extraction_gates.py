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


def test_one_off_grounded_op_dropped():
    from memtranslator.extraction import _gate_one_off
    ops = [{"kind": "contradict", "target_id": "req-x",
            "text": "use MLA for references — except this one time APA"}]
    spans = ["这一回，参考文献格式改成APA，之后恢复MLA"]
    kept, flags = _gate_one_off(ops, spans, [])
    assert kept == [] and any("one-off" in f for f in flags)


def test_durable_marker_overrides_one_off_gate():
    from memtranslator.extraction import _gate_one_off
    ops = [{"kind": "new", "text": "Reports use bullet points."}]
    spans = ["这次开始，以后周报都用 bullet points"]
    kept, _ = _gate_one_off(ops, spans, [])
    assert len(kept) == 1


def test_category_exception_passes_one_off_gate():
    from memtranslator.extraction import _gate_one_off
    ops = [{"kind": "contradict", "target_id": "req-x",
            "text": "Keep emails short — except formal cover letters."}]
    spans = ["以后邮件都写短点，除了正式求职信"]
    kept, _ = _gate_one_off(ops, spans, [])
    assert len(kept) == 1


def test_withdrawal_span_new_dropped_when_entry_alive():
    from memtranslator.extraction import _gate_withdrawal_new
    rule = Requirement(text="Format references in APA style.")
    ops = [{"kind": "new", "text": "Format references in APA style.",
            "key": "reference.format"}]
    spans = ["scratch that APA references rule, just go back to default"]
    kept, flags = _gate_withdrawal_new(ops, spans, [], [rule])
    assert kept == [] and any("withdrawal-span new" in f for f in flags)


def test_withdrawal_new_gate_cross_language_limitation():
    # Documented hole: a zh withdrawal of an en-stored rule shares too few
    # surface tokens to reach reference strength, so the gate passes it
    # through (never-block-on-weak-evidence). Root-lexicon growth is the
    # lever if this class shows up in chained forensics.
    from memtranslator.extraction import _gate_withdrawal_new
    rule = Requirement(text="Format references in APA style.")
    ops = [{"kind": "new", "text": "Format references in APA style."}]
    spans = ["参考文献那条 APA 规则不用了，按默认来"]
    kept, _ = _gate_withdrawal_new(ops, spans, [], [rule])
    assert len(kept) == 1


def test_plain_new_untouched_by_withdrawal_gate():
    from memtranslator.extraction import _gate_withdrawal_new
    ops = [{"kind": "new", "text": "Use serial commas in docs."}]
    spans = ["以后文档里都用 serial comma"]
    kept, _ = _gate_withdrawal_new(ops, spans, [], [])
    assert len(kept) == 1


def test_compound_new_split_into_atoms():
    from memtranslator.extraction import _atomise_ops
    ops = [{"kind": "new", "key": "code.style",
            "text": "Use single quotes for strings; avoid trailing commas "
                    "in generated config"}]
    out, flags = _atomise_ops(ops)
    assert len(out) == 2
    assert out[0]["evidence_id"] == out[1]["evidence_id"]
    assert all(o["kind"] == "new" for o in out)
    assert any("atomised" in f for f in flags)


def test_compound_contradict_keeps_target_on_first_half_only():
    from memtranslator.extraction import _atomise_ops
    ops = [{"kind": "contradict", "target_id": "req-old",
            "text": "Keep emails under 80 words; always sign off with the "
                    "team name"}]
    out, _ = _atomise_ops(ops)
    assert out[0]["kind"] == "contradict" and out[0]["target_id"] == "req-old"
    assert out[1]["kind"] == "new" and out[1]["target_id"] is None


def test_exception_folding_never_split():
    from memtranslator.extraction import _atomise_ops
    ops = [{"kind": "contradict", "target_id": "req-old",
            "text": "Keep emails short — except formal cover letters; those "
                    "may run long"}]
    out, _ = _atomise_ops(ops)
    assert len(out) == 1


def test_semicolon_inside_quotes_is_content():
    from memtranslator.extraction import _atomise_ops
    ops = [{"kind": "new",
            "text": "End every generated statement with `;` in output code"}]
    out, _ = _atomise_ops(ops)
    assert len(out) == 1


def test_trivial_half_never_split():
    from memtranslator.extraction import _atomise_ops
    ops = [{"kind": "new", "text": "Use bullet points in weekly reports; ok"}]
    out, _ = _atomise_ops(ops)
    assert len(out) == 1


def test_misaimed_retire_is_re_pointed_at_named_rule():
    from memtranslator.extraction import _gate_destructive_intent
    columns = Requirement(text="include at least 11 columns of data in "
                               "tables")
    headings = Requirement(text="always include at least 33 engaging "
                                "headings and subheadings")
    ops = [{"kind": "retire", "target_id": columns.id}]
    spans = ["之前说的「always include at least 33 engaging headings and "
             "subheadings」那条不用了，按你默认的来吧"]
    kept, flags = _gate_destructive_intent(ops, spans, [],
                                           [columns, headings])
    assert kept[0]["target_id"] == headings.id
    assert kept[0]["withdrawal"] is True
    assert any("re-aimed" in f for f in flags)


def test_correctly_aimed_retire_untouched():
    from memtranslator.extraction import _gate_destructive_intent
    pylint = Requirement(text="do not run pylint checks on python code")
    other = Requirement(text="keep insights under 67 words")
    ops = [{"kind": "retire", "target_id": pylint.id}]
    spans = ["之前说的「stop running pylint when writing python code」"
             "那条不用了"]
    kept, _ = _gate_destructive_intent(ops, spans, [], [pylint, other])
    assert kept[0]["target_id"] == pylint.id and kept[0]["withdrawal"]


def test_unquoted_withdrawal_still_uses_whole_span():
    from memtranslator.extraction import _gate_destructive_intent
    rule = Requirement(text="keep insights under 67 words")
    ops = [{"kind": "retire", "target_id": rule.id}]
    kept, _ = _gate_destructive_intent(
        ops, ["insights 那个 67 words 的限制不用了"], [], [rule])
    assert len(kept) == 1 and kept[0]["target_id"] == rule.id
