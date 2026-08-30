"""MemTranslator macOS menu-bar client.

Fn+R is Write: compile applicable remembered preferences into the focused
composer without learning.  Fn+Enter is Learn: forward one ordinary Enter and
explicitly queue user evidence, plus correction feedback for a matching
pending Write.  Focus changes never learn and do not require content polling.
"""
from __future__ import annotations

import json
import signal
import threading
import time
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
    CGEventCreateCopy,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskSecondaryFn,
    kCGEventFlagMaskShift,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventLeftMouseDown,
    kCGEventOtherMouseDown,
    kCGEventRightMouseDown,
    kCGEventSourceUserData,
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGKeyboardEventAutorepeat,
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
HOTKEY_SETTLE_SECONDS = 0.04
READY_LABEL = "Ready · Fn+R Write / Fn+Enter Learn"
SHORTCUT_MODIFIERS = kCGEventFlagMaskSecondaryFn
MODIFIER_MASK = (SHORTCUT_MODIFIERS | kCGEventFlagMaskCommand
                 | kCGEventFlagMaskShift | kCGEventFlagMaskAlternate
                 | kCGEventFlagMaskControl)


def write_flow(read=None, write=None, post=None) -> str:
    """Small platform-neutral Write seam retained for integration tests."""
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
            on_progress=self._on_progress)
        self._pointer_timer = None
        self._state_timer = None
        self._shutting_down = False
        self._shortcut_lock = threading.Lock()
        self._action_generation = 0
        self.status_item = NSStatusBar.systemStatusBar() \
            .statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⇄")

        menu = NSMenu.alloc().init()
        title = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "MemTranslator", None, "")
        title.setEnabled_(False)
        menu.addItem_(title)
        self.state_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            READY_LABEL, None, "")
        self.state_item.setEnabled_(False)
        menu.addItem_(self.state_item)
        menu.addItem_(NSMenuItem.separatorItem())
        write = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Write Focused Input", "writeFocusedInput:", "")
        write.setTarget_(self)
        menu.addItem_(write)
        menu.addItem_(NSMenuItem.separatorItem())
        control = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Control Center", "openControlCenter:", "")
        control.setTarget_(self)
        menu.addItem_(control)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItemWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        self.status_item.setMenu_(menu)
        return self

    def writeFocusedInput_(self, _sender):
        print("menu Write requested", flush=True)
        self.on_write()

    def openControlCenter_(self, _sender):
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.URLWithString_(DAEMON + "/"))

    def _set_state(self, glyph: str, text: str, reset_after: float = 0) -> None:
        if self._shutting_down:
            return
        def update():
            self.status_item.button().setTitle_(glyph)
            self.state_item.setTitle_(text)
        AppHelper.callAfter(update)
        if self._state_timer is not None:
            self._state_timer.cancel()
            self._state_timer = None
        if reset_after:
            def reset_state():
                self._state_timer = None
                self._set_state("⇄", READY_LABEL)

            self._state_timer = threading.Timer(reset_after, reset_state)
            self._state_timer.daemon = True
            self._state_timer.start()

    def shutdown(self) -> None:
        """Stop every timer before Cocoa tears down its run loop."""
        self._shutting_down = True
        for timer_name in ("_state_timer", "_pointer_timer"):
            timer = getattr(self, timer_name)
            if timer is not None:
                timer.cancel()
                setattr(self, timer_name, None)
        self.controller.pending_writes.cancel()
        self.overlay.shutdown()
        NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)

    def _on_progress(self, state: str, snapshot) -> None:
        bounds = snapshot.screen_bounds if snapshot is not None else None
        if state in {"translating", "writing"}:
            self.overlay.move(bounds)

    def on_plain_enter(self) -> None:
        """Dismiss a matching pending Write; ordinary Enter never learns."""
        if not self.controller.has_pending_write:
            return
        snapshot = self.controller.adapter.capture_once()
        if snapshot is not None:
            self.controller.dismiss(snapshot)

    def on_pointer_down(self) -> None:
        """Dismiss a matching Write if click-to-send clears its composer.

        A click inside the same composer or another field does not learn and
        does not end the session.  This is one event-driven check, not polling.
        """
        if not self.controller.has_pending_write:
            return
        before_click = self.controller.adapter.capture_once()
        if not self.controller.matches_pending(before_click):
            return
        if self._pointer_timer is not None:
            self._pointer_timer.cancel()

        def observe_after_click():
            self._pointer_timer = None
            self.controller.dismiss_if_empty(
                self.controller.adapter.capture_known(before_click))

        self._pointer_timer = threading.Timer(
            POINTER_SETTLE_SECONDS, observe_after_click)
        self._pointer_timer.daemon = True
        self._pointer_timer.start()

    def on_shortcut(self, keycode: int, original_event) -> None:
        pid = axtext.frontmost_pid()
        if not self._shortcut_lock.acquire(blocking=False):
            self.overlay.show("正在处理上一条操作，请稍候", auto_hide=1.8)
            return
        self._action_generation += 1
        generation = self._action_generation

        def commit(event):
            result = self.controller.commit_learn(event)
            if (self._shutting_down
                    or (generation != self._action_generation
                        and result["status"] == "learned")):
                return
            if result["status"] == "learned":
                feedback = result.get("feedback", {})
                if feedback.get("status") == "feedback_failed":
                    self._set_state("!", "Learn saved; correction unconfirmed", 3)
                    self.overlay.show("Learn 已提交；纠正反馈未确认", auto_hide=2.4)
                else:
                    self._set_state("✓", "Learn committed", 2.2)
                    self.overlay.show("✓ Learn 已提交，Enter 已转发", auto_hide=1.8)
            else:
                self._set_state("!", "Enter forwarded; Learn unconfirmed", 3)
                self.overlay.show("Enter 已转发；Learn 未确认", auto_hide=3)

        def run():
            try:
                # Let the event tap return before asking Electron for AXValue.
                time.sleep(HOTKEY_SETTLE_SECONDS)
                if self._shutting_down or not pid or axtext.frontmost_pid() != pid:
                    return
                captured = self.controller.adapter.capture()
                if self._shutting_down or axtext.frontmost_pid() != pid:
                    return
                if not self.controller.shortcut_allowed(captured):
                    axtext.replay_shortcut(original_event, pid)
                    if keycode in ENTER_KEYS:
                        self.overlay.show("未执行 Learn：来源或输入框不受支持", auto_hide=2.2)
                    return
                if keycode == KEY_R:
                    self.on_write(snapshot=captured, _synchronous=True)
                    return
                result = self.controller.prepare_learn(captured)
                if result["status"] == "learn_ready":
                    self._set_state("…", "Enter forwarded; committing Learn…")
                    # A slow/offline daemon must not block the next gesture.
                    threading.Thread(target=commit, args=(result["event"],),
                                     daemon=True).start()
                else:
                    message = {
                        "empty": "输入为空，未执行 Learn",
                        "unsupported": "来源或输入框不受支持，未执行 Learn",
                        "send_failed": "焦点或内容已变化，未执行 Learn",
                        "sent_unlearned": "Enter 已转发；Pending Write 已变化，Learn 未提交",
                        "unverified_origin": "无法确认 Write 前原文，未执行 Learn；请使用普通 Enter",
                    }.get(result["status"], "Learn 未完成")
                    self._set_state("!", message, 3)
                    self.overlay.show(message, auto_hide=3)
            except Exception:
                self._set_state("!", "Shortcut failed", 3)
                self.overlay.show("快捷键操作未完成", auto_hide=3)
            finally:
                self._shortcut_lock.release()

        threading.Thread(target=run, daemon=True).start()

    def on_write(self, snapshot=None, _synchronous: bool = False) -> None:
        print("Write requested: fn+r / menu", flush=True)
        if self._pointer_timer is not None:
            self._pointer_timer.cancel()
            self._pointer_timer = None
        self._set_state("…", "Compiling requirements…")

        def run():
            # The event-tap callback must return before querying Accessibility.
            # Otherwise Electron can expose the focused composer with the value
            # from just before the hotkey's key-down/modifier sequence settled.
            if snapshot is None:
                time.sleep(HOTKEY_SETTLE_SECONDS)
            captured_snapshot = (snapshot if snapshot is not None
                                 else self.controller.adapter.capture())
            bounds = (captured_snapshot.screen_bounds
                      if captured_snapshot is not None else None)
            self.overlay.start(bounds)
            result = self.controller.write(snapshot=captured_snapshot)
            status = result["status"]
            detail = ""
            if status == "write_failed" and result.get("write") is not None:
                write = result["write"]
                detail = f" strategy={write.strategy} reason={write.reason}"
            print(f"Write result: {status}{detail}", flush=True)
            if status == "written":
                write = result["write"]
                result_snapshot = result["snapshot"]
                self._set_state("●", f"Write ready to Learn · "
                                      f"{result_snapshot.app_name} · "
                                      f"{write.strategy}")
                self.overlay.complete(result_snapshot.screen_bounds)
            elif status == "write_noop":
                result_snapshot = result["snapshot"]
                self._set_state("●", f"Write ready to Learn · "
                                      f"{result_snapshot.app_name} · no changes")
                self.overlay.show("无需调整", result_snapshot.screen_bounds,
                                  auto_hide=1.2)
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
        if _synchronous:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()


