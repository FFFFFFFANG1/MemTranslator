import importlib.util
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("Quartz") is None:
    pytest.skip("pyobjc not installed (hotkey group)", allow_module_level=True)

from memtranslator.hotkey import axtext
from memtranslator.hotkey import __main__ as hotkey_main
from memtranslator.hotkey.__main__ import App, write_flow
from memtranslator.hotkey.models import InputSnapshot, TextRange, WriteResult
from Quartz import (CGEventCreateKeyboardEvent, CGEventGetFlags,
                    CGEventGetIntegerValueField, CGEventGetType,
                    CGEventSetFlags, CGEventSetIntegerValueField,
                    kCGEventFlagMaskNumericPad, kCGEventSourceUserData)


def test_applied_writes_back():
    wrote = {}
    out = write_flow(
        read=lambda: "raw",
        write=lambda t: wrote.setdefault("t", t) or True,
        post=lambda t: {"decision": "apply", "polished": "POLISHED"})
    assert out == "applied" and wrote["t"] == "POLISHED"


def test_noop_leaves_field_alone():
    out = write_flow(read=lambda: "raw", write=lambda t: (_ for _ in ()).throw(
        AssertionError("must not write")), post=lambda t: {"decision": "noop"})
    assert out == "noop"


def test_empty_and_daemon_down():
    assert write_flow(read=lambda: "  ", write=None, post=None) == "empty"

    def boom(t):
        raise OSError("down")

    assert write_flow(read=lambda: "raw", write=None, post=boom) == "daemon_down"


@pytest.mark.parametrize("status", ["written", "write_noop", "write_failed", "daemon_down"])
def test_success_animation_requires_verified_write_back(status):
    from types import SimpleNamespace
    from unittest.mock import Mock

    snapshot = SimpleNamespace(screen_bounds=(10, 20, 300, 80), app_name="Demo")
    result = {"status": status, "snapshot": snapshot,
              "write": WriteResult(status == "written", "value")}
    host = SimpleNamespace(
        _pointer_timer=None,
        controller=SimpleNamespace(write=lambda **_kwargs: result),
        overlay=Mock(), _set_state=Mock())

    App.on_write(host, snapshot=snapshot, _synchronous=True)

    host.overlay.start.assert_called_once_with(snapshot.screen_bounds)
    if status == "written":
        host.overlay.complete.assert_called_once_with(snapshot.screen_bounds)
        host.overlay.show.assert_not_called()
    else:
        host.overlay.complete.assert_not_called()
        host.overlay.show.assert_called_once()


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


def test_known_input_can_be_read_once_after_focus_moves(monkeypatch):
    snapshot = InputSnapshot(
        identity="known-box",
        full_text="written",
        target_range=TextRange(0, 7),
    )
    axtext._remember_input_element(snapshot.identity, "original-element")
    monkeypatch.setattr(
        axtext,
        "AXUIElementCopyAttributeValue",
        lambda element, attribute, _default: (
            (0, "")
            if element == "original-element" and attribute == axtext.kAXValueAttribute
            else (1, None)
        ),
    )

    observed = axtext.capture_known_input(snapshot)

    assert observed is not None
    assert observed.identity == "known-box"
    assert observed.full_text == ""
    assert observed.target_range == TextRange(0, 0)


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

    class Adapter:
        @staticmethod
        def capture():
            calls.append("capture")
            return None

    class Controller:
        adapter = Adapter()

        @staticmethod
        def write(snapshot=None):
            calls.append(("write", snapshot))
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

    App.on_write(Host())

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


def _key_event(keycode, flags=0, *, down=True, repeat=False, tagged=False):
    event = CGEventCreateKeyboardEvent(None, keycode, down)
    CGEventSetFlags(event, flags)
    CGEventSetIntegerValueField(event, hotkey_main.kCGKeyboardEventAutorepeat, int(repeat))
    if tagged:
        CGEventSetIntegerValueField(event, kCGEventSourceUserData, axtext.SYNTHETIC_EVENT_TAG)
    return event


