"""Embedding service shared by read and write retrieval paths.

The service has two explicit modes:

* ``local`` loads the provisioned multilingual-e5-small ONNX export on CPU.
  Provisioning happens during ``memtranslator init``; runtime never downloads.
* ``remote`` calls an OpenAI-compatible ``/embeddings`` endpoint. A dedicated
  key/base URL may be configured, otherwise the active LLM connection is used.

Any initialization or request failure leaves BM25 as the complete retrieval
path. Embedding improves ranking, but it is never required for memory safety.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

LOCAL_MODEL_REPO = "intfloat/multilingual-e5-small"
LOCAL_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
LOCAL_MODEL_FILES = ("onnx/model_O4.onnx", "onnx/tokenizer.json")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"


class EmbeddingUnavailable(Exception):
    """The configured embedding backend cannot be initialized or reached."""


class EmbeddingRanker(Protocol):
    def rank(self, query: str, texts: list[str]) -> list[int]: ...


@dataclass(frozen=True)
class RemoteEmbeddingConfig:
    model: str
    api_key: str
    base_url: str


def _project_env(name: str, default: str = "") -> str:
    # Keep config lazy so `memtranslator init --home ...` does not load the
    # previous default runtime home's .env merely by importing the downloader.
    from memtranslator.config import project_env

    return project_env(name, default)


def _llm_connection_defaults() -> tuple[str, str]:
    """Return the key/base URL for the active LLM API format."""
    from memtranslator.config import MODELS

    model = str(MODELS.get("translator") or "")
    api_format = _project_env("MT_LLM_API_FORMAT").strip().casefold()
    if not api_format:
        api_format = ("openai-compatible"
                      if model.startswith("ark:") or "/" in model
                      else "anthropic")
    generic_key = _project_env("LLM_API_KEY")
    generic_base = _project_env("LLM_BASE_URL")
    if generic_key or generic_base:
        default_base = (ANTHROPIC_BASE_URL if api_format == "anthropic"
                        else ARK_BASE_URL)
        return generic_key, generic_base or default_base
    if api_format == "anthropic":
        return (_project_env("ANTHROPIC_API_KEY"),
                _project_env("ANTHROPIC_BASE_URL", ANTHROPIC_BASE_URL))
    if "/" in model:
        return (_project_env("OPENROUTER_API_KEY"),
                _project_env("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL))
    return (_project_env("LLM_API_KEY"),
            _project_env("LLM_BASE_URL", ARK_BASE_URL))


def remote_embedding_config() -> RemoteEmbeddingConfig:
    """Resolve remote settings, falling back to the active LLM connection."""
    model = _project_env("MT_EMBEDDING_MODEL").strip()
    llm_key, llm_base_url = _llm_connection_defaults()
    api_key = _project_env("MT_EMBEDDING_API_KEY").strip() or llm_key
    base_url = (_project_env("MT_EMBEDDING_BASE_URL").strip()
                or llm_base_url).rstrip("/")
    if not model:
        raise EmbeddingUnavailable("MT_EMBEDDING_MODEL is not configured")
    if not api_key:
        raise EmbeddingUnavailable(
            "embedding API key and fallback LLM API key are both empty")
    if not base_url:
        raise EmbeddingUnavailable(
            "embedding base URL and fallback LLM base URL are both empty")
    return RemoteEmbeddingConfig(model, api_key, base_url)


class OnnxE5Ranker:
    """Lazy multilingual-e5 ranker using ONNX Runtime on CPU."""

    def __init__(self, model_path: Path, tokenizer_path: Path):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._np = np
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


class RemoteEmbeddingRanker:
    """Cached cosine ranker backed by an OpenAI-compatible embedding API."""

    def __init__(self, config: RemoteEmbeddingConfig,
                 client: httpx.Client | None = None):
        import numpy as np

        self.config = config
        self._np = np
        self._client = client or httpx.Client(timeout=120)
        self._document_vectors = {}
        self._document_matrices = {}

    def _encode(self, texts: list[str]):
        if not texts:
            return self._np.empty((0, 0), dtype=self._np.float32)
        try:
            response = self._client.post(
                f"{self.config.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={"model": self.config.model, "input": texts},
            )
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailable("connection") from exc
        if response.status_code != 200:
            raise EmbeddingUnavailable(
                f"status:{response.status_code} {response.text[:200]}")
        try:
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            if len(rows) != len(texts):
                raise ValueError("embedding count mismatch")
            vectors = self._np.asarray(
                [row["embedding"] for row in rows], dtype=self._np.float32)
            if vectors.ndim != 2 or not vectors.shape[1]:
                raise ValueError("invalid embedding shape")
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingUnavailable("malformed embedding response") from exc
        norms = self._np.linalg.norm(
            vectors, axis=1, keepdims=True).clip(min=1e-12)
        return vectors / norms

    def prepare(self, texts: list[str]) -> None:
        missing = list(dict.fromkeys(
            text for text in texts if text not in self._document_vectors))
        if not missing:
            return
        vectors = self._encode(missing)
        for text, vector in zip(missing, vectors):
            self._document_vectors[text] = vector

    def clear(self) -> None:
        self._document_vectors.clear()
        self._document_matrices.clear()

    def rank(self, query: str, texts: list[str]) -> list[int]:
        if not texts:
            return []
        self.prepare(texts)
        query_vector = self._encode([query])[0]
        corpus_key = tuple(texts)
        documents = self._document_matrices.get(corpus_key)
        if documents is None:
            documents = self._np.asarray(
                [self._document_vectors[text] for text in texts])
            self._document_matrices[corpus_key] = documents
        scores = documents @ query_vector
        return sorted(range(len(texts)), key=lambda idx: (-scores[idx], idx))


def local_model_ready(model_dir: Path) -> bool:
    root = Path(model_dir)
    return all((root / name).is_file() for name in LOCAL_MODEL_FILES)


def _download_snapshot(model_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=LOCAL_MODEL_REPO,
        revision=LOCAL_MODEL_REVISION,
        allow_patterns=list(LOCAL_MODEL_FILES),
        local_dir=str(model_dir),
    )


def download_local_model(model_dir: Path) -> Path:
    """Provision the pinned local model; never called by runtime retrieval."""
    destination = Path(model_dir).expanduser().resolve()
    if local_model_ready(destination):
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    try:
        _download_snapshot(destination)
    except Exception as exc:
        raise EmbeddingUnavailable(
            f"could not download {LOCAL_MODEL_REPO}: {exc}") from exc
    if not local_model_ready(destination):
        raise EmbeddingUnavailable(
            "download completed without the required ONNX artifacts")
    return destination


@lru_cache(maxsize=1)
def default_embedding_ranker() -> EmbeddingRanker | None:
    """Create the configured backend once; failures degrade cleanly to BM25."""
    from memtranslator import config

    mode = _project_env("MT_EMBEDDING_MODE", "local").strip().casefold()
    try:
        if mode == "remote":
            return RemoteEmbeddingRanker(remote_embedding_config())
        if mode != "local":
            return None
        model_dir = Path(_project_env(
            "MT_EMBED_MODEL_DIR", str(config.EMBED_MODEL_DIR)))
        model_path = model_dir / _project_env(
            "MT_EMBED_ONNX_FILE", config.EMBED_ONNX_FILE)
        tokenizer_path = model_dir / "onnx" / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            return None
        return OnnxE5Ranker(model_path, tokenizer_path)
    except Exception:
        return None
