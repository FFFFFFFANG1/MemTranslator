"""Installed command-line entry point for MemTranslator."""
from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _default_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MemTranslator"
    return Path.home() / ".memtranslator"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _env_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("configuration values cannot contain newlines")
    if not value or re.search(r"\s|#|['\"]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _write_env(path: Path, values: dict[str, str]) -> None:
    preferred = [
        "MT_PORT", "MT_LLM_API_FORMAT", "MT_TRANSLATOR", "MT_WRITER",
        "MT_DOWNSTREAM",
        "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY",
        "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
        "MT_EMBEDDING_MODE", "MT_EMBEDDING_MODEL",
        "MT_EMBEDDING_BASE_URL", "MT_EMBEDDING_API_KEY",
        "MT_EMBED_MODEL_DIR",
    ]
    ordered = [key for key in preferred if key in values]
    ordered.extend(sorted(set(values) - set(ordered)))
    body = "# MemTranslator configuration\n" + "".join(
        f"{key}={_env_value(values[key])}\n" for key in ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o600)


def _prompt(label: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or default


def _confirm(label: str, *, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        answer = input(f"{label}{suffix}: ").strip().casefold()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _required_prompt(label: str, default: str = "") -> str:
    while True:
        value = _prompt(label, default)
        if value:
            return value
        print(f"{label} is required.")


def _api_format_for(model: str) -> str:
    if model.startswith("ark:") or "/" in model:
        return "openai-compatible"
    return "anthropic"


def _api_model(model: str) -> str:
    return (model.removeprefix("ark:")
            .removeprefix("openrouter:")
            .removeprefix("anthropic:"))


def init_command(args: argparse.Namespace) -> int:
    from memtranslator.embedding import (EmbeddingUnavailable,
                                         download_local_model)

    home = Path(args.home or _default_home()).expanduser().resolve()
    env_file = home / ".env"
    source_env = Path.cwd() / ".env"
    values = _read_env(source_env) if source_env != env_file else {}
    values.update(_read_env(env_file))

    existing_model = values.get("MT_TRANSLATOR", "ark:deepseek-v4-flash")
    legacy_format = {
        "ark": "openai-compatible", "openrouter": "openai-compatible",
        "anthropic": "anthropic",
    }.get(args.provider or "")
    api_format = (args.api_format or legacy_format
                  or values.get("MT_LLM_API_FORMAT")
                  or _api_format_for(existing_model))
    model_defaults = {
        "openai-compatible": (_api_model(existing_model)
                              if _api_format_for(existing_model)
                              == "openai-compatible"
                              else "deepseek-v4-flash"),
        "anthropic": (_api_model(existing_model)
                      if _api_format_for(existing_model) == "anthropic"
                      else "claude-sonnet-4-5"),
    }
    port = str(args.port or values.get("MT_PORT", "8123"))
    model = args.model or model_defaults[api_format]
    if "LLM_BASE_URL" in values:
        saved_base_url = values["LLM_BASE_URL"]
    elif api_format == "anthropic":
        saved_base_url = values.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    elif "/" in existing_model and not existing_model.startswith("ark:"):
        saved_base_url = values.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    else:
        saved_base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
    base_url = args.base_url or saved_base_url

    if not args.non_interactive:
        port = _prompt("Backend port", port)
        initial_api_format = api_format
        api_format = _prompt(
            "LLM API format (openai-compatible/anthropic)", api_format)
        if api_format not in {"openai-compatible", "anthropic"}:
            raise SystemExit(f"Unsupported API format: {api_format}")
        model = _prompt("Model", model_defaults[api_format])
        if api_format != initial_api_format and not args.base_url:
            base_url = ("https://api.anthropic.com"
                        if api_format == "anthropic"
                        else "https://ark.cn-beijing.volces.com/api/coding/v3")
        base_url = _prompt("Base URL", base_url)

    model_id = _api_model(model)
    values.update({
        "MT_PORT": port,
        "MT_LLM_API_FORMAT": api_format,
        "MT_TRANSLATOR": model_id,
        "MT_WRITER": model_id,
        "MT_DOWNSTREAM": model_id,
        "LLM_MODEL": model_id,
        "LLM_BASE_URL": base_url.rstrip("/"),
    })

    legacy_key = (values.get("ANTHROPIC_API_KEY", "")
                  if api_format == "anthropic"
                  else values.get("OPENROUTER_API_KEY", ""))
    api_key = args.api_key or values.get("LLM_API_KEY", "") or legacy_key
    if not args.non_interactive:
        label = ("LLM_API_KEY (Enter keeps existing)"
                 if api_key else "LLM_API_KEY")
        entered = getpass.getpass(f"{label}: ").strip()
        api_key = entered or api_key
    if api_key:
        values["LLM_API_KEY"] = api_key
    for legacy_key_name in (
            "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL",
            "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        values.pop(legacy_key_name, None)

    # Embedding is configured only after the LLM connection is complete.
    # Interactive "no" means the default local CPU service, not disabled.
    embedding_mode = args.embedding_mode
    if embedding_mode is None:
        if args.embedding_model:
            embedding_mode = "remote"
        elif args.non_interactive:
            embedding_mode = "local"
        else:
            print("\nEmbedding configuration")
            use_remote = _confirm("Configure a remote embedding API?")
            embedding_mode = "remote" if use_remote else "local"

    if embedding_mode == "remote":
        embedding_model = args.embedding_model
        if not args.non_interactive:
            embedding_model = _required_prompt(
                "Embedding model name",
                embedding_model or values.get("MT_EMBEDDING_MODEL", ""))
            print("Press Enter for the next two fields to reuse the LLM "
                  "API key and base URL. The reused endpoint must expose "
                  "an OpenAI-compatible /embeddings API.")
            embedding_api_key = getpass.getpass(
                "Embedding API key (Enter uses LLM API key): ").strip()
            embedding_base_url = input(
                "Embedding base URL (Enter uses LLM base URL): ").strip()
        else:
            embedding_api_key = args.embedding_api_key or ""
            embedding_base_url = args.embedding_base_url or ""
        if not embedding_model:
            raise SystemExit(
                "--embedding-model is required for remote embedding")
        values["MT_EMBEDDING_MODE"] = "remote"
        values["MT_EMBEDDING_MODEL"] = embedding_model
        if embedding_api_key:
            values["MT_EMBEDDING_API_KEY"] = embedding_api_key
        else:
            values.pop("MT_EMBEDDING_API_KEY", None)
        if embedding_base_url:
            values["MT_EMBEDDING_BASE_URL"] = embedding_base_url.rstrip("/")
        else:
            values.pop("MT_EMBEDDING_BASE_URL", None)
        values.pop("MT_EMBED_MODEL_DIR", None)
    else:
        embedding_dir = Path(
            args.embedding_dir
            or values.get("MT_EMBED_MODEL_DIR", "")
            or home / "models" / "multilingual-e5-small").expanduser().resolve()
        print("No remote embedding API selected. Downloading the local "
              "multilingual-e5-small ONNX CPU model (~252 MB).")
        try:
            download_local_model(embedding_dir)
        except EmbeddingUnavailable as exc:
            raise SystemExit(f"Local embedding setup failed: {exc}") from exc
        print(f"Local embedding model ready at {embedding_dir}")
        values["MT_EMBEDDING_MODE"] = "local"
        values["MT_EMBED_MODEL_DIR"] = str(embedding_dir)
        values.pop("MT_EMBEDDING_MODEL", None)
        values.pop("MT_EMBEDDING_API_KEY", None)
        values.pop("MT_EMBEDDING_BASE_URL", None)

    _write_env(env_file, values)
    data_dir = home / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (home / "models").mkdir(parents=True, exist_ok=True)
    imported = source_env.exists() and source_env != env_file
    migrated: list[str] = []
    source_data = Path.cwd() / "data"
    if source_data != data_dir and source_data.is_dir():
        for name in ("store.jsonl", "events.jsonl"):
            source = source_data / name
            target = data_dir / name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
                migrated.append(name)
    print(f"Initialized MemTranslator at {home}")
    if imported:
        print(f"Imported existing settings from {source_env}")
    if migrated:
        print("Migrated memory data: " + ", ".join(migrated))
    if not api_key:
        print("Warning: LLM_API_KEY is empty; "
              f"add it to {env_file} before translating.")
    return 0


def _health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=0.5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _seed_demo(url: str) -> dict:
    request = urllib.request.Request(
        url + "/api/demo/seed", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            import json
            return json.loads(response.read().decode())
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise SystemExit(f"Could not import demo rules: {exc}") from exc


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def start_command(args: argparse.Namespace) -> int:
    home = Path(args.home or _default_home()).expanduser().resolve()
    env_file = home / ".env"
    saved = _read_env(env_file)
    if not env_file.exists() and not any(
            os.environ.get(key) for key in
            ("LLM_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")):
        raise SystemExit(
            "MemTranslator is not initialized. "
            "Run `memtranslator init` first.")

    os.environ["MT_HOME"] = str(home)
    for key, value in saved.items():
        os.environ.setdefault(key, value)
    port = int(args.port or os.environ.get("MT_PORT", "8123"))
    os.environ["MT_PORT"] = str(port)
    url = f"http://127.0.0.1:{port}"
    os.environ["MT_DAEMON_URL"] = url

    backend: subprocess.Popen | None = None
    if _health(url):
        print(f"Using existing backend at {url}")
    else:
        backend = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "memtranslator.server:app",
            "--host", "127.0.0.1", "--port", str(port),
        ])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _health(url):
                break
            if backend.poll() is not None:
                raise SystemExit(f"Backend exited with status {backend.returncode}")
            time.sleep(0.1)
        else:
            _stop(backend)
            raise SystemExit("Backend did not become ready within 15 seconds")
        print(f"Backend ready at {url}")

    if args.demo:
        seeded = _seed_demo(url)
        print("Demo rules ready: "
              f"{seeded.get('total', 10)} total, "
              f"{seeded.get('added', 0)} added")

    if not args.no_open:
        webbrowser.open(url)

    try:
        if sys.platform == "darwin" and not args.server_only:
            from memtranslator.hotkey.__main__ import main as hotkey_main
            print("Starting macOS menu-bar client (hotkey: ⌥⌘R)")
            hotkey_main()
        else:
            print("Press Ctrl+C to stop MemTranslator")
            while backend is None or backend.poll() is None:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _stop(backend)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memtranslator")
    try:
        package_version = version("memtranslator")
    except PackageNotFoundError:
        package_version = "0.2.0"
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {package_version}")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="configure local runtime state")
    init_parser.add_argument("--home")
    init_parser.add_argument("--port", type=int)
    init_parser.add_argument(
        "--api-format", choices=("openai-compatible", "anthropic"))
    # Compatibility for existing init scripts; new help exposes API format.
    init_parser.add_argument(
        "--provider", choices=("ark", "openrouter", "anthropic"),
        help=argparse.SUPPRESS)
    init_parser.add_argument("--model")
    init_parser.add_argument("--base-url")
    init_parser.add_argument("--api-key")
    init_parser.add_argument("--embedding-dir")
    init_parser.add_argument("--embedding-mode", choices=("local", "remote"))
    init_parser.add_argument("--embedding-model")
    init_parser.add_argument("--embedding-api-key")
    init_parser.add_argument("--embedding-base-url")
    init_parser.add_argument("--non-interactive", action="store_true")
    init_parser.set_defaults(handler=init_command)

    start_parser = commands.add_parser("start", help="start backend and macOS client")
    start_parser.add_argument("--home")
    start_parser.add_argument("--port", type=int)
    start_parser.add_argument("--server-only", action="store_true")
    start_parser.add_argument("--no-open", action="store_true")
    start_parser.add_argument("-demo", "--demo", action="store_true",
                              help="import ten curated demo memory rules")
    start_parser.set_defaults(handler=start_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