@pytest.mark.parametrize("keycode", [hotkey_main.KEY_R, 36, 76])
def test_fn_shortcuts_fire_once_and_consume_matching_keyup(keycode):
    calls = []
    app = SimpleNamespace(on_shortcut=lambda code, event: calls.append((code, event)))
    callback = hotkey_main.make_tap_callback(app)
    flags = hotkey_main.SHORTCUT_MODIFIERS
    down = _key_event(keycode, flags)
    repeated = _key_event(keycode, flags, repeat=True)
    up = _key_event(keycode, 0, down=False)
    assert callback(None, hotkey_main.kCGEventKeyDown, down, None) is None
    assert callback(None, hotkey_main.kCGEventKeyDown, repeated, None) is None
    assert callback(None, hotkey_main.kCGEventKeyUp, up, None) is None
    assert [code for code, _event in calls] == [keycode]
    callback(None, hotkey_main.kCGEventKeyDown, down, None)
    assert len(calls) == 2  # A new physical press is distinct.


def test_fn_keypad_enter_ignores_the_key_location_marker():
    calls = []
    app = SimpleNamespace(on_shortcut=lambda code, _event: calls.append(code))
    callback = hotkey_main.make_tap_callback(app)
    event = _key_event(
        76,
        hotkey_main.SHORTCUT_MODIFIERS | kCGEventFlagMaskNumericPad,
    )

    assert callback(None, hotkey_main.kCGEventKeyDown, event, None) is None
    assert calls == [76]


@pytest.mark.parametrize("keycode", [hotkey_main.KEY_R, 36])
@pytest.mark.parametrize("flags", [
    0,
    hotkey_main.kCGEventFlagMaskAlternate,
    hotkey_main.kCGEventFlagMaskControl,
    hotkey_main.kCGEventFlagMaskCommand,
    hotkey_main.kCGEventFlagMaskAlternate | hotkey_main.kCGEventFlagMaskCommand,
    hotkey_main.SHORTCUT_MODIFIERS | hotkey_main.kCGEventFlagMaskShift,
    hotkey_main.SHORTCUT_MODIFIERS | hotkey_main.kCGEventFlagMaskCommand,
    hotkey_main.SHORTCUT_MODIFIERS | hotkey_main.kCGEventFlagMaskAlternate,
    hotkey_main.SHORTCUT_MODIFIERS | hotkey_main.kCGEventFlagMaskControl,
])
def test_other_shortcuts_are_preserved(keycode, flags):
    plain_enter = keycode in hotkey_main.ENTER_KEYS and flags == 0
    app = SimpleNamespace(
        on_shortcut=lambda *_args: pytest.fail("Must pass through"),
        on_plain_enter=(lambda: None) if plain_enter else
        (lambda: pytest.fail("Not a plain Enter")),
    )
    event = _key_event(keycode, flags)
    callback = hotkey_main.make_tap_callback(app)
    assert callback(None, hotkey_main.kCGEventKeyDown, event, None) is event


def test_plain_enter_dismisses_and_synthetic_learn_enter_is_not_seen_twice():
    calls = []
    app = SimpleNamespace(on_plain_enter=lambda: calls.append("dismiss"),
                          on_shortcut=lambda *_args: pytest.fail("No Learn"))
    callback = hotkey_main.make_tap_callback(app)
    plain = _key_event(36)
    synthetic = _key_event(36, tagged=True)
    assert callback(None, hotkey_main.kCGEventKeyDown, plain, None) is plain
    assert callback(None, hotkey_main.kCGEventKeyDown, synthetic, None) is synthetic
    assert calls == ["dismiss"]


def test_app_plain_enter_uses_one_capture_and_only_dismisses():
    calls = []
    snapshot = InputSnapshot(
        identity="box", full_text="written", target_range=TextRange(0, 7))
    controller = SimpleNamespace(
        has_pending_write=True,
        adapter=SimpleNamespace(
            capture_once=lambda: calls.append("capture_once") or snapshot,
            capture=lambda: pytest.fail("Ordinary Enter must not retry"),
        ),
        dismiss=lambda captured: calls.append(("dismiss", captured.identity)),
        prepare_learn=lambda *_args: pytest.fail("Ordinary Enter must not Learn"),
    )

    App.on_plain_enter(SimpleNamespace(controller=controller))

    assert calls == ["capture_once", ("dismiss", "box")]


