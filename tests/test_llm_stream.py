import json

from memtranslator import llm


class _Response:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def iter_lines(self):
        for content in ("hello", " world"):
            event = {"choices": [{"delta": {"content": content}}]}
            yield "data: " + json.dumps(event)
        yield "data: [DONE]"


class _Client:
    def __init__(self):
        self.request = None

    def stream(self, method, url, **kwargs):
        self.request = (method, url, kwargs)
        return _Response()


def test_ark_stream_uses_openai_compatible_sse(monkeypatch):
    client = _Client()
    monkeypatch.setattr(llm, "_or_client", client)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")

    chunks = list(llm.stream_text(
        "ark:deepseek-v4-flash", "system",
        [{"role": "user", "content": "hi"}], max_tokens=32,
        temperature=0.0))

    assert chunks == ["hello", " world"]
    assert client.request[0:2] == (
        "POST", "https://example.test/v1/chat/completions")
    payload = client.request[2]["json"]
    assert payload["stream"] is True
    assert payload["temperature"] == 0.0
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["messages"][0] == {
        "role": "system", "content": "system"}
