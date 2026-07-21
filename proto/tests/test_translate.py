import json

from memtranslator import FakeLLM, MemoryEntry, MemoryStore, Scope
from memtranslator.translate import translate

PAPER_CONTENT = "# Some Long Paper\n\nLorem ipsum research content..."


def seeded_store(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    entry = store.add(MemoryEntry(
        requirement="When analyzing papers, critique problems and compare against related work.",
        scope=Scope(condition="the user asks to analyze a research paper",
                    keywords=["paper", "analysis", "review"]),
    ))
    return store, entry


def test_patch_rewrites_request_and_preserves_content_verbatim(tmp_path):
    store, entry = seeded_store(tmp_path)
    resp = json.dumps({"action": "patch",
                       "revised_request": "请批判性分析这篇论文的问题，并与相关工作对比。",
                       "applied_memory_ids": [entry.mid], "rationale": "paper analysis scope"})
    t = translate(FakeLLM([resp]), "帮我看看这篇论文", store, content=PAPER_CONTENT)
    assert not t.noop
    assert t.polished_request.startswith("请批判性分析")
    assert t.polished_input.endswith(PAPER_CONTENT)  # content untouched, reattached mechanically
    assert [e.mid for e in t.applied] == [entry.mid]
    assert store.get(entry.mid).last_applied_at is not None  # usage write-back


def test_content_never_sent_inside_request_segment(tmp_path):
    store, _ = seeded_store(tmp_path)
    resp = json.dumps({"action": "noop", "applied_memory_ids": [], "rationale": "n/a"})
    llm = FakeLLM([resp])
    translate(llm, "帮我看看这篇论文", store, content=PAPER_CONTENT)
    assert PAPER_CONTENT not in llm.calls[0]["user"]  # long content stays out of the translator call


def test_explicit_noop_passes_through(tmp_path):
    store, entry = seeded_store(tmp_path)
    resp = json.dumps({"action": "noop", "applied_memory_ids": [], "rationale": "unrelated request"})
    t = translate(FakeLLM([resp]), "今天天气怎么样", store)
    assert t.noop and t.polished_request == "今天天气怎么样"
    assert store.get(entry.mid).last_applied_at is None


def test_empty_store_short_circuits_without_llm(tmp_path):
    store = MemoryStore(tmp_path / "m.jsonl")
    llm = FakeLLM([])
    t = translate(llm, "任何请求", store)
    assert t.noop and llm.calls == []


def test_unparseable_translator_output_falls_back_to_passthrough(tmp_path):
    store, _ = seeded_store(tmp_path)
    t = translate(FakeLLM(["sure! here's a better prompt: ..."]), "帮我看看这篇论文", store)
    assert t.noop and t.polished_request == "帮我看看这篇论文"


def test_hallucinated_memory_ids_are_filtered_making_patch_a_noop(tmp_path):
    store, _ = seeded_store(tmp_path)
    resp = json.dumps({"action": "patch", "revised_request": "改写后的请求",
                       "applied_memory_ids": ["m-hallucinated"], "rationale": ""})
    t = translate(FakeLLM([resp]), "帮我看看这篇论文", store)
    assert t.noop  # a patch justified by no real memory must not go through
