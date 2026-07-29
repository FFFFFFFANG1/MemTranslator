"""Controlled scope vocabulary: spelling-level normalisation only —
sibling categories must survive distinct (blog vs article carried
different caps on the same real store)."""
from memtranslator.scopes import normalize_scope, normalize_value


def test_spelling_variants_fold_to_one():
    assert normalize_value("Code Documentation") == "code_documentation" or \
           normalize_value("Code Documentation") == "doc"  # slug at minimum
    assert normalize_value("code_documentation") == normalize_value("code documentation")
    assert normalize_value("python脚本") == "python_script"
    assert normalize_value("邮件") == "email"
    assert normalize_value("Emails") == "email"


def test_sibling_categories_stay_distinct():
    assert normalize_value("博客") != normalize_value("文章")
    assert normalize_value("script") != normalize_value("python_script")
    assert normalize_value("周报") != normalize_value("报告")


def test_scope_dict_keys_normalised():
    assert normalize_scope({"Lang": "Go"}) == {"language": "go"}
    assert normalize_scope({"task": "会议纪要"}) == {"task": "meeting_minutes"}
    assert normalize_scope(None) == {}


def test_unknown_values_slug_not_dropped():
    assert normalize_scope({"task": "招标文件"}) == {"task": "招标文件"}
