from bench.suites.ablate_e1_retrieval import attribute_then_text_candidates
from bench.suites.analyze_e1_translator import _align_requirement
from memtranslator.schema import Requirement


class _Ranker:
    def rank(self, _query, texts):
        if texts and texts[0].startswith("work_kinds:"):
            return list(reversed(range(len(texts))))
        priorities = {text: rank for rank, text in enumerate(
            ["body-b", "body-c", "body-d", "body-a"])}
        return sorted(range(len(texts)), key=lambda i: priorities[texts[i]])


def test_attribute_pool_precedes_body_final_selection():
    requirements = [
        Requirement(id=letter, text=f"body-{letter}", kinds=["report"],
                    scope_mode="scoped", applies_when=f"attr-{letter}")
        for letter in ("a", "b", "c", "d")]

    pool, final = attribute_then_text_candidates(
        requirements, "body-c", attribute_pool_cap=3, final_cap=2,
        embedding_ranker=_Ranker())

    assert [item.id for item in pool] == ["d", "c", "b"]
    assert {item.id for item in final} == {"b", "c"}
    assert "a" not in {item.id for item in final}


def test_ambiguous_shared_source_does_not_align_to_wrong_sibling():
    source = "one raw message containing two distinct rules"
    golden = {
        "text": "Keep work content formal.",
        "anchor": "formal",
        "key": "tone.formality",
        "scope_mode": "scoped",
        "work_kinds": ["all"],
    }
    sibling = Requirement(
        text="Do not include URLs in examples.",
        key="examples.no_urls", kinds=["any"], scope_mode="scoped",
        sources=[source])

    aligned, method = _align_requirement(
        golden, [source], [sibling], ambiguous_introduction=True)

    assert aligned is None
    assert method == "ambiguous_source_key_mismatch"


def test_ambiguous_shared_source_accepts_known_key_namespace_alias():
    source = "以后都别用 markdown 格式"
    golden = {
        "text": "Do not use Markdown formatting.",
        "anchor": "markdown",
        "key": "format.markdown",
        "scope_mode": "global",
        "work_kinds": ["all"],
    }
    stored = Requirement(
        text="Do not use Markdown formatting in future responses.",
        key="formatting.markdown", kinds=["any"], scope_mode="global",
        sources=[source])

    aligned, method = _align_requirement(
        golden, [source], [stored], ambiguous_introduction=True)

    assert aligned is stored
    assert method == "source+normalized_key"


def test_later_reinforcement_can_align_a_better_global_entry():
    initial = "avoid a juvenile tone in this postmortem"
    reinforced = "keep this rule for every kind of content"
    golden = {
        "text": "Never use a high-school style in any content.",
        "anchor": "high-school",
        "key": "tone.register",
        "scope_mode": "global",
        "work_kinds": ["all"],
    }
    narrow = Requirement(
        text="Avoid a juvenile tone in postmortems.",
        key="tone.no_juvenile", kinds=["postmortem"],
        scope_mode="scoped", sources=[initial])
    broad = Requirement(
        text="Do not use a high-school style in any content.",
        key="tone.no_high_school", kinds=["any"], scope_mode="global",
        sources=[reinforced])

    aligned, method = _align_requirement(
        golden, [initial, reinforced], [narrow, broad])

    assert aligned is broad
    assert method == "source+anchor"
