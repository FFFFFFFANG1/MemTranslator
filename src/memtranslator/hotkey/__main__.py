"""MemTranslator macOS menu-bar client.

⌥⌘R captures the focused composer as a guarded Accessibility transaction,
asks the local daemon to compile applicable requirements into it, writes the
result back, then watches the same composer briefly for human edits.
"""
from __future__ import annotations

import json
import threading
import urllib.request

from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                    NSMenu, NSMenuItem, NSStatusBar,
                    NSVariableStatusItemLength, NSWorkspace)
from Foundation import NSObject, NSURL
from PyObjCTools import AppHelper
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventKeyDown,
    kCGEventLeftMouseDown,
    kCGEventOtherMouseDown,
    kCGEventRightMouseDown,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)
from objc import super

from memtranslator.hotkey import axtext
from memtranslator.hotkey.client import DaemonClient
from memtranslator.hotkey.controller import DesktopController
from memtranslator.hotkey.overlay import StatusOverlay
from memtranslator.config import DAEMON_URL

DAEMON = DAEMON_URL
KEY_R = 15
ENTER_KEYS = {36, 76}
POINTER_DOWN_EVENTS = {
    kCGEventLeftMouseDown,
    kCGEventRightMouseDown,
    kCGEventOtherMouseDown,
}
POINTER_SETTLE_SECONDS = 0.08