def make_tap_callback(app):
    consumed: set[int] = set()

    def tap_callback(_proxy, event_type, event, _refcon):
        if (CGEventGetIntegerValueField(event, kCGEventSourceUserData)
                == axtext.SYNTHETIC_EVENT_TAG):
            return event
        if event_type in POINTER_DOWN_EVENTS:
            app.on_pointer_down()
            return event
        if event_type not in {kCGEventKeyDown, kCGEventKeyUp}:
            return event
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if event_type == kCGEventKeyUp:
            if keycode in consumed:
                consumed.remove(keycode)
                return None
            return event
        if keycode in consumed:
            return None
        flags = CGEventGetFlags(event) & MODIFIER_MASK
        repeat = CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat)
        if keycode in (KEY_R, *ENTER_KEYS) and flags == SHORTCUT_MODIFIERS:
            consumed.add(keycode)
            if not repeat:
                app.on_shortcut(keycode, CGEventCreateCopy(event))
            return None
        # Shift+Enter/IME modifiers are not message boundaries. Learn's
        # synthetic Enter is tagged and already handled before this branch.
        if keycode in ENTER_KEYS and flags == 0 and not repeat:
            app.on_plain_enter()
        return event

    return tap_callback


def main():
    if not axtext.ensure_trusted():
        print("Grant Accessibility permission, then relaunch.")
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app = App.alloc().init()

    tap_callback = make_tap_callback(app)
    event_mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
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
    previous_sigint = signal.getsignal(signal.SIGINT)
    try:
        # PyObjC does not install its SIGINT-to-run-loop bridge by default.
        # Without this, Ctrl+C stops the Uvicorn child but leaves the Cocoa
        # event loop and global keyboard tap alive in the CLI parent process.
        AppHelper.runEventLoop(installInterrupt=True)
    finally:
        # AppHelper's Mach interrupt bridge is process-global and does not
        # restore Python's SIGINT handler when the run loop ends.
        signal.signal(signal.SIGINT, previous_sigint)
        CGEventTapEnable(tap, False)
        app.shutdown()


if __name__ == "__main__":
    main()
