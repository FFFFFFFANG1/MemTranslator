"""Recall: independent global and ranked non-global lanes."""
import json

import memtranslator.llm as llm
from memtranslator.recall import recall, style_block
from memtranslator.retrieval import (flatten_applicability_fields,
                                     rerank_by_best_rank,
                                     rerank_by_rank_sum)
from memtranslator.schema import Requirement
from memtranslator.translate import _translate_legacy as translate


def _r(text, **kw):
    return Requirement(text=text, **kw)


def test_metadata_only_document_excludes_requirement_text_and_key():
    document = flatten_applicability_fields(
        work_kinds=["all"], applies_when="when abbreviations appear")

    assert document == (
        "work_kinds: all\n"
        "applies_when: when abbreviations appear\n"
        "legacy_scope: {}")
    assert "requirement text" not in document
    assert "key:" not in document


def test_recall_does_not_hard_filter_non_global_work_kinds():
    reqs = [_r("邮件写短", kinds=["email"]),
            _r("代码只给代码", kinds=["code"]),
            _r("全局规则")]
    got = recall(reqs, context={"task": "email"})
    assert {r.text for r in got} == {"邮件写短", "代码只给代码", "全局规则"}


def test_legacy_scope_task_migrates_into_kinds():
    reqs = [_r("邮件写短", scope={"task": "email"}),
            _r("代码只给代码", scope={"task": "code"})]
    got = recall(reqs, context={"task": "email"})
    assert {r.text for r in got} == {"邮件写短", "代码只给代码"}
    assert reqs[0].kinds == ["email"] and reqs[0].scope == {}


def test_known_scope_conflict_does_not_hard_exclude_scoped_rule():
    reqs = [_r("给 Smith 的邮件加联系方式", kinds=["email"],
               scope={"audience": "smith"}),
            _r("邮件写短", kinds=["email"])]
    got = recall(reqs, context={"task": "email", "audience": "jones"})
    assert {r.text for r in got} == {"给 Smith 的邮件加联系方式", "邮件写短"}


def test_style_rules_never_join_recall():
    reqs = [_r("正常规则"), _r("style", kind="style_rule")]
    assert [r.text for r in recall(reqs)] == ["正常规则"]


def test_recall_uses_text_only_hybrid_ranking_for_non_global_top16():
    class Dense:
        def __init__(self):
            self.calls = []

        def rank(self, query, texts):
            self.calls.append(texts)
            return list(range(len(texts)))

    old_hit = _r("邮件规则", key="email.length", kinds=["email"],
                 created_at=1.0)
    fillers = [_r(f"规则{i}", key=f"f{i}.a", kinds=["email"],
                  created_at=100.0 + i)
               for i in range(40)]
    dense = Dense()
    got = recall([old_hit] + fillers, query="帮我写封邮件给教授",
                 embedding_ranker=dense)
    assert len(got) == 16
    assert old_hit in got
    assert dense.calls[0][0] == "邮件规则"
    assert dense.calls[1][0].startswith("work_kinds: email\n")


def test_optional_attribute_pool_admits_before_body_top_k(monkeypatch):
    import memtranslator.recall as recall_mod

    def fake_sparse(_query, texts, *, positive_only=False):
        assert positive_only is True
        return list(range(len(texts)))

    class Dense:
        def rank(self, _query, texts):
            if texts[0].startswith("work_kinds:"):
                return list(reversed(range(len(texts))))
            return list(reversed(range(len(texts))))

    monkeypatch.setattr(recall_mod, "SCOPED_RECALL_CAP", 2)
    monkeypatch.setattr(
        recall_mod, "SCOPED_ATTRIBUTE_POOL_CAP", 3, raising=False)
    monkeypatch.setattr(recall_mod, "sparse_order", fake_sparse)
    reqs = [
        _r(f"body-{letter}", kinds=[f"kind-{letter}"],
           applies_when=f"condition-{letter}", created_at=float(index))
        for index, letter in enumerate(("a", "b", "c", "d"))]

    got = recall(reqs, query="condition-d", embedding_ranker=Dense())

    assert {item.text for item in got} == {"body-b", "body-d"}


def test_recall_keeps_all_short_globals_even_above_ten_items():
    reqs = [_r(f"r{i}", kinds=["any"], scope_mode="global",
               created_at=float(i), updated_at=float(i))
            for i in range(40)]

    got = recall(reqs, query="")

    assert [r.text for r in got] == [f"r{i}" for i in range(40)]


def test_over_budget_globals_use_strength_then_recency(monkeypatch):
    import memtranslator.recall as recall_mod

    old = _r("旧" + "甲" * 700, kinds=["any"], scope_mode="global",
             strength=1,
             created_at=1.0, updated_at=1.0)
    strong = _r("强" + "乙" * 700, kinds=["any"], scope_mode="global",
                strength=2,
                created_at=2.0, updated_at=2.0)
    recent = _r("新" + "丙" * 700, kinds=["any"], scope_mode="global",
                strength=1,
                created_at=3.0, updated_at=3.0)
    two_rule_budget = recall_mod.requirement_block_tokens([strong, recent])
    assert recall_mod.requirement_block_tokens(
        [strong, recent, old]) > two_rule_budget
    monkeypatch.setattr(
        recall_mod, "GLOBAL_RECALL_MAX_TOKENS", two_rule_budget)

    got = recall([old, strong, recent])

    assert got == [strong, recent]
    assert recall_mod.requirement_block_tokens(got) <= two_rule_budget