def polish_flow(read=None, write=None, post=None) -> str:
    """Compatibility wrapper retained for integrations around the v0 spike."""
    if read is None:
        read = axtext.read_focused_text
    if write is None:
        write = axtext.write_focused_text
    if post is None:
        def post(text):
            request = urllib.request.Request(
                f"{DAEMON}/api/translate",
                data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
    raw = read()
    if not raw or not raw.strip():
        return "empty"
    try:
        out = post(raw)
    except Exception:
        return "daemon_down"
    if out.get("decision") != "apply":
        return "noop"
    return "applied" if write(out["polished"]) else "write_failed"


class App(NSObject):
    def init(self):
        self = super().init()
        if self is None:
            return None
        self.overlay = StatusOverlay()
        self.controller = DesktopController(
            axtext.MacOSInputAdapter(), DaemonClient(DAEMON),
            on_feedback=self._on_feedback, on_progress=self._on_progress)
        self._poll_timer = None
        self._pointer_timer = None
        self.status_item = NSStatusBar.systemStatusBar() \
            .statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⇄")

        menu = NSMenu.alloc().init()
        title = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "MemTranslator", None, "")
        title.setEnabled_(False)
        menu.addItem_(title)
        self.state_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Ready · ⌥⌘R", None, "")
        self.state_item.setEnabled_(False)
        menu.addItem_(self.state_item)
        menu.addItem_(NSMenuItem.separatorItem())
        polish = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Polish Focused Input", "polishFocusedInput:", "")
        polish.setTarget_(self)
        menu.addItem_(polish)
        menu.addItem_(NSMenuItem.separatorItem())
        control = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Control Center", "openControlCenter:", "")
        control.setTarget_(self)
        menu.addItem_(control)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItemWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        self.status_item.setMenu_(menu)
        return self

    def polishFocusedInput_(self, _sender):
        print("menu polish requested", flush=True)
        self.on_hotkey()

    def openControlCenter_(self, _sender):
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.URLWithString_(DAEMON + "/"))

    def _set_state(self, glyph: str, text: str, reset_after: float = 0) -> None:
        def update():
            self.status_item.button().setTitle_(glyph)
            self.state_item.setTitle_(text)
        AppHelper.callAfter(update)
        if reset_after:
            threading.Timer(reset_after, lambda: self._set_state(
                "⇄", "Ready · ⌥⌘R")).start()

    def _on_feedback(self, result: dict) -> None:
        if result["status"] == "feedback_failed":
            self._set_state("!", "Feedback queued failed", 2.2)
            self.overlay.show("未能保存修改", auto_hide=1.8)
            return
        classification = result.get("response", {}).get(
            "classification", "")
        if classification == "edited_after_polish":
            self._set_state("✓", "Edit feedback saved", 2.2)
            self.overlay.show("✓  已记录修改", auto_hide=1.8)

    def _on_progress(self, state: str, snapshot) -> None:
        bounds = snapshot.screen_bounds if snapshot is not None else None
        if state in {"translating", "writing"}:
            self.overlay.move(bounds)

    def _schedule_poll(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.cancel()
        if not self.controller.tracker.active:
            self._poll_timer = None
            return
        self._poll_timer = threading.Timer(0.18, self._poll)
        self._poll_timer.daemon = True
        self._poll_timer.start()

    def _poll(self) -> None:
        self.controller.observe()
        self._schedule_poll()

    def on_enter(self) -> None:
        if not self.controller.tracker.active:
            return
        threading.Thread(target=lambda: self.controller.observe(key="Enter"),
                         daemon=True).start()

    def on_pointer_down(self) -> None:
        """Re-check after a click has had time to clear or move the input.

        A click inside the same composer merely refreshes its snapshot. A
        send-button click, tab switch, or click into another field finishes
        through the tracker's existing cleared/focus-changed rules.
        """
        if not self.controller.tracker.active:
            return
        if self._pointer_timer is not None:
            self._pointer_timer.cancel()

        def observe_after_click():
            self._pointer_timer = None
            self.controller.observe()

        self._pointer_timer = threading.Timer(
            POINTER_SETTLE_SECONDS, observe_after_click)
        self._pointer_timer.daemon = True
        self._pointer_timer.start()

    def on_hotkey(self) -> None:
        print("hotkey accepted: option+command+r", flush=True)
        if self._pointer_timer is not None:
            self._pointer_timer.cancel()
            self._pointer_timer = None
        if self.controller.tracker.active:
            self.controller.tracker.cancel()
        self._set_state("…", "Compiling requirements…")
        captured_snapshot = self.controller.adapter.capture()
        bounds = (captured_snapshot.screen_bounds
                  if captured_snapshot is not None else None)
        self.overlay.start(bounds)

        def run():
            result = self.controller.polish(snapshot=captured_snapshot)
            status = result["status"]
            print(f"polish result: {status}", flush=True)
            if status == "tracking":
                write = result["write"]
                result_snapshot = result["snapshot"]
                self._set_state("●", f"Tracking · {result_snapshot.app_name} · "
                                      f"{write.strategy}")
                self.overlay.complete(result_snapshot.screen_bounds)
                self._schedule_poll()
            elif status == "noop_tracking":
                result_snapshot = result["snapshot"]
                self._set_state("●", f"Tracking · {result_snapshot.app_name} · "
                                      "no changes")
                self.overlay.show("无需调整", result_snapshot.screen_bounds,
                                  auto_hide=1.2)
                self._schedule_poll()
            else:
                glyph, label = {
                    "empty": ("·", "Focused composer is empty"),
                    "unsupported": ("×", "Protected or unsupported input"),
                    "daemon_down": ("!", "Daemon unavailable"),
                    "write_failed": ("!", "Write verification failed"),
                }.get(status, ("!", status))
                self._set_state(glyph, label, 2.2)
                overlay_label = {
                    "empty": "未找到可编辑文字",
                    "unsupported": "此输入框暂不支持",
                    "daemon_down": "本地服务未连接",
                    "write_failed": "回填失败",
                }.get(status, "处理失败")
                self.overlay.show(overlay_label, bounds, auto_hide=1.6)
        threading.Thread(target=run, daemon=True).start()


def main():
    if not axtext.ensure_trusted():
        print("Grant Accessibility permission, then relaunch.")
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app = App.alloc().init()

    def tap_callback(_proxy, event_type, event, _refcon):
        if event_type in POINTER_DOWN_EVENTS:
            app.on_pointer_down()
            return event
        if event_type != kCGEventKeyDown:
            return event
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        if keycode == KEY_R:
            print(
                "R key observed: "
                f"command={bool(flags & kCGEventFlagMaskCommand)} "
                f"option={bool(flags & kCGEventFlagMaskAlternate)}",
                flush=True,
            )
        if (keycode == KEY_R
                and flags & kCGEventFlagMaskCommand
                and flags & kCGEventFlagMaskAlternate):
            app.on_hotkey()
            return None
        if keycode in ENTER_KEYS:
            app.on_enter()
        return event

    event_mask = CGEventMaskBit(kCGEventKeyDown)
    for pointer_event in POINTER_DOWN_EVENTS:
        event_mask |= CGEventMaskBit(pointer_event)
    tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                           kCGEventTapOptionDefault,
                           event_mask, tap_callback, None)
    if tap is None:
        raise SystemExit("Event tap failed — check Accessibility permission.")
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
