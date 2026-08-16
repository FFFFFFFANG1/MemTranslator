from dataclasses import replace

from memtranslator.hotkey.models import InputSnapshot, TextRange
from memtranslator.hotkey.profiles import resolve_profile


def _snapshot(bundle: str = "com.apple.TextEdit") -> InputSnapshot:
    return InputSnapshot(identity="box", full_text="text",
                         target_range=TextRange(0, 4),
                         app_bundle_id=bundle, role="AXTextArea")


def test_native_input_prefers_direct_value_write():
    assert resolve_profile(_snapshot()).write_order == ("value", "paste")


def test_electron_and_browser_inputs_prefer_verified_paste():
    assert resolve_profile(_snapshot(
        "com.tinyspeck.slackmacgap")).write_order[0] == "paste"
    assert resolve_profile(_snapshot(
        "com.google.Chrome")).write_order == ("paste",)


def test_capability_probe_routes_unknown_read_only_ax_value_to_paste():
    snapshot = replace(_snapshot("com.example.editor"),
                       value_settable=False)
    assert resolve_profile(snapshot).name == "paste-only"


def test_secure_input_is_disabled():
    profile = resolve_profile(replace(_snapshot(), secure=True))
    assert profile.enabled is False and profile.write_order == ()


def test_terminal_requires_shell_adapter_and_fails_closed():
    profile = resolve_profile(_snapshot("com.apple.Terminal"))
    assert profile.name == "terminal-needs-shell-adapter"
    assert profile.enabled is False and profile.write_order == ()
