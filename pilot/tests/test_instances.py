from pilot.data_prep import build_instances, super_category


def fake_items():
    return [{"topic": f"cat{i}_sub", "preference": f"pref-{i}-{j}",
             "query": f"query-{i}-{j}"}
            for i in range(10) for j in range(30)]


def test_counts_and_shape():
    pos, neg = build_instances(fake_items(), n_pos=20, n_neg=10)
    assert len(pos) == 20 and len(neg) == 10
    for inst in pos + neg:
        assert len(inst["memory_store"]) == 8
        assert inst["content"] == ""


def test_positive_has_exactly_one_relevant_memory():
    pos, _ = build_instances(fake_items(), n_pos=20, n_neg=10)
    for inst in pos:
        hits = [m for m in inst["memory_store"]
                if m["mid"] == inst["relevant_memory_id"]]
        assert len(hits) == 1
        assert hits[0]["text"] == inst["preference"]
        others = [m for m in inst["memory_store"]
                  if m["mid"] != inst["relevant_memory_id"]]
        assert all(super_category(m["topic"]) != super_category(inst["topic"])
                   for m in others)


def test_negative_has_no_same_supercategory_memory():
    _, neg = build_instances(fake_items(), n_pos=20, n_neg=10)
    for inst in neg:
        assert inst["preference"] is None
        assert all(super_category(m["topic"]) != super_category(inst["topic"])
                   for m in inst["memory_store"])


def test_deterministic():
    a = build_instances(fake_items(), n_pos=20, n_neg=10)
    b = build_instances(fake_items(), n_pos=20, n_neg=10)
    assert a == b


def test_stratification_covers_topics():
    pos, _ = build_instances(fake_items(), n_pos=20, n_neg=10)
    assert len({i["topic"] for i in pos}) == 10
