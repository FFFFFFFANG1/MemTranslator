"""BM25 has to behave on the two things the 14-root lexicon could not: Chinese
vocabulary nobody registered, and picking the on-topic rule out of a pool that
is larger than the cap."""
from memtranslator.bm25 import BM25, tokenize


def test_tokenize_splits_latin_and_cjk():
    assert tokenize("Keep emails under 120 words") == [
        "keep", "emails", "under", "120", "words"]
    assert tokenize("邮件结尾") == ["邮件", "件结", "结尾"]
    assert tokenize("用 Python 写") == ["python", "用", "写"]
    assert tokenize("") == []


def test_single_char_cjk_run_survives():
    # no bigram exists, and dropping it would silently lose the term
    assert "写" in tokenize("写 code")


def test_ranks_the_on_topic_rule_first():
    docs = ["邮件结尾只留名字和手机号",
            "代码注释统一用英文",
            "会议纪要按时间倒序排列"]
    order = [i for i, _ in BM25(docs).rank("给供应商写封邮件催发票")]
    assert order[0] == 0


def test_vocabulary_outside_the_key_lexicon_still_matches():
    """The whole point: no lexicon entry exists for 发票 or 报销, and BM25 does
    not need one."""
    docs = ["报销单要附上发票照片", "邮件结尾只留名字和手机号"]
    assert BM25(docs).rank("帮我把这个月的发票整理成报销单")[0][0] == 0


def test_ties_keep_the_callers_order():
    docs = ["无关规则一", "无关规则二", "无关规则三"]
    assert [i for i, _ in BM25(docs).rank("完全不相干的请求")] == [0, 1, 2]


def test_empty_corpus_and_empty_query_are_safe():
    assert BM25([]).rank("x") == []
    assert BM25(["a"]).scores("") == [0.0]


def test_idf_never_penalises_a_universal_term():
    # a term in every document contributes zero, never a negative score
    docs = ["邮件要短", "邮件要正式", "邮件要有署名"]
    assert all(s >= 0 for s in BM25(docs).scores("邮件"))