def test_app_plain_enter_without_pending_write_does_not_capture():
    controller = SimpleNamespace(
        has_pending_write=False,
        adapter=SimpleNamespace(
            capture_once=lambda: pytest.fail("Nothing is pending")),
    )

    App.on_plain_enter(SimpleNamespace(controller=controller))


def test_app_exposes_no_periodic_poll_loop():
    assert not hasattr(App, "_poll")
    assert not hasattr(App, "_schedule_poll")


def test_pointer_boundary_is_one_shot_and_only_dismisses_matching_empty(monkeypatch):
    calls = []
    before = InputSnapshot(
        identity="box", full_text="written", target_range=TextRange(0, 7))
    empty = InputSnapshot(
        identity="box", full_text="", target_range=TextRange(0, 0))

    class Timer:
        def __init__(self, delay, callback):
            assert delay == hotkey_main.POINTER_SETTLE_SECONDS
            self.callback = callback
            self.daemon = False
            self.cancelled = False

        def start(self):
            calls.append("timer_started")

        def cancel(self):
            self.cancelled = True

    timer = None

    def make_timer(delay, callback):
        nonlocal timer
        timer = Timer(delay, callback)
        return timer

    controller = SimpleNamespace(
        has_pending_write=True,
        adapter=SimpleNamespace(
            capture_once=lambda: calls.append("capture_once") or before,
            capture_known=lambda captured: calls.append(
                ("capture_known", captured.identity)) or empty,
            capture=lambda: pytest.fail("Pointer boundary must not poll"),
        ),
        matches_pending=lambda captured: captured.identity == "box",
        dismiss_if_empty=lambda captured: calls.append(
            ("dismiss_if_empty", captured.identity, captured.full_text)),
    )
    host = SimpleNamespace(controller=controller, _pointer_timer=None)
    monkeypatch.setattr(hotkey_main.threading, "Timer", make_timer)

    App.on_pointer_down(host)

    assert calls == ["capture_once", "timer_started"]
    assert timer is not None and timer.daemon is True
    timer.callback()
    assert calls == [
        "capture_once",
        "timer_started",
        ("capture_known", "box"),
        ("dismiss_if_empty", "box", ""),
    ]
    assert host._pointer_timer is None


def test_pointer_outside_pending_composer_does_not_schedule_a_read(monkeypatch):
    other = InputSnapshot(
        identity="other", full_text="draft", target_range=TextRange(0, 5))
    controller = SimpleNamespace(
        has_pending_write=True,
        adapter=SimpleNamespace(capture_once=lambda: other),
        matches_pending=lambda _captured: False,
    )
    host = SimpleNamespace(controller=controller, _pointer_timer=None)
    monkeypatch.setattr(
        hotkey_main.threading,
        "Timer",
        lambda *_args: pytest.fail("No matching pointer boundary"),
    )

    App.on_pointer_down(host)

    assert host._pointer_timer is None


def test_guarded_enter_posts_one_modifier_free_tagged_pair(monkeypatch):
    snapshot = InputSnapshot(identity="box", full_text="raw", target_range=TextRange(0, 3), app_pid=123)
    posted = []
    monkeypatch.setattr(axtext, "_capture_with_ax_retries", lambda: snapshot)
    monkeypatch.setattr(axtext, "frontmost_pid", lambda: 123)
    monkeypatch.setattr(axtext, "CGEventPostToPid", lambda pid, event: posted.append((pid, event)))

    assert axtext.send_enter(snapshot) is True
    assert len(posted) == 2
    assert [CGEventGetType(event) for _, event in posted] == [
        hotkey_main.kCGEventKeyDown, hotkey_main.kCGEventKeyUp]
    for pid, event in posted:
        assert pid == 123
        assert CGEventGetFlags(event) == 0
        assert CGEventGetIntegerValueField(event, hotkey_main.kCGKeyboardEventKeycode) == 36
        assert CGEventGetIntegerValueField(event, kCGEventSourceUserData) == axtext.SYNTHETIC_EVENT_TAG


