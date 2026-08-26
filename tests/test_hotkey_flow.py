import importlib.util
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("Quartz") is None:
    pytest.skip("pyobjc not installed (hotkey group)", allow_module_level=True)

from memtranslator.hotkey import axtext
from memtranslator.hotkey import __main__ as hotkey_main
from memtranslator.hotkey.__main__ import App, polish_flow
from memtranslator.hotkey.models import InputSnapshot, TextRange, WriteResult


def test_applied_writes_back():
    wrote = {}
    out = polish_flow(
        read=lambda: "raw",
        write=lambda t: wrote.setdefault("t", t) or True,
        post=lambda t: {"decision": "apply", "polished": "POLISHED"})
    assert out == "applied" and wrote["t"] == "POLISHED"


def test_noop_leaves_field_alone():
    out = polish_flow(read=lambda: "raw", write=lambda t: (_ for _ in ()).throw(
        AssertionError("must not write")), post=lambda t: {"decision": "noop"})
    assert out == "noop"


def test_empty_and_daemon_down():
    assert polish_flow(read=lambda: "  ", write=None, post=None) == "empty"

    def boom(t):
        raise OSError("down")

    assert polish_flow(read=lambda: "raw", write=None, post=boom) == "daemon_down"


def test_chromium_renderer_accessibility_is_enabled_once(monkeypatch):
    class Frontmost:
        @staticmethod
        def bundleIdentifier():
            return "com.google.Chrome"

        @staticmethod
        def localizedName():
            return "Google Chrome"

        @staticmethod
        def processIdentifier():
            return 42

    class Workspace:
        @staticmethod
        def sharedWorkspace():
            return Workspace()

        @staticmethod
        def frontmostApplication():
            return Frontmost()

    writes = []
    monkeypatch.setattr(axtext, "NSWorkspace", Workspace)
    monkeypatch.setattr(axtext, "AXUIElementCreateApplication",
                        lambda _pid: "application")
    monkeypatch.setattr(axtext, "_copy", lambda _element, attribute:
                        "window" if attribute == axtext.kAXFocusedWindowAttribute
                        else None)
    monkeypatch.setattr(axtext, "AXUIElementSetAttributeValue",
                        lambda target, attribute, value:
                        writes.append((target, attribute, value)) or 0)
    monkeypatch.setattr(axtext.time, "sleep", lambda _seconds: None)
    axtext._WEB_AX_ENABLED_PIDS.clear()

    assert axtext._enable_frontmost_web_accessibility() is True
    assert axtext._enable_frontmost_web_accessibility() is False
    assert ("application", "AXEnhancedUserInterface", True) in writes
    assert ("window", "AXManualAccessibility", True) in writes


def test_web_domain_capture_keeps_only_hostname(monkeypatch):
    parents = {"input": "group", "group": "webarea", "webarea": None}

    def copy(element, attribute):
        if attribute == "AXParent":
            return parents.get(element)
        if element == "webarea" and attribute == "AXURL":
            return "https://www.chatgpt.com/c/secret?token=private"
        return None

    monkeypatch.setattr(axtext, "_copy", copy)

    assert axtext._focused_web_domain("input") == "chatgpt.com"
    assert axtext._domain_from_url("file:///tmp/private") == ""


def test_capture_snapshot_includes_web_domain(monkeypatch):
    monkeypatch.setattr(axtext, "_focused_element", lambda: "input")
    monkeypatch.setattr(
        axtext, "AXUIElementCopyAttributeValue",
        lambda _element, attribute, _default:
        (0, "draft") if attribute == axtext.kAXValueAttribute else (1, None))
    monkeypatch.setattr(axtext, "_copy", lambda *_args: None)
    monkeypatch.setattr(axtext, "_frontmost_app", lambda: (
        "Google Chrome", "com.google.Chrome"))
    monkeypatch.setattr(axtext, "_focused_web_domain",
                        lambda _element: "gemini.google.com")
    monkeypatch.setattr(axtext, "_is_settable", lambda *_args: True)

    snapshot = axtext.capture_focused_input()

    assert snapshot is not None
    assert snapshot.web_domain == "gemini.google.com"
    assert snapshot.context()["web_domain"] == "gemini.google.com"


def test_adapter_retries_a_temporarily_empty_focused_value(monkeypatch):
    """Electron can expose the focused editor before its AXValue catches up."""
    values = iter(["", "draft typed immediately before the hotkey"])
    monkeypatch.setattr(axtext, "_focused_element", lambda: "input")
    monkeypatch.setattr(
        axtext, "AXUIElementCopyAttributeValue",
        lambda _element, attribute, _default:
        (0, next(values)) if attribute == axtext.kAXValueAttribute
        else (1, None))
    monkeypatch.setattr(axtext, "_copy", lambda *_args: None)
    monkeypatch.setattr(axtext, "_frontmost_app", lambda: (
        "Codex", "com.openai.codex"))
    monkeypatch.setattr(axtext, "_focused_web_domain", lambda _element: "")
    monkeypatch.setattr(axtext, "_is_settable", lambda *_args: True)
    monkeypatch.setattr(axtext.time, "sleep", lambda _seconds: None)

    snapshot = axtext.MacOSInputAdapter().capture()

    assert snapshot is not None
    assert snapshot.full_text == "draft typed immediately before the hotkey"


def test_write_verification_waits_for_ax_value_to_catch_up(monkeypatch):
    """A successful Electron paste is not immediately visible through AXValue."""
    stale = InputSnapshot(
        identity="composer", full_text="raw", target_range=TextRange(0, 3))
    written = InputSnapshot(
        identity="composer", full_text="polished",
        target_range=TextRange(0, 8))
    captures = iter([stale, written])
    monkeypatch.setattr(axtext, "capture_focused_input",
                        lambda: next(captures))
    monkeypatch.setattr(axtext.time, "sleep", lambda _seconds: None)

    assert axtext._verify("polished", "composer") is True


