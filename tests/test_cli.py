import stat

from memtranslator.cli import _read_env, build_parser


def _fake_local_embedding(monkeypatch):
    calls = []

    def download(path):
        calls.append(path)
        return path

    monkeypatch.setattr(
        "memtranslator.embedding.download_local_model", download)
    return calls


def test_init_imports_checkout_settings_and_memory(tmp_path, monkeypatch,
                                                   capsys):
    downloads = _fake_local_embedding(monkeypatch)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".env").write_text(
        "LLM_BASE_URL=https://example.test/v3\nEXISTING_SETTING=kept\n")
    (checkout / "data").mkdir()
    (checkout / "data" / "store.jsonl").write_text('{"id":"req-1"}\n')
    (checkout / "data" / "events.jsonl").write_text('{"kind":"x"}\n')
    home = tmp_path / "runtime"
    monkeypatch.chdir(checkout)
    args = build_parser().parse_args([
        "init", "--non-interactive", "--home", str(home),
        "--port", "9123", "--provider", "ark", "--model", "demo-model",
        "--api-key", "secret-value",
    ])

    assert args.handler(args) == 0

    values = _read_env(home / ".env")
    assert values["MT_PORT"] == "9123"
    assert values["MT_LLM_API_FORMAT"] == "openai-compatible"
    assert values["MT_TRANSLATOR"] == "demo-model"
    assert values["LLM_API_KEY"] == "secret-value"
    assert values["MT_EMBEDDING_MODE"] == "local"
    assert downloads == [home / "models" / "multilingual-e5-small"]
    assert values["EXISTING_SETTING"] == "kept"
    assert stat.S_IMODE((home / ".env").stat().st_mode) == 0o600
    assert (home / "data" / "store.jsonl").read_text() == '{"id":"req-1"}\n'
    assert (home / "data" / "events.jsonl").read_text() == '{"kind":"x"}\n'
    assert "secret-value" not in capsys.readouterr().out


def test_init_does_not_overwrite_existing_runtime_memory(tmp_path,
                                                         monkeypatch):
    _fake_local_embedding(monkeypatch)
    checkout = tmp_path / "checkout"
    (checkout / "data").mkdir(parents=True)
    (checkout / "data" / "store.jsonl").write_text("checkout\n")
    home = tmp_path / "runtime"
    (home / "data").mkdir(parents=True)
    (home / "data" / "store.jsonl").write_text("runtime\n")
    monkeypatch.chdir(checkout)
    args = build_parser().parse_args([
        "init", "--non-interactive", "--home", str(home),
        "--provider", "ark", "--api-key", "key",
    ])

    args.handler(args)

    assert (home / "data" / "store.jsonl").read_text() == "runtime\n"


def test_init_configures_remote_embedding_after_llm(tmp_path, monkeypatch):
    answers = iter([
        "", "", "", "",  # port, API format, model, LLM base URL
        "y", "embed-v1", "",  # remote?, model, embedding base URL
    ])
    secrets = iter(["llm-secret", ""])
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(secrets))
    monkeypatch.setattr(
        "memtranslator.embedding.download_local_model",
        lambda _path: (_ for _ in ()).throw(AssertionError("must not download")))
    home = tmp_path / "runtime"
    args = build_parser().parse_args(["init", "--home", str(home)])

    assert args.handler(args) == 0

    values = _read_env(home / ".env")
    assert values["LLM_API_KEY"] == "llm-secret"
    assert values["MT_EMBEDDING_MODE"] == "remote"
    assert values["MT_EMBEDDING_MODEL"] == "embed-v1"
    assert "MT_EMBEDDING_API_KEY" not in values
    assert "MT_EMBEDDING_BASE_URL" not in values
    assert "MT_EMBED_MODEL_DIR" not in values
    assert any("remote embedding API" in prompt for prompt in prompts)
    assert any("uses LLM base URL" in prompt for prompt in prompts)


def test_init_declining_remote_downloads_local_onnx(tmp_path, monkeypatch,
                                                    capsys):
    answers = iter([
        "", "", "", "",  # port, API format, model, LLM base URL
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "llm-secret")
    downloads = _fake_local_embedding(monkeypatch)
    home = tmp_path / "runtime"
    args = build_parser().parse_args(["init", "--home", str(home)])

    assert args.handler(args) == 0

    model_dir = home / "models" / "multilingual-e5-small"
    values = _read_env(home / ".env")
    assert values["MT_EMBEDDING_MODE"] == "local"
    assert values["MT_EMBED_MODEL_DIR"] == str(model_dir)
    assert downloads == [model_dir]
    output = capsys.readouterr().out
    assert "Downloading the local" in output
    assert "~252 MB" in output


def test_noninteractive_remote_embedding_accepts_independent_credentials(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        "memtranslator.embedding.download_local_model",
        lambda _path: (_ for _ in ()).throw(AssertionError("must not download")))
    home = tmp_path / "runtime"
    args = build_parser().parse_args([
        "init", "--non-interactive", "--home", str(home),
        "--provider", "ark", "--api-key", "llm-key",
        "--embedding-mode", "remote", "--embedding-model", "embed-v2",
        "--embedding-api-key", "embed-key",
        "--embedding-base-url", "https://embed.example/v1/",
    ])

    assert args.handler(args) == 0

    values = _read_env(home / ".env")
    assert values["MT_EMBEDDING_MODE"] == "remote"
    assert values["MT_EMBEDDING_MODEL"] == "embed-v2"
    assert values["MT_EMBEDDING_API_KEY"] == "embed-key"
    assert values["MT_EMBEDDING_BASE_URL"] == "https://embed.example/v1"


def test_start_accepts_demo_short_and_long_flags():
    parser = build_parser()

    assert parser.parse_args(["start", "-demo"]).demo is True
    assert parser.parse_args(["start", "--demo"]).demo is True


def test_init_accepts_native_anthropic_api_format(tmp_path, monkeypatch):
    _fake_local_embedding(monkeypatch)
    home = tmp_path / "runtime"
    args = build_parser().parse_args([
        "init", "--non-interactive", "--home", str(home),
        "--api-format", "anthropic", "--model", "claude-test",
        "--base-url", "https://anthropic.example", "--api-key", "key",
    ])

    assert args.handler(args) == 0

    values = _read_env(home / ".env")
    assert values["MT_LLM_API_FORMAT"] == "anthropic"
    assert values["MT_TRANSLATOR"] == "claude-test"
    assert values["LLM_BASE_URL"] == "https://anthropic.example"
    assert values["LLM_API_KEY"] == "key"
