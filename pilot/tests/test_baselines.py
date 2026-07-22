"""Shape tests for the baseline adapters (no external services).

Live single-instance runs are in scripts/dryrun_b1.py; the 20-instance
dry-run with judge output is B2.
"""

from pilot.baselines import ADAPTERS, HEADER, InjectResult, TopKInjectAdapter, format_block

ENTRIES = [
    {"mid": "m0", "text": "I avoid gluten strictly.", "topic": "lifestyle_dietary"},
    {"mid": "m1", "text": "I prefer boutique hotels.", "topic": "travel_hotel"},
]


def test_format_block_empty_is_empty():
    assert format_block([]) == ""


def test_topk_injects_all_entries_verbatim():
    a = TopKInjectAdapter()
    a.ingest(ENTRIES)
    r = a.inject("any query")
    assert isinstance(r, InjectResult)
    assert r.n_retrieved == 2
    assert r.text.startswith(HEADER)
    assert "I avoid gluten strictly." in r.text
    assert r.raw == [e["text"] for e in ENTRIES]


def test_topk_respects_k():
    a = TopKInjectAdapter(k=1)
    a.ingest(ENTRIES)
    assert a.inject("q").n_retrieved == 1


def test_registry_names():
    assert set(ADAPTERS) == {"topk_inject", "mem0", "graphiti"}
    for name, cls in ADAPTERS.items():
        assert cls.name == name
