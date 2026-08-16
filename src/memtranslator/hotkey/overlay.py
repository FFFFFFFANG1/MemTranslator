"""Small non-activating status pill anchored to the focused input."""
from __future__ import annotations

import threading

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSFontWeightMedium,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSTextAlignmentCenter,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from PyObjCTools import AppHelper


PANEL_HEIGHT = 36.0
PANEL_GAP = 8.0


def _text_width(text: str) -> float:
    units = sum(1.7 if "\u3400" <= char <= "\u9fff" else 1 for char in text)
    return max(132.0, min(244.0, 34.0 + units * 7.0))


class StatusOverlay:
    def __init__(self):
        self._timer: threading.Timer | None = None
        self._last_bounds: tuple[float, float, float, float] | None = None
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 168, PANEL_HEIGHT),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary)

        self.background = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 168, PANEL_HEIGHT))
        self.background.setWantsLayer_(True)
        layer = self.background.layer()
        layer.setCornerRadius_(12.0)
        layer.setMasksToBounds_(True)
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.92).CGColor())

        self.label = NSTextField.labelWithString_("")
        self.label.setFrame_(NSMakeRect(12, 0, 144, PANEL_HEIGHT))
        self.label.setAlignment_(NSTextAlignmentCenter)
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setFont_(NSFont.systemFontOfSize_weight_(
            12.0, NSFontWeightMedium))
        self.background.addSubview_(self.label)
        self.panel.setContentView_(self.background)

    def show(self, text: str, bounds=None, *, auto_hide: float = 0) -> None:
        AppHelper.callAfter(self._show, text, bounds, auto_hide)

    def _show(self, text: str, bounds, auto_hide: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if bounds is not None:
            self._last_bounds = tuple(float(value) for value in bounds)
        width = _text_width(text)
        self.panel.setFrame_display_(
            NSMakeRect(*self._origin(width), width, PANEL_HEIGHT), True)
        self.background.setFrame_(NSMakeRect(0, 0, width, PANEL_HEIGHT))
        self.label.setFrame_(NSMakeRect(12, 0, width - 24, PANEL_HEIGHT))
        self.label.setStringValue_(text)
        self.panel.orderFrontRegardless()
        if auto_hide:
            self._timer = threading.Timer(auto_hide, self.hide)
            self._timer.daemon = True
            self._timer.start()

    def hide(self) -> None:
        AppHelper.callAfter(self._hide)

    def _hide(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.panel.orderOut_(None)

    def _origin(self, width: float) -> tuple[float, float]:
        screens = list(NSScreen.screens())
        if not screens:
            point = NSEvent.mouseLocation()
            return point.x - width / 2, point.y + PANEL_GAP

        primary_height = screens[0].frame().size.height
        bounds = self._last_bounds
        target = NSScreen.mainScreen() or screens[0]
        if bounds is not None:
            x, y, field_width, field_height = bounds
            for screen in screens:
                frame = screen.frame()
                ax_top = primary_height - (frame.origin.y + frame.size.height)
                if (frame.origin.x <= x <= frame.origin.x + frame.size.width
                        and ax_top <= y <= ax_top + frame.size.height):
                    target = screen
                    break
            frame = target.frame()
            ax_top = primary_height - (frame.origin.y + frame.size.height)
            ax_bottom = ax_top + frame.size.height
            panel_ax_y = y + field_height + PANEL_GAP
            if panel_ax_y + PANEL_HEIGHT > ax_bottom:
                panel_ax_y = max(ax_top, y - PANEL_HEIGHT - PANEL_GAP)
            origin_x = x + field_width - width
            origin_y = primary_height - panel_ax_y - PANEL_HEIGHT
        else:
            point = NSEvent.mouseLocation()
            origin_x = point.x - width / 2
            origin_y = point.y + PANEL_GAP

        visible = target.visibleFrame()
        origin_x = max(visible.origin.x + PANEL_GAP,
                       min(origin_x, visible.origin.x + visible.size.width
                           - width - PANEL_GAP))
        origin_y = max(visible.origin.y + PANEL_GAP,
                       min(origin_y, visible.origin.y + visible.size.height
                           - PANEL_HEIGHT - PANEL_GAP))
        return origin_x, origin_y
