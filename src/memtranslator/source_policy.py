"""Persistent source allowlist for desktop shortcuts and Route-A capture.

Option+Control shortcuts act only in configured AI clients and websites;
the menu's rewrite action remains usable in other supported inputs. Original
requests enter Extractor-A only on explicit Option+Control+Enter capture.

Browser matching deliberately fails closed. A browser context without a
readable domain is never eligible. Manual memory-manager actions do not use
this policy because they are direct memory-manager actions.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


BROWSER_BUNDLES = frozenset({
    "com.apple.Safari",
    "com.brave.Browser",
    "com.google.Chrome",
    "com.google.Chrome.beta",
    "com.google.Chrome.canary",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "org.mozilla.firefox",
})

# These remain capability hints for AX renderer activation and write profiles.
# The user-managed Route-A policy is DEFAULT_SOURCE_ENTRIES below.
AI_APP_BUNDLES = frozenset({
    "com.openai.chat",
    "com.openai.codex",
    "com.todesktop.230313mzl4w4u92",
    "com.anthropic.claudefordesktop",
    "com.anthropic.claude-code",
    "com.codeium.windsurf",
})
AI_APP_NAMES = frozenset({
    "chatgpt", "claude", "claude code", "codex", "cursor", "windsurf",
})

SOURCE_KINDS = frozenset({"app", "web"})


def _default(entry_id: str, label: str, kind: str,
             patterns: list[str]) -> dict:
    return {
        "id": entry_id,
        "label": label,
        "kind": kind,
        "patterns": patterns,
        "is_default": True,
        "created_at": 0.0,
        "updated_at": 0.0,
    }


DEFAULT_SOURCE_ENTRIES = (
    _default("source-app-codex", "Codex", "app",
             ["com.openai.codex", "Codex"]),
    _default("source-app-cursor", "Cursor", "app",
             ["com.todesktop.230313mzl4w4u92", "Cursor"]),
    _default("source-app-claude", "Claude", "app",
             ["com.anthropic.claudefordesktop", "Claude"]),
    _default("source-app-claude-code", "Claude Code", "app",
             ["com.anthropic.claude-code", "Claude Code"]),
    _default("source-app-chatgpt", "ChatGPT", "app",
             ["com.openai.chat", "ChatGPT"]),
    _default("source-app-windsurf", "Windsurf", "app",
             ["com.codeium.windsurf", "Windsurf"]),
    _default("source-web-chatgpt", "ChatGPT", "web",
             ["chatgpt.com", "chat.openai.com"]),
    _default("source-web-claude", "Claude", "web", ["claude.ai"]),
    _default("source-web-gemini", "Gemini", "web", ["gemini.google.com"]),
    _default("source-web-doubao", "豆包", "web", ["doubao.com"]),
    _default("source-web-deepseek", "DeepSeek", "web", ["deepseek.com"]),
    _default("source-web-kimi", "Kimi", "web",
             ["kimi.com", "kimi.moonshot.cn"]),
    _default("source-web-yuanbao", "元宝", "web", ["yuanbao.tencent.com"]),
    _default("source-web-perplexity", "Perplexity", "web",
             ["perplexity.ai"]),
    _default("source-web-poe", "Poe", "web", ["poe.com"]),
    _default("source-web-grok", "Grok", "web", ["grok.com"]),
    _default("source-web-copilot", "Copilot", "web",
             ["copilot.microsoft.com"]),
)


def _configured(name: str) -> set[str]:
    return {item.strip().casefold()
            for item in os.environ.get(name, "").split(",") if item.strip()}


def _normalise_domain(value: str) -> str:
    raw = value.strip().casefold()
    if "://" in raw:
        try:
            raw = urlsplit(raw).hostname or ""
        except ValueError:
            raw = ""
    raw = raw.removeprefix("*.").rstrip(".")
    if raw.startswith("www."):
        raw = raw[4:]
    if (not raw or len(raw) > 253 or " " in raw or "." not in raw
            or any(not part or len(part) > 63 for part in raw.split("."))):
        raise ValueError("website match must be a valid domain")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-.")
    if any(char not in allowed for char in raw):
        raise ValueError("website match must be a valid domain")
    return raw


def normalise_entry(*, label: str, kind: str, patterns: list[str],
                    entry_id: str | None = None, id: str | None = None,
                    is_default: bool = False,
                    created_at: float | None = None,
                    updated_at: float | None = None) -> dict:
    label = " ".join(str(label).split())
    kind = str(kind).strip().casefold()
    if not label or len(label) > 80:
        raise ValueError("label must be 1-80 characters")
    if kind not in SOURCE_KINDS:
        raise ValueError("kind must be app or web")
    if not isinstance(patterns, list):
        raise ValueError("patterns must be a list")
    cleaned = []
    seen = set()
    for pattern in patterns:
        value = str(pattern).strip()
        if not value:
            continue
        if kind == "web":
            value = _normalise_domain(value)
        elif len(value) > 180:
            raise ValueError("app match must be at most 180 characters")
        key = value.casefold()
        if key not in seen:
            cleaned.append(value)
            seen.add(key)
    if not cleaned:
        raise ValueError("at least one match value is required")
    now = time.time()
    return {
        "id": entry_id or id or f"source-{uuid.uuid4().hex[:12]}",
        "label": label,
        "kind": kind,
        "patterns": cleaned,
        "is_default": bool(is_default),
        "created_at": now if created_at is None else float(created_at),
        "updated_at": now if updated_at is None else float(updated_at),
    }


class SourceAllowlist:
    """Small atomically persisted CRUD store seeded exactly once."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                now = time.time()
                self._entries = {
                    item["id"]: normalise_entry(
                        **{**item, "created_at": now, "updated_at": now})
                    for item in DEFAULT_SOURCE_ENTRIES
                }
                return
            try:
                payload = json.loads(self.path.read_text())
                rows = payload.get("entries") if isinstance(payload, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("allowlist entries are malformed")
                loaded = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    entry = normalise_entry(**row)
                    loaded[entry["id"]] = entry
                self._entries = loaded
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"cannot load source allowlist: {exc}") from exc

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(
            {"version": 1, "entries": list(self._entries.values())},
            ensure_ascii=False, indent=2) + "\n")
        temporary.replace(self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._entries.values()]

    def add(self, *, label: str, kind: str, patterns: list[str]) -> dict:
        with self._lock:
            entry = normalise_entry(label=label, kind=kind, patterns=patterns)
            self._entries[entry["id"]] = entry
            self._save_locked()
            return dict(entry)

    def update(self, entry_id: str, *, label: str | None = None,
               kind: str | None = None,
               patterns: list[str] | None = None) -> dict:
        with self._lock:
            if entry_id not in self._entries:
                raise KeyError(entry_id)
            current = self._entries[entry_id]
            entry = normalise_entry(
                entry_id=entry_id,
                label=current["label"] if label is None else label,
                kind=current["kind"] if kind is None else kind,
                patterns=current["patterns"] if patterns is None else patterns,
                is_default=current["is_default"],
                created_at=current["created_at"],
                updated_at=time.time(),
            )
            self._entries[entry_id] = entry
            self._save_locked()
            return dict(entry)

    def delete(self, entry_id: str) -> dict:
        with self._lock:
            if entry_id not in self._entries:
                raise KeyError(entry_id)
            entry = self._entries.pop(entry_id)
            self._save_locked()
            return dict(entry)


