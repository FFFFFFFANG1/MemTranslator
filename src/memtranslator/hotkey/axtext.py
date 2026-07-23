"""Read and write the focused text field via the Accessibility API.

Primary path: AXValue get/set on the system-wide focused element.
Fallback (Chromium/Electron fields that reject AXValue set): put the text
on the pasteboard, select-all, and synthesize Cmd+V — the Typeless-style
bottom line. Requires the Accessibility permission (System Settings →
Privacy & Security → Accessibility)."""
import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from ApplicationServices import (
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateSystemWide,
    AXUIElementSetAttributeValue,
    kAXFocusedUIElementAttribute,
    kAXTrustedCheckOptionPrompt,
    kAXValueAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

KEY_A, KEY_V = 0, 9


def ensure_trusted() -> bool:
    return AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})


def _focused_element():
    err, el = AXUIElementCopyAttributeValue(
        AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None)
    return el if err == 0 else None


def read_focused_text() -> str | None:
    el = _focused_element()
    if el is None:
        return None
    err, value = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
    if err != 0 or not isinstance(value, str):
        return None
    return value


def _tap_key(keycode: int, cmd: bool = False) -> None:
    for down in (True, False):
        ev = CGEventCreateKeyboardEvent(None, keycode, down)
        if cmd:
            CGEventSetFlags(ev, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, ev)


def write_focused_text(text: str) -> bool:
    el = _focused_element()
    if el is not None:
        err = AXUIElementSetAttributeValue(el, kAXValueAttribute, text)
        if err == 0 and read_focused_text() == text:
            return True
    # fallback: pasteboard + select-all + paste
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    _tap_key(KEY_A, cmd=True)
    time.sleep(0.05)
    _tap_key(KEY_V, cmd=True)
    return True
