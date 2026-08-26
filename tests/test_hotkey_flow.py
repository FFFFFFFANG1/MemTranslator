import importlib.util

import pytest

if importlib.util.find_spec("Quartz") is None:
    pytest.skip("pyobjc not installed (hotkey group)", allow_module_level=True)

from memtranslator.hotkey import axtext
from memtranslator.hotkey.__main__ import polish_flow


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
