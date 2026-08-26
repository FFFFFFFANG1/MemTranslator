"""Transactional read/write access to the focused macOS text input.

The important invariant is not a particular Accessibility call; it is that a
write is applied only to the element and text version we captured before the
LLM request.  Native controls use a guarded AXValue patch.  Web/Electron
editors select only the captured range and paste, with the clipboard restored.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import replace
from urllib.parse import urlsplit

from AppKit import (NSPasteboard, NSPasteboardItem, NSPasteboardTypeString,
                    NSWorkspace)
from ApplicationServices import (
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    AXUIElementIsAttributeSettable,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    AXValueGetValue,
    kAXDescriptionAttribute,
    kAXFocusedUIElementAttribute,
    kAXFocusedWindowAttribute,
    kAXIdentifierAttribute,
    kAXMainWindowAttribute,
    kAXPositionAttribute,
    kAXRoleAttribute,
    kAXSelectedTextRangeAttribute,
    kAXSizeAttribute,
    kAXSubroleAttribute,
    kAXTitleAttribute,
    kAXTrustedCheckOptionPrompt,
    kAXValueAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXValueCFRangeType,
    kAXWindowAttribute,
)
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

from memtranslator.hotkey.models import InputSnapshot, TextRange, WriteResult
from memtranslator.hotkey.profiles import resolve_profile
from memtranslator.source_policy import AI_APP_BUNDLES, is_ai_app

KEY_A, KEY_V = 0, 9

_CHROMIUM_BUNDLES = {
    "com.google.Chrome",
    "com.google.Chrome.beta",
    "com.google.Chrome.canary",
    "com.microsoft.edgemac",
    "company.thebrowser.Browser",
    "com.brave.Browser",
} | set(AI_APP_BUNDLES)
_WEB_AX_ENABLED_PIDS: set[int] = set()


def ensure_trusted() -> bool:
    return AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})


def _copy(element, attribute):
    err, value = AXUIElementCopyAttributeValue(element, attribute, None)
    return value if err == 0 else None


def _enable_frontmost_web_accessibility() -> bool:
    """Ask Chromium to expose renderer form controls through macOS AX.

    Chromium's native chrome (including the address bar) is visible without
    renderer accessibility.  Web-page inputs are not guaranteed to exist in
    the native tree until an assistive client sets EnhancedUserInterface on
    the browser application/window.  The string attributes are Chromium's
    long-standing macOS activation contract; failures remain non-fatal.
    """
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return False
    bundle_id = app.bundleIdentifier() or ""
    app_name = app.localizedName() or ""
    if (bundle_id not in _CHROMIUM_BUNDLES
            and not is_ai_app(app_bundle_id=bundle_id, app_name=app_name)):
        return False
    pid = int(app.processIdentifier())
    if pid in _WEB_AX_ENABLED_PIDS:
        return False
    application = AXUIElementCreateApplication(pid)
    targets = [application]
    for attribute in (kAXFocusedWindowAttribute, kAXMainWindowAttribute):
        target = _copy(application, attribute)
        if target is not None and target not in targets:
            targets.append(target)
    enabled = False
    for target in targets:
        for attribute in ("AXEnhancedUserInterface",
                          "AXManualAccessibility"):
            try:
                enabled = (AXUIElementSetAttributeValue(
                    target, attribute, True) == 0) or enabled
            except Exception:
                pass
    if enabled:
        _WEB_AX_ENABLED_PIDS.add(pid)
        # Renderer AX data is bridged asynchronously into the browser process.
        time.sleep(0.06)
    return enabled


def _focused_element():
    _enable_frontmost_web_accessibility()
    err, element = AXUIElementCopyAttributeValue(
        AXUIElementCreateSystemWide(), kAXFocusedUIElementAttribute, None)
    if err != 0 or element is None:
        _debug_capture_failure("focused_element_unavailable", error=err)
    return element if err == 0 else None


def _string_attr(element, attribute) -> str:
    value = _copy(element, attribute)
    return value if isinstance(value, str) else ""


def _is_settable(element, attribute) -> bool:
    try:
        err, settable = AXUIElementIsAttributeSettable(
            element, attribute, None)
        return err == 0 and bool(settable)
    except Exception:
        return False


def _decode_range(value, text_length: int) -> TextRange:
    if value is None:
        return TextRange(0, text_length)
    try:
        decoded = AXValueGetValue(value, kAXValueCFRangeType, None)
        if isinstance(decoded, tuple) and len(decoded) == 2 \
                and isinstance(decoded[0], bool):
            decoded = decoded[1]
        if isinstance(decoded, tuple) and len(decoded) == 2:
            location, length = int(decoded[0]), int(decoded[1])
        elif hasattr(decoded, "location") and hasattr(decoded, "length"):
            location, length = int(decoded.location), int(decoded.length)
        else:
            return TextRange(0, text_length)
        if location < 0 or length < 0 or location + length > text_length:
            return TextRange(0, text_length)
        # A caret has no useful target span, so default to the full composer.
        # The caller currently promotes real selections to full-composer too.
        return TextRange(location, length) if length else TextRange(0, text_length)
    except Exception:
        return TextRange(0, text_length)


def _decode_pair(value, value_type: int) -> tuple[float, float] | None:
    if value is None:
        return None
    try:
        decoded = AXValueGetValue(value, value_type, None)
        if (isinstance(decoded, tuple) and len(decoded) == 2
                and isinstance(decoded[0], bool)):
            decoded = decoded[1]
        if isinstance(decoded, tuple) and len(decoded) == 2:
            return float(decoded[0]), float(decoded[1])
        if hasattr(decoded, "x") and hasattr(decoded, "y"):
            return float(decoded.x), float(decoded.y)
        if hasattr(decoded, "width") and hasattr(decoded, "height"):
            return float(decoded.width), float(decoded.height)
    except Exception:
        pass
    return None


def _frontmost_app() -> tuple[str, str]:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return "", ""
    return app.localizedName() or "", app.bundleIdentifier() or ""


def _url_string(value) -> str:
    if isinstance(value, str):
        return value
    try:
        absolute = value.absoluteString()
        return absolute if isinstance(absolute, str) else ""
    except Exception:
        return ""


def _domain_from_url(value) -> str:
    raw = _url_string(value).strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    domain = parsed.hostname.casefold().rstrip(".")
    return domain[4:] if domain.startswith("www.") else domain


def _focused_web_domain(element) -> str:
    """Read only the page hostname, never retain its path or query string."""
    current = element
    visited = set()
    for _ in range(16):
        if current is None:
            break
        try:
            marker = hash(current)
        except Exception:
            marker = id(current)
        if marker in visited:
            break
        visited.add(marker)
        for attribute in ("AXURL", "AXDocument"):
            domain = _domain_from_url(_copy(current, attribute))
            if domain:
                return domain
        current = _copy(current, "AXParent")
    window = _copy(element, kAXWindowAttribute)
    for target in (window,):
        for attribute in ("AXURL", "AXDocument"):
            domain = _domain_from_url(_copy(target, attribute)) if target else ""
            if domain:
                return domain
    return ""


def _debug_capture_failure(reason: str, *, element=None, error=None,
                           value=None, value_error=None) -> None:
    """Emit privacy-safe AX metadata for opt-in composer diagnosis."""
    if os.environ.get("MT_AX_DEBUG", "").strip().lower() not in {
            "1", "true", "yes", "on"}:
        return
    app_name, bundle_id = _frontmost_app()
    report = {
        "reason": reason,
        "app_name": app_name,
        "app_bundle_id": bundle_id,
        "focused_error": error,
        "value_error": value_error,
        "value_type": type(value).__name__ if value is not None else None,
        "value_length": len(value) if isinstance(value, str) else None,
    }
    if element is not None:
        report.update({
            "role": _string_attr(element, kAXRoleAttribute),
            "subrole": _string_attr(element, kAXSubroleAttribute),
            "identifier_present": bool(
                _string_attr(element, kAXIdentifierAttribute)),
            "description_present": bool(
                _string_attr(element, kAXDescriptionAttribute)),
            "value_settable": _is_settable(element, kAXValueAttribute),
            "selection_settable": _is_settable(
                element, kAXSelectedTextRangeAttribute),
        })
    print("[MT_AX_DEBUG] " + json.dumps(
        report, ensure_ascii=False, sort_keys=True), flush=True)


def _identity(element, *, app_bundle_id: str, role: str, subrole: str,
              identifier: str, description: str, window_title: str) -> str:
    try:
        element_key = str(hash(element))
    except Exception:
        element_key = repr(element)
    raw = "\x1f".join((app_bundle_id, window_title, role, subrole, identifier,
                       description, element_key))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def capture_focused_input() -> InputSnapshot | None:
    element = _focused_element()
    if element is None:
        return None
    value_error, value = AXUIElementCopyAttributeValue(
        element, kAXValueAttribute, None)
    if not isinstance(value, str):
        _debug_capture_failure(
            "focused_value_not_text", element=element, value=value,
            value_error=value_error)
        return None
    if not value.strip():
        _debug_capture_failure(
            "focused_value_empty", element=element, value=value,
            value_error=value_error)
    role = _string_attr(element, kAXRoleAttribute)
    subrole = _string_attr(element, kAXSubroleAttribute)
    identifier = _string_attr(element, kAXIdentifierAttribute)
    description = _string_attr(element, kAXDescriptionAttribute)
    window = _copy(element, kAXWindowAttribute)
    window_title = _string_attr(window, kAXTitleAttribute) if window else ""
    app_name, bundle_id = _frontmost_app()
    web_domain = _focused_web_domain(element)
    position = _decode_pair(_copy(element, kAXPositionAttribute),
                            kAXValueCGPointType)
    size = _decode_pair(_copy(element, kAXSizeAttribute),
                        kAXValueCGSizeType)
    screen_bounds = ((*position, *size)
                     if position is not None and size is not None else None)
    selected = _decode_range(
        _copy(element, kAXSelectedTextRangeAttribute), len(value))
    # The product action is "polish this composer".  A future explicit
    # selection command can retain a partial range, but the global hotkey must
    # track one complete request so the final submit can join unambiguously.
    if selected != TextRange(0, len(value)):
        selected = TextRange(0, len(value))
    role_text = f"{role} {subrole}".casefold()
    secure = "secure" in role_text or "password" in role_text
    editable = bool(value is not None and not secure)
    snapshot = InputSnapshot(
        identity=_identity(element, app_bundle_id=bundle_id, role=role,
                           subrole=subrole, identifier=identifier,
                           description=description, window_title=window_title),
        full_text=value,
        target_range=selected,
        app_name=app_name,
        app_bundle_id=bundle_id,
        web_domain=web_domain,
        window_title=window_title,
        role=role,
        subrole=subrole,
        identifier=identifier or description,
        editable=editable,
        secure=secure,
        value_settable=_is_settable(element, kAXValueAttribute),
        selection_settable=_is_settable(
            element, kAXSelectedTextRangeAttribute),
        screen_bounds=screen_bounds,
    )
    # Terminals expose scrollback as one AXTextArea, not the shell's editable
    # line buffer.  Reject disabled profiles before the controller calls the
    # daemon, so terminal history is neither uploaded nor pasted back.
    if not resolve_profile(snapshot).enabled:
        return replace(snapshot, editable=False)
    return snapshot


def _tap_key(keycode: int, cmd: bool = False) -> None:
    for down in (True, False):
        event = CGEventCreateKeyboardEvent(None, keycode, down)
        if cmd:
            CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)


def _set_selection(element, selection: TextRange) -> bool:
    try:
        encoded = AXValueCreate(kAXValueCFRangeType,
                                (selection.location, selection.length))
        return encoded is not None and AXUIElementSetAttributeValue(
            element, kAXSelectedTextRangeAttribute, encoded) == 0
    except Exception:
        return False


def _verify(expected: str, identity: str) -> bool:
    current = capture_focused_input()
    return bool(current and current.identity == identity
                and current.full_text == expected)


def _write_value(element, snapshot: InputSnapshot, polished: str,
                 expected: str) -> WriteResult:
    err = AXUIElementSetAttributeValue(element, kAXValueAttribute, expected)
    if err != 0 or not _verify(expected, snapshot.identity):
        return WriteResult(False, "value", reason=f"ax_error:{err}")
    caret = TextRange(snapshot.target_range.location + len(polished), 0)
    _set_selection(element, caret)
    return WriteResult(True, "value", expected_full_text=expected)


def _save_pasteboard(pasteboard) -> list[dict]:
    saved = []
    for item in pasteboard.pasteboardItems() or []:
        payload = {}
        for item_type in item.types() or []:
            data = item.dataForType_(item_type)
            if data is not None:
                payload[item_type] = data
        saved.append(payload)
    return saved


def _restore_pasteboard(pasteboard, saved: list[dict]) -> None:
    pasteboard.clearContents()
    items = []
    for payload in saved:
        item = NSPasteboardItem.alloc().init()
        for item_type, data in payload.items():
            item.setData_forType_(data, item_type)
        items.append(item)
    if items:
        pasteboard.writeObjects_(items)


def _write_paste(element, snapshot: InputSnapshot, polished: str,
                 expected: str) -> WriteResult:
    if not _set_selection(element, snapshot.target_range):
        # A full-composer target can still safely use select-all because the
        # stale-version and identity checks already passed immediately before.
        if snapshot.target_range != TextRange(0, len(snapshot.full_text)):
            return WriteResult(False, "paste", reason="range_unsettable")
        _tap_key(KEY_A, cmd=True)
    pasteboard = NSPasteboard.generalPasteboard()
    saved = _save_pasteboard(pasteboard)
    try:
        pasteboard.clearContents()
        pasteboard.setString_forType_(polished, NSPasteboardTypeString)
        _tap_key(KEY_V, cmd=True)
        time.sleep(0.08)
        if not _verify(expected, snapshot.identity):
            return WriteResult(False, "paste", reason="verification_failed")
        return WriteResult(True, "paste", expected_full_text=expected)
    finally:
        _restore_pasteboard(pasteboard, saved)


def write_snapshot(snapshot: InputSnapshot, polished: str) -> WriteResult:
    if snapshot.secure or not snapshot.editable:
        return WriteResult(False, "none", reason="protected_input")
    current = capture_focused_input()
    if current is None or current.identity != snapshot.identity:
        return WriteResult(False, "none", reason="focus_changed")
    if current.full_text != snapshot.full_text:
        return WriteResult(False, "none", reason="stale_snapshot")
    expected = snapshot.prefix + polished + snapshot.suffix
    profile = resolve_profile(snapshot)
    if not profile.enabled:
        return WriteResult(False, "none", reason="profile_disabled")
    last = WriteResult(False, "none", reason="no_strategy")
    for strategy in profile.write_order:
        element = _focused_element()
        if element is None:
            return WriteResult(False, strategy, reason="focus_lost")
        if strategy == "value":
            last = _write_value(element, snapshot, polished, expected)
        elif strategy == "paste":
            last = _write_paste(element, snapshot, polished, expected)
        if last.ok:
            return last
    return last


class MacOSInputAdapter:
    capture = staticmethod(capture_focused_input)
    write = staticmethod(write_snapshot)


# Compatibility surface for the original spike and third-party imports.
def read_focused_text() -> str | None:
    snapshot = capture_focused_input()
    return snapshot.full_text if snapshot is not None else None


def write_focused_text(text: str) -> bool:
    snapshot = capture_focused_input()
    return bool(snapshot and write_snapshot(snapshot, text).ok)
