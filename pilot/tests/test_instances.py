import json

from pilot.config import MEMORY_STORE_SIZE, N_NEGATIVE, N_POSITIVE
from pilot.data_prep import build_instances, load_prefeval, super_category

DATA = load_prefeval()


def test_counts_and_shapes():
    pos, neg = build_instances(DATA)
    assert len(pos) == N_POSITIVE and len(neg) == N_NEGATIVE
    for inst in pos + neg:
        assert len(inst.memory_store) == MEMORY_STORE_SIZE
        assert len({e["mid"] for e in inst.memory_store}) == MEMORY_STORE_SIZE


def test_positive_gold_in_store_and_distractors_cross_category():
    pos, _ = build_instances(DATA)
    for inst in pos:
        gold = [e for e in inst.memory_store if e["mid"] == inst.gold_mid]
        assert len(gold) == 1 and gold[0]["text"] == inst.gold_preference
        for e in inst.memory_store:
            if e["mid"] != inst.gold_mid:
                assert super_category(e["topic"]) != super_category(inst.query_topic)


def test_negative_store_fully_cross_category():
    _, neg = build_instances(DATA)
    for inst in neg:
        assert inst.gold_mid is None and inst.gold_preference is None
        for e in inst.memory_store:
            assert super_category(e["topic"]) != super_category(inst.query_topic)


def test_deterministic_under_seed():
    a_pos, a_neg = build_instances(DATA)
    b_pos, b_neg = build_instances(DATA)
    assert json.dumps([i.iid for i in a_pos]) == json.dumps([i.iid for i in b_pos])
    assert a_pos[0].memory_store == b_pos[0].memory_store
    assert a_neg[-1].memory_store == b_neg[-1].memory_store


def test_stratification_covers_topics():
    pos, _ = build_instances(DATA)
    topics = {i.query_topic for i in pos}
    assert len(topics) == 20  # every topic contributes positives
