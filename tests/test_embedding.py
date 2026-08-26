import memtranslator.config as config
import memtranslator.embedding as embedding


def _clear_embedding_env(monkeypatch):
    for name in (
        "MT_LLM_API_FORMAT", "MT_EMBEDDING_MODE", "MT_EMBEDDING_MODEL",
        "MT_EMBEDDING_API_KEY", "MT_EMBEDDING_BASE_URL",
        "MT_EMBED_MODEL_DIR", "MT_EMBED_ONNX_FILE",
        "LLM_API_KEY", "LLM_BASE_URL", "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    embedding.default_embedding_ranker.cache_clear()


def test_remote_config_falls_back_to_active_llm_connection(monkeypatch):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setitem(config.MODELS, "translator", "ark:chat-model")
    monkeypatch.setenv("MT_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("LLM_API_KEY", "llm-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1/")

    resolved = embedding.remote_embedding_config()

    assert resolved == embedding.RemoteEmbeddingConfig(
        "embed-model", "llm-key", "https://llm.example/v1")


def test_remote_config_prefers_embedding_overrides(monkeypatch):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setitem(config.MODELS, "translator", "provider/model")
    monkeypatch.setenv("MT_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("MT_EMBEDDING_API_KEY", "embed-key")
    monkeypatch.setenv("MT_EMBEDDING_BASE_URL", "https://embed.example/v1/")
    monkeypatch.setenv("OPENROUTER_API_KEY", "llm-key")

    resolved = embedding.remote_embedding_config()

    assert resolved.api_key == "embed-key"
    assert resolved.base_url == "https://embed.example/v1"


def test_remote_config_inherits_custom_openrouter_base(monkeypatch):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setitem(config.MODELS, "translator", "provider/model")
    monkeypatch.setenv("MT_EMBEDDING_MODEL", "embed-model")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://router.example/v1/")

    resolved = embedding.remote_embedding_config()

    assert resolved.api_key == "router-key"
    assert resolved.base_url == "https://router.example/v1"


def test_remote_ranker_calls_openai_compatible_api_and_caches_documents():
    calls = []

    class Response:
        status_code = 200
        text = ""

        def __init__(self, inputs):
            self.inputs = inputs

        def json(self):
            data = []
            for index, text in enumerate(self.inputs):
                vector = [1.0, 0.0] if text == "east" else [0.0, 1.0]
                data.append({"index": index, "embedding": vector})
            return {"data": data}

    class Client:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response(kwargs["json"]["input"])

    ranker = embedding.RemoteEmbeddingRanker(
        embedding.RemoteEmbeddingConfig(
            "embed-model", "embed-key", "https://embed.example/v1"),
        Client())

    assert ranker.rank("east", ["west", "east"]) == [1, 0]
    assert ranker.rank("east", ["west", "east"]) == [1, 0]

    assert [call[1]["json"]["input"] for call in calls] == [
        ["west", "east"], ["east"], ["east"]]
    assert all(call[0] == "https://embed.example/v1/embeddings"
               for call in calls)
    assert calls[0][1]["headers"]["Authorization"] == "Bearer embed-key"


def test_default_local_service_loads_provisioned_cpu_model(
        tmp_path, monkeypatch):
    _clear_embedding_env(monkeypatch)
    model_dir = tmp_path / "model"
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "onnx" / "model_O4.onnx").write_bytes(b"model")
    (model_dir / "onnx" / "tokenizer.json").write_text("{}")
    sentinel = object()
    calls = []
    monkeypatch.setenv("MT_EMBEDDING_MODE", "local")
    monkeypatch.setenv("MT_EMBED_MODEL_DIR", str(model_dir))
    monkeypatch.setattr(
        embedding, "OnnxE5Ranker",
        lambda model, tokenizer: calls.append((model, tokenizer)) or sentinel)

    assert embedding.default_embedding_ranker() is sentinel
    assert calls == [(model_dir / "onnx" / "model_O4.onnx",
                      model_dir / "onnx" / "tokenizer.json")]


def test_local_model_download_is_pinned_and_validated(tmp_path, monkeypatch):
    destination = tmp_path / "model"
    calls = []

    def download(path):
        calls.append(path)
        (path / "onnx").mkdir(parents=True)
        (path / "onnx" / "model_O4.onnx").write_bytes(b"model")
        (path / "onnx" / "tokenizer.json").write_text("{}")

    monkeypatch.setattr(embedding, "_download_snapshot", download)

    assert embedding.download_local_model(destination) == destination
    assert calls == [destination]
    assert embedding.local_model_ready(destination)

    embedding.download_local_model(destination)
    assert calls == [destination]
