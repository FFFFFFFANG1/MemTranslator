"""Small-store hybrid retrieval for memory candidates.

BM25 and the configured embedding service produce independent orders. Reciprocal
rank fusion combines positions rather than incomparable raw scores. The dense
backend is deliberately optional: when it is unavailable, retrieval degrades
to BM25.
"""
from __future__ import annotations

import json
from functools import lru_cache

from memtranslator.bm25 import (BM25, bm25_document_cache_info,
                                clear_bm25_document_cache,
                                prepare_bm25_documents)
from memtranslator.embedding import (EmbeddingRanker, OnnxE5Ranker,
                                     default_embedding_ranker)
from memtranslator.schema import Requirement

RRF_K = 60


def flatten_memory_fields(text: str, *, work_kinds: list[str] | None = None,
                          scope: dict | None = None,
                          applies_when: str = "",
                          scope_mode: str = "global", key: str = "") -> str:
    """One deterministic retrieval document shared by read and write paths."""
    kind_values = sorted({str(kind) for kind in work_kinds or []
                          if str(kind).strip()})
    kinds = ", ".join(kind_values)
    # Keep facet identity separate in storage, but expose the combination the
    # user requested to both lexical and dense retrieval. A script rule with
    # key=length.min therefore contributes script.length.min without making
    # that composite the lifecycle key.
    kind_keys = ", ".join(
        f"{kind}.{key.strip()}" for kind in kind_values if key.strip())
    shown_scope = json.dumps(scope or {}, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
    condition = " ".join(str(applies_when or "").split())
    return (f"text: {text.strip()}\n"
            f"work_kinds: {kinds}\n"
            f"work_kind_keys: {kind_keys}\n"
            f"scope_mode: {scope_mode}\n"
            f"applies_when: {condition}\n"
            f"legacy_scope: {shown_scope}\n"
            f"key: {key.strip()}")


def flatten_applicability_fields(
        *, work_kinds: list[str] | None = None, applies_when: str = "",
        scope: dict | None = None) -> str:
    """Metadata-only retrieval document for the E1 ablation.

    New records contribute only work kind plus the short applicability phrase.
    Legacy key:value scope remains visible until old stores age out.
    """
    kind_values = sorted({str(kind) for kind in work_kinds or []
                          if str(kind).strip()})
    shown_scope = json.dumps(scope or {}, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
    return (f"work_kinds: {', '.join(kind_values)}\n"
            f"applies_when: {' '.join(str(applies_when or '').split())}\n"
            f"legacy_scope: {shown_scope}")


def flatten_requirement(requirement: Requirement) -> str:
    return flatten_memory_fields(
        requirement.text, work_kinds=requirement.kinds,
        scope=requirement.scope, applies_when=requirement.applies_when,
        scope_mode=requirement.scope_mode,
        key=requirement.key)


@lru_cache(maxsize=32)
def _bm25_corpus(texts: tuple[str, ...]) -> BM25:
    """Reuse corpus IDF/TF while the ordered active-memory snapshot is stable."""
    return BM25(list(texts))


def prepare_requirements(requirements: list[Requirement], *,
                         embedding_ranker: EmbeddingRanker | None = None
                         ) -> list[str]:
    """Warm immutable item indexes at ingestion/reload time.

    Content-addressing means metadata-only mutations are cache hits. A changed
    text/work_kind/scope/key creates exactly one new flattened document.
    """
    documents = [flatten_requirement(requirement)
                 for requirement in requirements
                 if requirement.kind == "requirement"]
    prepare_bm25_documents(documents)
    ranker = (embedding_ranker if embedding_ranker is not None
              else default_embedding_ranker())
    prepare = getattr(ranker, "prepare", None) if ranker is not None else None
    if prepare is not None:
        try:
            prepare(documents)
        except Exception:
            pass
    return documents


def rrf_order(rankings: list[list[int]], *, tie_order: list[int] | None = None,
              k: int = RRF_K) -> list[int]:
    """Fuse zero-based document rankings with deterministic ties."""
    docs = {doc for ranking in rankings for doc in ranking}
    if not docs:
        return []
    scores = {doc: 0.0 for doc in docs}
    for ranking in rankings:
        seen = set()
        for rank, doc in enumerate(ranking, 1):
            if doc in seen:
                continue
            seen.add(doc)
            scores[doc] += 1.0 / (k + rank)
    tie_order = tie_order or sorted(docs)
    tie = {doc: pos for pos, doc in enumerate(tie_order)}
    return sorted(docs, key=lambda doc: (-scores[doc], tie.get(doc, doc)))


def sparse_order(query: str, texts: list[str], *,
                 positive_only: bool = False) -> list[int]:
    """BM25 document order, optionally excluding its zero-evidence tail."""
    if not texts:
        return []
    return [index for index, score in _bm25_corpus(tuple(texts)).rank(query)
            if not positive_only or score > 0]


def quota_interleave_order(sparse: list[int], dense: list[int], *,
                           cap: int, sparse_quota: int = 4,
                           dense_quota: int = 4) -> list[int]:
    """Unique quota union, then alternate unseen sparse/dense candidates.

    The seed gives each retrieval meaning independent representation. Any
    overlap is refilled in sparse-then-dense order until ``cap`` is reached.
    """
    selected: list[int] = []
    seen: set[int] = set()

    def add(index: int) -> None:
        if index not in seen and len(selected) < cap:
            seen.add(index)
            selected.append(index)

    for index in sparse[:sparse_quota]:
        add(index)
    for index in dense[:dense_quota]:
        add(index)

    sparse_index = sparse_quota
    dense_index = dense_quota
    while (len(selected) < cap
           and (sparse_index < len(sparse) or dense_index < len(dense))):
        if sparse_index < len(sparse):
            add(sparse[sparse_index])
            sparse_index += 1
        if dense_index < len(dense) and len(selected) < cap:
            add(dense[dense_index])
            dense_index += 1
    return selected


def rerank_by_best_rank(candidates: list[int], sparse: list[int],
                        dense: list[int]) -> list[int]:
    """Rerank a fixed candidate union without another model.

    A document that either independent route ranks highly should remain near
    the front of the Translator prompt.  The better of its sparse/dense ranks
    is therefore primary; their sum breaks ties, and the candidate-union
    order is the final deterministic tie-break.  Missing route evidence sorts
    behind real ranks but never removes an already selected candidate.
    """
    sparse_rank = {document: rank for rank, document in enumerate(sparse, 1)}
    dense_rank = {document: rank for rank, document in enumerate(dense, 1)}
    candidate_rank = {
        document: rank for rank, document in enumerate(candidates)}
    missing = max(len(sparse), len(dense), len(candidates)) + 1
    return sorted(
        dict.fromkeys(candidates),
        key=lambda document: (
            min(sparse_rank.get(document, missing),
                dense_rank.get(document, missing)),
            sparse_rank.get(document, missing)
            + dense_rank.get(document, missing),
            candidate_rank[document],
        ))


def rerank_by_rank_sum(candidates: list[int], primary: list[int],
                       secondary: list[int]) -> list[int]:
    """Blend two deterministic orders over an already fixed candidate set.

    Read retrieval uses text relevance to form the 8+8 union and its primary
    order.  Applicability metadata is deliberately allowed to reorder that
    union, but never to admit or remove a rule. Equal weight performed best
    in the E1 trace ablation; primary rank breaks sums so weak or missing
    metadata cannot overturn a clear text match.
    """
    unique = list(dict.fromkeys(candidates))
    primary_rank = {document: rank
                    for rank, document in enumerate(primary, 1)}
    secondary_rank = {document: rank
                      for rank, document in enumerate(secondary, 1)}
    candidate_rank = {document: rank
                      for rank, document in enumerate(unique)}
    missing = max(len(primary), len(secondary), len(unique)) + 1
    return sorted(
        unique,
        key=lambda document: (
            primary_rank.get(document, missing)
            + secondary_rank.get(document, missing),
            primary_rank.get(document, missing),
            candidate_rank[document],
        ))


def hybrid_order(query: str, bm25_texts: list[str], *,
                 embedding_texts: list[str] | None = None,
                 embedding_ranker: EmbeddingRanker | None = None,
                 positive_sparse_only: bool = False) -> list[int]:
    """Return all document indices ordered by BM25+dense RRF.

    A backend failure cannot break the asynchronous write path. It removes
    only the dense ranking; BM25 still proposes candidates for consolidation.
    """
    if not bm25_texts:
        return []
    sparse = sparse_order(query, bm25_texts,
                          positive_only=positive_sparse_only)
    rankings = [sparse] if sparse else []
    if embedding_ranker is not None:
        try:
            dense = embedding_ranker.rank(
                query, embedding_texts if embedding_texts is not None
                else bm25_texts)
            valid = [idx for idx in dense
                     if isinstance(idx, int) and 0 <= idx < len(bm25_texts)]
            if valid:
                rankings.append(valid)
        except Exception:
            pass
    return rrf_order(rankings, tie_order=list(range(len(bm25_texts))))


def clear_retrieval_caches() -> None:
    """Test/maintenance hook; production caches are content-addressed."""
    clear_bm25_document_cache()
    _bm25_corpus.cache_clear()
    if default_embedding_ranker.cache_info().currsize:
        ranker = default_embedding_ranker()
        clear = getattr(ranker, "clear", None) if ranker is not None else None
        if clear is not None:
            clear()
    default_embedding_ranker.cache_clear()


def retrieval_cache_info() -> dict:
    corpus = _bm25_corpus.cache_info()
    ranker = (default_embedding_ranker()
              if default_embedding_ranker.cache_info().currsize else None)
    return {
        "bm25_documents": bm25_document_cache_info(),
        "bm25_corpora": {"hits": corpus.hits, "misses": corpus.misses,
                          "size": corpus.currsize},
        "embedding_documents": len(getattr(ranker, "_document_vectors", {})),
    }