def _domain_matches(domain: str, allowed: set[str]) -> bool:
    domain = domain.strip().casefold().rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == root or domain.endswith("." + root)
               for root in allowed)


def is_ai_app(*, app_bundle_id: str = "", app_name: str = "") -> bool:
    """Capability probe for AX handling, independent of learning policy."""
    bundles = set(AI_APP_BUNDLES) | _configured("MT_CAPTURE_APP_BUNDLES")
    names = set(AI_APP_NAMES) | _configured("MT_CAPTURE_APP_NAMES")
    return (app_bundle_id.strip().casefold() in {
                item.casefold() for item in bundles}
            or app_name.strip().casefold() in names)


def route_a_source_allowed(context: dict | None,
                           entries: list[dict] | None = None) -> bool:
    """Whether a desktop source is eligible for explicit memory capture."""
    if not isinstance(context, dict):
        return False
    if entries is None:
        entries = list(DEFAULT_SOURCE_ENTRIES)
        for value in _configured("MT_CAPTURE_APP_BUNDLES") \
                | _configured("MT_CAPTURE_APP_NAMES"):
            entries.append({"kind": "app", "patterns": [value]})
        for value in _configured("MT_CAPTURE_WEB_DOMAINS"):
            entries.append({"kind": "web", "patterns": [value]})
    bundle = str(context.get("app_bundle_id") or "").strip().casefold()
    name = str(context.get("app_name") or "").strip().casefold()
    browser = bundle in {item.casefold() for item in BROWSER_BUNDLES}
    if browser:
        domains = {str(pattern).casefold()
                   for entry in entries if entry.get("kind") == "web"
                   for pattern in entry.get("patterns") or []}
        return _domain_matches(str(context.get("web_domain") or ""), domains)
    app_patterns = {str(pattern).strip().casefold()
                    for entry in entries if entry.get("kind") == "app"
                    for pattern in entry.get("patterns") or []}
    return bool((bundle and bundle in app_patterns)
                or (name and name in app_patterns))
