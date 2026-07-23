"""MemTranslator hotkey shell (spike): menu bar item + global ⌥⌘E.

On hotkey: read the focused text field, ask the daemon to polish, write the
result back — editable in place, human in the loop (anchor §2.2). The
daemon records the translate event; the agent-side hook records the final
submit; the join happens server-side."""
import json
import threading
import urllib.request

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)
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
    kCGEventTapOptionDefault,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

from memtranslator.hotkey import axtext

DAEMON = "http://127.0.0.1:8123"
KEY_E = 14  # ANSI 'e'


def polish_flow(read=None, write=None, post=None) -> str:
    """Returns a status string; separated from AX for testability."""
    if read is None:
        read = axtext.read_focused_text
    if write is None:
        write = axtext.write_focused_text
    if post is None:
        def post(text):
            req = urllib.request.Request(
                f"{DAEMON}/api/translate",
                data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
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


class App:
    def __init__(self):
        self.status_item = NSStatusBar.systemStatusBar() \
            .statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⇄")
        menu = NSMenu.alloc().init()
        menu.addItemWithTitle_action_keyEquivalent_(
            "MemTranslator · ⌥⌘E 润色", None, "")
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItemWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        self.status_item.setMenu_(menu)

    def flash(self, text):
        def set_title(t):
            self.status_item.button().setTitle_(t)
        AppHelper.callAfter(set_title, text)
        threading.Timer(1.6, lambda: AppHelper.callAfter(set_title, "⇄")).start()

    def on_hotkey(self):
        def run():
            status = polish_flow()
            self.flash({"applied": "✓", "noop": "·", "empty": "·",
                        "daemon_down": "!", "write_failed": "!"}[status])
        threading.Thread(target=run, daemon=True).start()


def main():
    if not axtext.ensure_trusted():
        print("Grant Accessibility permission, then relaunch.")
    nsapp = NSApplication.sharedApplication()
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app = App()

    def tap_callback(proxy, etype, event, refcon):
        if etype == kCGEventKeyDown:
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            flags = CGEventGetFlags(event)
            if (keycode == KEY_E
                    and flags & kCGEventFlagMaskCommand
                    and flags & kCGEventFlagMaskAlternate):
                app.on_hotkey()
                return None  # swallow the keystroke
        return event

    tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                           kCGEventTapOptionDefault,
                           CGEventMaskBit(kCGEventKeyDown), tap_callback, None)
    if tap is None:
        raise SystemExit("Event tap failed — check Accessibility permission.")
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