def test_global_token_budget_counts_visible_prompt_metadata():
    import memtranslator.recall as recall_mod

    plain = _r("Keep it concise.")
    annotated = _r(
        "Keep it concise.", kinds=["any"], bucket="output_contract",
        key="response.length", confidence=9)

    assert recall_mod.requirement_block_tokens([annotated]) \
        > recall_mod.requirement_block_tokens([plain])


def test_global_and_scoped_lanes_do_not_compete_for_capacity():
    class Dense:
        def rank(self, query, texts):
            return list(range(len(texts)))

    globals_ = [
        _r(f"global {i}", kinds=["any"], scope_mode="global", confidence=9,
           created_at=float(i))
        for i in range(12)
    ]
    emails = [_r(f"email {i}", kinds=["email"], confidence=8,
                 created_at=100.0 + i) for i in range(12)]
    reports = [_r(f"report {i}", kinds=["report"], confidence=8,
                  created_at=200.0 + i) for i in range(12)]

    got = recall(
        globals_ + emails + reports, query="draft email volcano",
        context={"task": "email"}, embedding_ranker=Dense())

    assert len(got) == 28
    assert sum(r.text.startswith("global") for r in got) == 12
    assert sum(r.text.startswith("email") for r in got) == 12
    assert sum(r.text.startswith("report") for r in got) == 4


def test_only_explicit_all_plus_global_enters_the_global_lane():
    legacy = _r("legacy untagged")
    inferred_all = _r("all but not declared", kinds=["any"])
    declared = _r("declared global", kinds=["any"], scope_mode="global")

    assert legacy.scope_mode == "scoped"
    assert inferred_all.scope_mode == "scoped"
    assert declared.scope_mode == "global"


def test_scoped_sparse_and_dense_routes_use_raw_query(monkeypatch):
    import memtranslator.recall as recall_mod

    seen = {}

    def fake_sparse(query, texts, *, positive_only=False):
        seen["sparse_query"] = query
        seen["sparse_texts"] = texts
        seen["positive_only"] = positive_only
        return list(range(len(texts)))

    class Dense:
        def rank(self, query, texts):
            seen["dense_query"] = query
            seen.setdefault("dense_texts", []).append(texts)
            return list(reversed(range(len(texts))))

    monkeypatch.setattr(recall_mod, "sparse_order", fake_sparse)
    reqs = [_r(f"email rule {i}", kinds=["email"],
               key=f"email.facet_{i}") for i in range(17)]

    recall(reqs, query="draft the launch email",
           context={"task": "email"}, embedding_ranker=Dense())

    assert seen["sparse_query"] == "draft the launch email"
    assert seen["positive_only"] is True
    assert seen["sparse_texts"] == seen["dense_texts"][0]
    assert seen["dense_query"] == "draft the launch email"
    assert seen["dense_texts"][0] == [f"email rule {i}" for i in range(17)]
    assert seen["dense_texts"][1][0].startswith("work_kinds: email\n")


def test_scoped_candidates_rerank_by_best_route_then_rank_sum():
    candidates = [4, 3, 2, 1, 0]
    sparse = [4, 3, 2, 1, 0]
    dense = [0, 1, 2, 3, 4]

    assert rerank_by_best_rank(candidates, sparse, dense) == [4, 0, 3, 1, 2]


def test_fixed_union_blends_text_and_applicability_rank_sums():
    candidates = [4, 0, 3, 1, 2]
    applicability = [1, 0, 4, 3, 2]

    assert rerank_by_rank_sum(
        candidates, candidates, applicability) == [4, 0, 1, 3, 2]


def test_recall_reuses_the_unchanged_bm25_corpus_between_queries():
    from memtranslator.retrieval import (clear_retrieval_caches,
                                         retrieval_cache_info)

    clear_retrieval_caches()
    reqs = [_r(f"Keep email rule {i} concise.", kinds=["email"],
               key=f"email.rule_{i}") for i in range(17)]
    recall(reqs, query="draft an email")
    first = retrieval_cache_info()["bm25_corpora"]
    recall(reqs, query="reply to this email")
    second = retrieval_cache_info()["bm25_corpora"]

    assert second["misses"] == first["misses"]
    assert second["hits"] == first["hits"] + 1


def test_style_block_caps_and_formats():
    reqs = [_r(f"style rule {i}", kind="style_rule") for i in range(12)]
    block = style_block(reqs)
    assert block.count("- ") == 10            # STYLE_RULE_CAP
    assert style_block([_r("普通规则")]) == ""


def test_translate_injects_style_rules(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["system"] = system
        return json.dumps({"decision": "noop"})
    monkeypatch.setattr(llm, "complete", fake)
    reqs = [_r("邮件写短"),
            _r("保留用户原句式，约束以从句追加", kind="style_rule")]
    translate("帮我写封邮件", reqs)
    assert "保留用户原句式" in seen["system"]


def test_translate_system_unchanged_without_styles(monkeypatch):
    seen = {}

    def fake(model, system, user, max_tokens=1024, **kw):
        seen["system"] = system
        return json.dumps({"decision": "noop"})
    monkeypatch.setattr(llm, "complete", fake)
    from memtranslator.translate import LEGACY_TRANSLATOR_SYSTEM
    translate("帮我写封邮件", [_r("邮件写短")])
    assert seen["system"] == LEGACY_TRANSLATOR_SYSTEM


def test_requirement_block_surfaces_attributes():
    from memtranslator.translate import _requirement_block
    req = _r("Emails under 120 words.", kinds=["email"],
             scope={"audience": "smith"}, bucket="output_contract",
             key="email.length", confidence=8)
    block = _requirement_block([req])
    assert "work_kinds: email" in block
    assert "scope: audience=smith" in block
    assert "bucket: output_contract" in block
    assert "key: email.length" in block
    assert "confidence: 8/10" in block
    assert "recency:" in block
