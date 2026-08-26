import memtranslator.config as config
import memtranslator.llm as llm


def test_project_env_reads_repo_dotenv_and_process_env_wins(
        tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "LLM_API_KEY=dot-env-key\nLLM_BASE_URL=https://example.test\n")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    assert config.project_env("LLM_API_KEY") == "dot-env-key"
    monkeypatch.setenv("LLM_API_KEY", "process-key")
    assert config.project_env("LLM_API_KEY") == "process-key"


def test_ark_model_channel_uses_unified_llm_settings(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    values = {"LLM_API_KEY": "unified-key",
              "LLM_BASE_URL": "https://example.test/v3"}
    monkeypatch.setattr(
        llm, "project_env", lambda name, default="": values.get(name, default))
    monkeypatch.setattr(llm, "_or_client", Client())

    assert llm._ark_complete("model", "system", "user", 20, 0, False) == "ok"
    assert calls[0][0] == "https://example.test/v3/chat/completions"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer unified-key"


def test_openrouter_channel_uses_runtime_base_url(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    values = {
        "OPENROUTER_API_KEY": "router-key",
        "OPENROUTER_BASE_URL": "https://router.example/v1",
    }
    monkeypatch.setattr(
        llm, "project_env", lambda name, default="": values.get(name, default))
    monkeypatch.setattr(llm, "_or_client", Client())

    assert llm._openrouter_complete(
        "provider/model", "system", "user", 20, 0) == "ok"
    assert calls[0][0] == "https://router.example/v1/chat/completions"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer router-key"


def test_explicit_openai_format_routes_bare_model_to_compatible_api(
        monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setenv("MT_LLM_API_FORMAT", "openai-compatible")
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    monkeypatch.setenv(
        "LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
    monkeypatch.setattr(llm, "_or_client", Client())

    assert llm.complete("deepseek-test", "system", "user") == "ok"
    assert calls[0][1]["json"]["model"] == "deepseek-test"
    assert calls[0][1]["json"]["thinking"] == {"type": "disabled"}


def test_explicit_anthropic_format_overrides_slash_model_inference(
        monkeypatch):
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return type("Response", (), {
                "content": [type("Block", (), {"type": "text", "text": "ok"})]
            })()

    client = type("Client", (), {"messages": Messages()})()
    monkeypatch.setenv("MT_LLM_API_FORMAT", "anthropic")
    monkeypatch.setattr(llm, "_get_client", lambda: client)

    assert llm.complete("vendor/claude-test", "system", "user") == "ok"
    assert calls[0]["model"] == "vendor/claude-test"
