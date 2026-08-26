"""Capability profiles for known macOS input surfaces."""
from __future__ import annotations

from dataclasses import dataclass

from memtranslator.hotkey.models import InputSnapshot
from memtranslator.source_policy import AI_APP_BUNDLES, BROWSER_BUNDLES


@dataclass(frozen=True)
class InputProfile:
    name: str
    write_order: tuple[str, ...]
    enter_submits: bool = True
    enabled: bool = True


GENERIC = InputProfile("generic-ax", ("value", "paste"))
ELECTRON = InputProfile("electron-composer", ("paste", "value"))
BROWSER = InputProfile("browser-editor", ("paste",))
PASTE_ONLY = InputProfile("paste-only", ("paste",))
DISABLED = InputProfile("protected-input", (), enabled=False)
TERMINAL_UNSUPPORTED = InputProfile("terminal-needs-shell-adapter", (),
                                    enabled=False)

_ELECTRON_BUNDLES = {
    "com.tinyspeck.slackmacgap",
    "com.microsoft.teams2",
    "com.hnc.Discord",
    "notion.id",
    "com.openai.chat",
} | set(AI_APP_BUNDLES)
_BROWSER_BUNDLES = set(BROWSER_BUNDLES)
_TERMINAL_BUNDLES = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "dev.warp.Warp-Stable",
    "net.kovidgoyal.kitty",
    "com.github.wez.wezterm",
    "org.alacritty",
}


def resolve_profile(snapshot: InputSnapshot) -> InputProfile:
    role = f"{snapshot.role} {snapshot.subrole}".casefold()
    if snapshot.secure or "secure" in role or "password" in role:
        return DISABLED
    if snapshot.app_bundle_id in _TERMINAL_BUNDLES:
        return TERMINAL_UNSUPPORTED
    if snapshot.app_bundle_id in _ELECTRON_BUNDLES:
        return ELECTRON
    if snapshot.app_bundle_id in _BROWSER_BUNDLES:
        return BROWSER
    if not snapshot.value_settable:
        return PASTE_ONLY
    return GENERIC
