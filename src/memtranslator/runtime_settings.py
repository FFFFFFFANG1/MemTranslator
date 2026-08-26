"""Runtime-editable LLM and embedding configuration.

The WebUI only receives redacted connection metadata. Secrets are persisted in
the application's ``.env`` and are represented to the browser as booleans.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from memtranslator import config, llm
from memtranslator.embedding import (ARK_BASE_URL, LOCAL_MODEL_REPO,
                                     OPENROUTER_BASE_URL,
                                     download_local_model, local_model_ready)


API_FORMATS = ("openai-compatible", "anthropic")
ANTHROPIC_CHAT_BASE_URL = "https://api.anthropic.com"
PREFERRED_ENV_ORDER = [
    "MT_PORT", "MT_LLM_API_FORMAT", "MT_TRANSLATOR", "MT_WRITER",
    "MT_DOWNSTREAM",
    "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY",
    "OPENROUTER_BASE_URL", "OPENROUTER_API_KEY",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
    "MT_EMBEDDING_MODE", "MT_EMBEDDING_MODEL",
    "MT_EMBEDDING_BASE_URL", "MT_EMBEDDING_API_KEY",
    "MT_EMBED_MODEL_DIR", "MT_EMBED_ONNX_FILE",
]


def read_env(path: Path) -> dict[str, str]:
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


def write_env(path: Path, values: dict[str, str]) -> None:
    ordered = [key for key in PREFERRED_ENV_ORDER if key in values]
    ordered.extend(sorted(set(values) - set(ordered)))
    body = "# MemTranslator configuration\n" + "".join(
        f"{key}={_env_value(values[key])}\n" for key in ordered)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(body)
    temporary.chmod(0o600)
    temporary.replace(path)


def api_format_for(model: str) -> str:
    """Infer the old three-provider configuration during migration."""
    if model.startswith("ark:") or "/" in model:
        return "openai-compatible"
    return "anthropic"


def api_model(model: str) -> str:
    model = model.strip()
    return (model.removeprefix("ark:")
            .removeprefix("openrouter:")
            .removeprefix("anthropic:"))


class RuntimeSettings:
    """Persist settings and refresh the in-process service singletons."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.home = self.path.parent
        self._lock = threading.Lock()

    def _value(self, values: dict[str, str], key: str,
               default: str = "") -> str:
        if key in os.environ:
            return os.environ[key]
        return values.get(key, default)

    def _llm_snapshot(self, values: dict[str, str]) -> dict:
        model_id = self._value(
            values, "MT_TRANSLATOR", config.MODELS["translator"])
        api_format = self._value(
            values, "MT_LLM_API_FORMAT", api_format_for(model_id))
        legacy_openrouter = "/" in model_id and not model_id.startswith("ark:")
        if "LLM_API_KEY" in values or "LLM_API_KEY" in os.environ:
            api_key = self._value(values, "LLM_API_KEY")
        elif api_format == "anthropic":
            api_key = self._value(values, "ANTHROPIC_API_KEY")
        elif legacy_openrouter:
            api_key = self._value(values, "OPENROUTER_API_KEY")
        else:
            api_key = ""
        if "LLM_BASE_URL" in values or "LLM_BASE_URL" in os.environ:
            base_url = self._value(values, "LLM_BASE_URL")
        elif api_format == "anthropic":
            base_url = self._value(
                values, "ANTHROPIC_BASE_URL", ANTHROPIC_CHAT_BASE_URL)
        elif legacy_openrouter:
            base_url = self._value(
                values, "OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)
        else:
            base_url = ARK_BASE_URL
        return {
            "api_format": api_format,
            "model": api_model(model_id),
            "base_url": base_url,
            "api_key": api_key,
            "has_api_key": bool(api_key),
        }

    def snapshot(self) -> dict:
        values = read_env(self.path)
        llm_info = self._llm_snapshot(values)
        mode = self._value(values, "MT_EMBEDDING_MODE", "local").casefold()
        if mode not in {"local", "remote"}:
            mode = "local"
        model_dir = Path(self._value(
            values, "MT_EMBED_MODEL_DIR",
            str(self.home / "models" / "multilingual-e5-small")))
        embedding_key = self._value(values, "MT_EMBEDDING_API_KEY")
        embedding_base = self._value(values, "MT_EMBEDDING_BASE_URL")
        embedding_model = self._value(values, "MT_EMBEDDING_MODEL")
        embedding = {
            "mode": mode,
            "model": (embedding_model if mode == "remote"
                      else LOCAL_MODEL_REPO),
            "base_url": (embedding_base if mode == "remote" else ""),
            "api_key": (embedding_key if mode == "remote" else ""),
            "has_api_key": bool(embedding_key),
            "uses_llm_api_key": mode == "remote" and not bool(embedding_key),
            "uses_llm_base_url": mode == "remote" and not bool(embedding_base),
            "local_model_ready": local_model_ready(model_dir),
            "local_model_dir": str(model_dir),
        }
        return {"llm": llm_info, "embedding": embedding}

    @staticmethod
    def _refresh_services() -> None:
        llm.reset_clients()
        from memtranslator.retrieval import clear_retrieval_caches
        clear_retrieval_caches()

    def _save(self, values: dict[str, str], changed: set[str],
              removed: set[str]) -> dict:
        write_env(self.path, values)
        for key in changed:
            os.environ[key] = values[key]
        for key in removed:
            os.environ.pop(key, None)
        config.MODELS.update({
            "translator": values.get(
                "MT_TRANSLATOR", config.MODELS["translator"]),
            "writer": values.get("MT_WRITER", config.MODELS["writer"]),
            "downstream": values.get(
                "MT_DOWNSTREAM", config.MODELS["downstream"]),
        })
        if "MT_EMBED_MODEL_DIR" in values:
            config.EMBED_MODEL_DIR = Path(values["MT_EMBED_MODEL_DIR"])
        if "MT_EMBED_ONNX_FILE" in values:
            config.EMBED_ONNX_FILE = values["MT_EMBED_ONNX_FILE"]
        elif "MT_EMBED_ONNX_FILE" in removed:
            config.EMBED_ONNX_FILE = "onnx/model_O4.onnx"
        self._refresh_services()
        return self.snapshot()

    def update_llm(self, *, api_format: str, model: str, base_url: str = "",
                   api_key: str | None = None) -> dict:
        api_format = api_format.strip().casefold()
        model = model.strip()
        if api_format not in API_FORMATS:
            raise ValueError(f"unsupported LLM API format: {api_format}")
        if not model:
            raise ValueError("LLM model is required")
        if api_format == "openai-compatible" and not base_url.strip():
            raise ValueError("base URL is required for OpenAI-compatible APIs")
        model_id = api_model(model)
        with self._lock:
            values = read_env(self.path)
            changed = {"MT_TRANSLATOR", "MT_WRITER", "MT_DOWNSTREAM",
                       "LLM_MODEL", "MT_LLM_API_FORMAT"}
            removed = {"OPENROUTER_API_KEY", "OPENROUTER_BASE_URL",
                       "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"}
            values.update({
                "MT_LLM_API_FORMAT": api_format,
                "MT_TRANSLATOR": model_id,
                "MT_WRITER": model_id,
                "MT_DOWNSTREAM": model_id,
                "LLM_MODEL": model_id.removeprefix("ark:"),
            })
            if base_url.strip():
                values["LLM_BASE_URL"] = base_url.strip().rstrip("/")
                changed.add("LLM_BASE_URL")
            else:
                values.pop("LLM_BASE_URL", None)
                removed.add("LLM_BASE_URL")
            if api_key is not None and api_key.strip():
                values["LLM_API_KEY"] = api_key.strip()
                changed.add("LLM_API_KEY")
            elif api_key is not None:
                values.pop("LLM_API_KEY", None)
                removed.add("LLM_API_KEY")
            for key in removed:
                values.pop(key, None)
            return self._save(values, changed, removed)

    def update_remote_embedding(self, *, model: str, base_url: str = "",
                                api_key: str = "") -> dict:
        model = model.strip()
        if not model:
            raise ValueError("embedding model is required")
        with self._lock:
            values = read_env(self.path)
            changed = {"MT_EMBEDDING_MODE", "MT_EMBEDDING_MODEL"}
            removed = {"MT_EMBED_MODEL_DIR"}
            values["MT_EMBEDDING_MODE"] = "remote"
            values["MT_EMBEDDING_MODEL"] = model
            values.pop("MT_EMBED_MODEL_DIR", None)
            for key, value in (
                    ("MT_EMBEDDING_BASE_URL", base_url),
                    ("MT_EMBEDDING_API_KEY", api_key)):
                if value.strip():
                    values[key] = (value.strip().rstrip("/")
                                   if "URL" in key else value.strip())
                    changed.add(key)
                else:
                    values.pop(key, None)
                    removed.add(key)
            return self._save(values, changed, removed)

    def use_default_embedding(self) -> tuple[dict, bool]:
        model_dir = self.home / "models" / "multilingual-e5-small"
        with self._lock:
            downloaded = not local_model_ready(model_dir)
            if downloaded:
                download_local_model(model_dir)
            values = read_env(self.path)
            values.update({
                "MT_EMBEDDING_MODE": "local",
                "MT_EMBED_MODEL_DIR": str(model_dir),
            })
            removed = {"MT_EMBEDDING_MODEL", "MT_EMBEDDING_BASE_URL",
                       "MT_EMBEDDING_API_KEY", "MT_EMBED_ONNX_FILE"}
            for key in removed:
                values.pop(key, None)
            snapshot = self._save(
                values, {"MT_EMBEDDING_MODE", "MT_EMBED_MODEL_DIR"}, removed)
            return snapshot, downloaded
