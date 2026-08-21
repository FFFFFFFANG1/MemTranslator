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
