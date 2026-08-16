from memtranslator.vocabulary import (VocabularyStore, apply_vocabulary,
                                      vocabulary_replacements)


def test_spelling_like_edit_becomes_vocabulary_candidate():
    out = vocabulary_replacements(
        "请让 Sirius 在周五前发结果。",
        "请让 siriux 在周五前发结果。")
    assert out == [{"term": "siriux", "alias": "Sirius",
                    "similarity": 0.833}]


def test_semantic_word_swap_is_not_vocabulary():
    assert vocabulary_replacements(
        "Keep the report formal.", "Keep the report casual.") == []


def test_store_upsert_is_append_only_and_deduplicates(tmp_path):
    path = tmp_path / "vocabulary.jsonl"
    store = VocabularyStore(path)
    first, created = store.upsert("siriux", alias="Sirius",
                                  source="desktop-edit")
    assert created is True and first.observations == 1
    again, created = store.upsert("siriux", alias="Sirius",
                                  source="desktop-edit")
    assert created is False and again.id == first.id
    assert again.observations == 2
    reloaded = VocabularyStore(path)
    assert len(reloaded.list()) == 1
    assert reloaded.list()[0].observations == 2


def test_apply_vocabulary_replaces_complete_alias_tokens_only(tmp_path):
    store = VocabularyStore(tmp_path / "vocabulary.jsonl")
    entry, _ = store.upsert("siriux", alias="Sirius")
    text, applied = apply_vocabulary(
        "Ask Sirius, not SiriusXM or siriux.", store.list())
    assert text == "Ask siriux, not SiriusXM or siriux."
    assert applied == [entry.id]
