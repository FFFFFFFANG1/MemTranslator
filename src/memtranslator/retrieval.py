"""Small-store hybrid retrieval for memory candidates.

BM25 and a local embedding ranker produce independent orders. Reciprocal
rank fusion combines positions rather than incomparable raw scores. The dense
backend is deliberately optional and local: when the configured ONNX model is
absent, retrieval degrades to BM25 without adding a network dependency.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from memtranslator.bm25 import (BM25, bm25_document_cache_info,
                                clear_bm25_document_cache,
                                prepare_bm25_documents)
from memtranslator.schema import Requirement

RRF_K = 60


class EmbeddingRanker(Protocol):
    def rank(self, query: str, texts: list[str]) -> list[int]: ...


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


class OnnxE5Ranker:
    """Lazy multilingual-e5 ranker using local ONNX Runtime on CPU.

    Imports live inside ``__init__`` so the base product remains usable
    without the optional ``memory-embedding`` dependency set. No model is
    downloaded here; provisioning the local directory is an explicit install
    step and therefore cannot turn a memory flush into a network operation.
    """

    def __init__(self, model_path: Path, tokenizer_path: Path):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
        # model_O4.onnx is an fp16 GPU export. On Apple Silicon, CoreML is
        # first in ORT's provider list but barely offloads this graph; CPU
        # matches it on a cached query (~2.4ms) and avoids compile jitter.
        # Cap intra-op threads: M4's default 10 oversubscribes a 12-layer
        # MiniLM, 4 P-cores were the fastest of 1/4/8 in a 24-doc batch.
        options = ort.SessionOptions()
        options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL)
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options,
            providers=["CPUExecutionProvider"])
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=512)
        self._pad_id = self._tokenizer.token_to_id("<pad>") or 0
        self._input_names = {item.name for item in self._session.get_inputs()}
        self._document_vectors = {}
        self._document_matrices = {}

    def _encode(self, texts: list[str]):
        np = self._np
        encoded = self._tokenizer.encode_batch(texts)
        width = max((len(item.ids) for item in encoded), default=1)
        ids, masks = [], []
        for item in encoded:
            pad = width - len(item.ids)
            ids.append(item.ids + [self._pad_id] * pad)
            masks.append(item.attention_mask + [0] * pad)
        inputs = {
            "input_ids": np.asarray(ids, dtype=np.int64),
            "attention_mask": np.asarray(masks, dtype=np.int64),
        }
        if "token_type_ids" in self._input_names:
            inputs["token_type_ids"] = np.zeros_like(inputs["input_ids"])
        inputs = {name: value for name, value in inputs.items()
                  if name in self._input_names}
        output = self._session.run(None, inputs)[0]
        if output.ndim == 3:
            mask = inputs["attention_mask"][..., None]
            output = (output * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
        norms = np.linalg.norm(output, axis=1, keepdims=True).clip(min=1e-12)
        return output / norms

    def prepare(self, texts: list[str]) -> None:
        missing = list(dict.fromkeys(
            text for text in texts if text not in self._document_vectors))
        if not missing:
            return
        vectors = self._encode([f"passage: {text}" for text in missing])
        for text, vector in zip(missing, vectors):
            self._document_vectors[text] = vector

    def clear(self) -> None:
        self._document_vectors.clear()
        self._document_matrices.clear()

    def rank(self, query: str, texts: list[str]) -> list[int]:
        if not texts:
            return []
        self.prepare(texts)
        query_vector = self._encode([f"query: {query}"])[0]
        corpus_key = tuple(texts)
        documents = self._document_matrices.get(corpus_key)
        if documents is None:
            documents = self._np.asarray(
                [self._document_vectors[text] for text in texts])
            self._document_matrices[corpus_key] = documents
        scores = documents @ query_vector
        return sorted(range(len(texts)), key=lambda idx: (-scores[idx], idx))


@lru_cache(maxsize=1)
def default_embedding_ranker() -> EmbeddingRanker | None:
    """Load the configured local model if all artifacts are present."""
    from memtranslator.config import EMBED_MODEL_DIR, EMBED_ONNX_FILE

    model_path = Path(EMBED_MODEL_DIR) / EMBED_ONNX_FILE
    tokenizer_path = Path(EMBED_MODEL_DIR) / "onnx" / "tokenizer.json"
    if not model_path.is_file() or not tokenizer_path.is_file():
        return None
    try:
        return OnnxE5Ranker(model_path, tokenizer_path)
    except Exception:
        return None


def clear_retrieval_caches() -> None:
    """Test/maintenance hook; production caches are content-addressed."""
    clear_bm25_document_cache()
    _bm25_corpus.cache_clear()
    if default_embedding_ranker.cache_info().currsize:
        ranker = default_embedding_ranker()
        clear = getattr(ranker, "clear", None) if ranker is not None else None
        if clear is not None:
            clear()


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