def test_write_guard_retries_a_temporarily_stale_prewrite_read(monkeypatch):
    original = InputSnapshot(
        identity="composer", full_text="raw", target_range=TextRange(0, 3),
        editable=True)
    temporarily_empty = InputSnapshot(
        identity="composer", full_text="", target_range=TextRange(0, 0),
        editable=True)
    captures = iter([temporarily_empty, original])
    monkeypatch.setattr(axtext, "capture_focused_input",
                        lambda: next(captures))
    monkeypatch.setattr(axtext.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(axtext, "resolve_profile", lambda _snapshot:
                        SimpleNamespace(enabled=True, write_order=("value",)))
    monkeypatch.setattr(axtext, "_focused_element", lambda: "input")
    monkeypatch.setattr(
        axtext, "_write_value",
        lambda _element, _snapshot, _polished, expected:
        WriteResult(True, "value", expected_full_text=expected))

    result = axtext.write_snapshot(original, "polished")

    assert result.ok is True


def test_hotkey_callback_defers_ax_capture_until_after_it_returns(monkeypatch):
    calls = []
    pending = {}

    class Tracker:
        active = False

    class Adapter:
        @staticmethod
        def capture():
            calls.append("capture")
            return None

    class Controller:
        tracker = Tracker()
        adapter = Adapter()

        @staticmethod
        def polish(snapshot=None):
            calls.append(("polish", snapshot))
            return {"status": "empty"}

    class Overlay:
        @staticmethod
        def start(_bounds):
            calls.append("overlay_start")

        @staticmethod
        def show(*_args, **_kwargs):
            calls.append("overlay_show")

    class Host:
        _pointer_timer = None
        controller = Controller()
        overlay = Overlay()

        @staticmethod
        def _set_state(*_args, **_kwargs):
            pass

    class DeferredThread:
        def __init__(self, *, target, daemon):
            assert daemon is True
            pending["target"] = target

        @staticmethod
        def start():
            pass

    monkeypatch.setattr(hotkey_main.threading, "Thread", DeferredThread)
    monkeypatch.setattr(hotkey_main.time, "sleep", lambda _seconds: None)

    App.on_hotkey(Host())

    assert calls == []
    pending["target"]()
    assert calls[:2] == ["capture", "overlay_start"]


def test_state_reset_timer_cannot_hold_process_open(monkeypatch):
    timers = []

    class Timer:
        def __init__(self, delay, callback):
            self.delay = delay
            self.callback = callback
            self.daemon = False
            self.started = False
            timers.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            pass

    class Button:
        @staticmethod
        def setTitle_(_glyph):
            pass

    class StatusItem:
        @staticmethod
        def button():
            return Button()

    class StateItem:
        @staticmethod
        def setTitle_(_text):
            pass

    host = SimpleNamespace(
        _shutting_down=False,
        _state_timer=None,
        status_item=StatusItem(),
        state_item=StateItem(),
    )
    monkeypatch.setattr(hotkey_main.threading, "Timer", Timer)
    monkeypatch.setattr(
        hotkey_main.AppHelper, "callAfter", lambda callback: callback())

    App._set_state(host, "✓", "Saved", 2.2)

    assert len(timers) == 1
    assert timers[0].daemon is True
    assert timers[0].started is True


def test_hotkey_main_installs_interrupt_bridge_and_disables_event_tap(
        monkeypatch):
    calls = []

    class NSApp:
        @staticmethod
        def setActivationPolicy_(policy):
            calls.append(("activation_policy", policy))

    class Application:
        @staticmethod
        def sharedApplication():
            return NSApp()

    class AppInstance:
        def shutdown(self):
            calls.append(("app_shutdown",))

    class AppFactory:
        @staticmethod
        def alloc():
            return AppFactory()

        @staticmethod
        def init():
            return AppInstance()

    monkeypatch.setattr(hotkey_main.axtext, "ensure_trusted", lambda: True)
    monkeypatch.setattr(hotkey_main, "NSApplication", Application)
    monkeypatch.setattr(hotkey_main, "App", AppFactory)
    monkeypatch.setattr(hotkey_main, "CGEventTapCreate", lambda *_args: "tap")
    monkeypatch.setattr(hotkey_main, "CFMachPortCreateRunLoopSource",
                        lambda *_args: "source")
    monkeypatch.setattr(hotkey_main, "CFRunLoopGetCurrent", lambda: "runloop")
    monkeypatch.setattr(hotkey_main, "CFRunLoopAddSource",
                        lambda *_args: None)
    monkeypatch.setattr(
        hotkey_main, "CGEventTapEnable",
        lambda tap, enabled: calls.append(("tap_enabled", tap, enabled)))
    monkeypatch.setattr(
        hotkey_main.AppHelper, "runEventLoop",
        lambda **kwargs: calls.append(("event_loop", kwargs)))
    monkeypatch.setattr(
        hotkey_main.signal, "getsignal", lambda signum:
        calls.append(("get_signal", signum)) or "previous-handler")
    monkeypatch.setattr(
        hotkey_main.signal, "signal", lambda signum, handler:
        calls.append(("restore_signal", signum, handler)))

    hotkey_main.main()

    assert ("event_loop", {"installInterrupt": True}) in calls
    assert ("tap_enabled", "tap", True) in calls
    assert ("tap_enabled", "tap", False) in calls
    assert ("restore_signal", hotkey_main.signal.SIGINT,
            "previous-handler") in calls
    assert calls[-1] == ("app_shutdown",)