@pytest.mark.parametrize("changes,frontmost", [
    ({"identity": "other-box"}, 123), ({"full_text": "changed"}, 123),
    ({"secure": True}, 123), ({"editable": False}, 123), ({}, 456),
])
def test_stale_or_protected_send_never_posts_a_key(monkeypatch, changes, frontmost):
    snapshot = InputSnapshot(identity="box", full_text="raw", target_range=TextRange(0, 3), app_pid=123)
    monkeypatch.setattr(axtext, "_capture_with_ax_retries", lambda: replace(snapshot, **changes))
    monkeypatch.setattr(axtext, "frontmost_pid", lambda: frontmost)
    monkeypatch.setattr(axtext, "CGEventPostToPid", lambda *_args: pytest.fail("Must not send"))
    assert axtext.send_enter(snapshot) is False


def test_unsupported_shortcut_replay_preserves_modifiers_and_avoids_recursion(monkeypatch):
    posted = []
    event = _key_event(hotkey_main.KEY_R, hotkey_main.SHORTCUT_MODIFIERS)
    monkeypatch.setattr(axtext, "frontmost_pid", lambda: 123)
    monkeypatch.setattr(axtext, "CGEventPostToPid", lambda pid, replay: posted.append((pid, replay)))
    assert axtext.replay_shortcut(event, 123) is True
    assert len(posted) == 2
    for pid, replay in posted:
        assert pid == 123
        assert CGEventGetFlags(replay) == hotkey_main.SHORTCUT_MODIFIERS
        assert CGEventGetIntegerValueField(replay, kCGEventSourceUserData) == axtext.SYNTHETIC_EVENT_TAG
    posted.clear()
    assert axtext.replay_shortcut(event, 456) is False
    assert posted == []


def test_secure_field_value_is_never_read(monkeypatch):
    monkeypatch.setattr(axtext, "_focused_element", lambda: "password")
    monkeypatch.setattr(axtext, "_string_attr", lambda _element, attribute:
                        "AXSecureTextField" if attribute == axtext.kAXSubroleAttribute else "AXTextField")
    monkeypatch.setattr(axtext, "AXUIElementCopyAttributeValue",
                        lambda *_args: pytest.fail("Do not read secure AXValue"))
    snapshot = axtext.capture_focused_input()
    assert snapshot.secure is True
    assert snapshot.full_text == ""


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("keycode", [hotkey_main.KEY_R, 36])
def test_shortcut_capture_is_deferred_and_only_allowed_inputs_send(monkeypatch, allowed, keycode):
    calls, pending = [], []
    snapshot = InputSnapshot(identity="box", full_text="raw", target_range=TextRange(0, 3), app_pid=123)

    class DeferredThread:
        def __init__(self, *, target, daemon, args=()):
            pending.append(lambda: target(*args))

        def start(self):
            pass

    def prepare(captured):
        assert captured is snapshot
        calls.append("learn")
        return {"status": "learn_ready", "event": "learn-event"}

    def commit(event):
        assert event == "learn-event"
        calls.append("commit")
        return {"status": "learned"}

    controller = SimpleNamespace(
        adapter=SimpleNamespace(capture=lambda: calls.append("capture") or snapshot),
        shortcut_allowed=lambda _snapshot: allowed,
        prepare_learn=prepare,
        commit_learn=commit,
    )
    host = SimpleNamespace(
        _shutting_down=False, _shortcut_lock=threading.Lock(), controller=controller,
        _action_generation=0,
        overlay=SimpleNamespace(show=lambda *_args, **_kwargs: None),
        _set_state=lambda *_args: None,
        on_write=lambda **_kwargs: calls.append("write"),
    )
    monkeypatch.setattr(hotkey_main.threading, "Thread", DeferredThread)
    monkeypatch.setattr(hotkey_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(axtext, "frontmost_pid", lambda: 123)
    monkeypatch.setattr(axtext, "replay_shortcut", lambda *_args: calls.append("replay"))
    App.on_shortcut(host, keycode, "original-event")
    assert calls == []
    pending.pop(0)()
    if allowed and keycode == hotkey_main.KEY_R:
        assert calls == ["capture", "write"]
    elif allowed:
        assert calls == ["capture", "learn"]
        assert not host._shortcut_lock.locked()
        pending.pop(0)()
        assert calls == ["capture", "learn", "commit"]
    else:
        assert calls == ["capture", "replay"]
