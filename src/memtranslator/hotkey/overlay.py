"""Non-activating macOS feedback drawn beside the focused input.

The primary state is a small code-drawn network. Nodes arrive in a stable,
random-looking order, edges join them as a rewrite progresses, and the complete
graph emits a soft halo after the rewritten text has been written back. Short
text pills remain available for errors and later feedback events.
"""
from __future__ import annotations

import math
import threading
import time

from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSFontWeightMedium,
    NSGradient,
    NSGradientDrawsBeforeStartingLocation,
    NSGraphicsContext,
    NSMakePoint,
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
from Quartz import CGContextClearRect
from objc import super


NETWORK_SIZE = 90.0
MESSAGE_HEIGHT = 36.0
PANEL_GAP = 10.0
FRAME_SECONDS = 0.075
PHASE_SPEED = 0.42 / FRAME_SECONDS
COMPLETE_SECONDS = 0.9
FADE_SECONDS = 0.45


def _text_width(text: str) -> float:
    units = sum(1.7 if "\u3400" <= char <= "\u9fff" else 1 for char in text)
    return max(132.0, min(244.0, 34.0 + units * 7.0))


def _ink(alpha: float = 1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(
        0.08, 0.08, 0.075, alpha)


def _paper(alpha: float = 1.0):
    return NSColor.colorWithCalibratedWhite_alpha_(1.0, alpha)


def _graphite(alpha: float = 1.0):
    return NSColor.colorWithCalibratedWhite_alpha_(0.42, alpha)


class NetworkView(NSView):
    """A tiny code-drawn graph so the overlay needs no bundled image asset."""

    NODES = (
        (45.0, 45.0, 5.2),
        (23.0, 24.0, 3.6),
        (68.0, 22.0, 4.0),
        (72.0, 56.0, 3.4),
        (50.0, 70.0, 3.1),
        (20.0, 64.0, 4.0),
        (17.0, 43.0, 2.9),
    )
    NODE_ORDER = (5, 2, 0, 6, 3, 1, 4)
    EDGES = (
        (0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6),
        (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 1),
    )
    EDGE_ORDER = (5, 1, 4, 0, 2, 3, 8, 11, 6, 9, 7, 10)

    def initWithFrame_(self, frame):
        self = super().initWithFrame_(frame)
        if self is None:
            return None
        self.phase = 0.0
        self.completed = False
        return self

    def setAnimationState_completed_(self, phase, completed):
        self.phase = float(phase)
        self.completed = bool(completed)
        self.setNeedsDisplay_(True)

    def isOpaque(self):
        return False

    @staticmethod
    def _stroke(path, width=2.4, color=None):
        (color or _ink()).setStroke()
        path.setLineWidth_(width)
        path.stroke()

    @staticmethod
    def _node_path(x_pos, y_pos, radius):
        return NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(
            x_pos - radius, y_pos - radius, radius * 2, radius * 2))

    def drawRect_(self, _dirty_rect):
        bounds = self.bounds()
        # The transparent backdrop must not accumulate old nodes or halo frames.
        CGContextClearRect(NSGraphicsContext.currentContext().CGContext(), bounds)
        center = NSMakePoint(bounds.size.width / 2.0,
                             bounds.size.height / 2.0)
        # Keep the graph readable over arbitrary editors without drawing a
        # visible card: white at the core, then a circular fade to fully
        # transparent exactly around the network's outer edge.
        backdrop = NSGradient.alloc().initWithStartingColor_endingColor_(
            _paper(0.96), _paper(0.0))
        backdrop.drawFromCenter_radius_toCenter_radius_options_(
            center, 7.0, center, min(bounds.size.width,
                                     bounds.size.height) / 2.0,
            NSGradientDrawsBeforeStartingLocation)

        if self.completed:
            pulse = (math.sin(self.phase * 1.35) + 1.0) / 2.0
            for inset, alpha, width in (
                    (5.0, 0.07, 5.0), (8.0, 0.12, 2.7),
                    (11.0, 0.18, 1.25)):
                halo = NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(inset, inset,
                               bounds.size.width - inset * 2,
                               bounds.size.height - inset * 2))
                self._stroke(halo, width + pulse, _ink(alpha + pulse * 0.04))
            visible_nodes = len(self.NODES)
            visible_edges = len(self.EDGES)
            content_alpha = 1.0
        else:
            cycle = self.phase % 6.2
            visible_nodes = min(len(self.NODES), int(cycle / 0.38) + 1)
            visible_edges = min(
                len(self.EDGES), max(0, int((cycle - 2.5) / 0.24) + 1))
            content_alpha = min(1.0, max(0.0, (6.2 - cycle) / 0.7))

        appeared = set(self.NODE_ORDER[:visible_nodes])
        for edge_index in self.EDGE_ORDER[:visible_edges]:
            start_index, end_index = self.EDGES[edge_index]
            if start_index not in appeared or end_index not in appeared:
                continue
            start_x, start_y, _ = self.NODES[start_index]
            end_x, end_y, _ = self.NODES[end_index]
            edge = NSBezierPath.bezierPath()
            edge.moveToPoint_(NSMakePoint(start_x, start_y))
            edge.lineToPoint_(NSMakePoint(end_x, end_y))
            self._stroke(edge, 1.5 if self.completed else 1.25,
                         _graphite((0.72 if self.completed else 0.48)
                                   * content_alpha))

        for order_index, node_index in enumerate(self.NODE_ORDER[:visible_nodes]):
            x_pos, y_pos, radius = self.NODES[node_index]
            node = self._node_path(x_pos, y_pos, radius)
            _ink(content_alpha).setFill()
            node.fill()
            if (not self.completed and order_index == visible_nodes - 1
                    and visible_nodes < len(self.NODES)):
                arrival = self._node_path(x_pos, y_pos, radius + 3.0)
                self._stroke(arrival, 1.0, _graphite(0.38 * content_alpha))


class StatusOverlay:
    def __init__(self):
        self._hide_timer: threading.Timer | None = None
        self._animation_timer: threading.Timer | None = None
        self._last_bounds: tuple[float, float, float, float] | None = None
        self._mode: str | None = None
        self._started_at = 0.0
        self._completed_at: float | None = None
        self._animation_generation = 0

        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, NETWORK_SIZE, NETWORK_SIZE),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary)

        self.background = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, NETWORK_SIZE, NETWORK_SIZE))
        self.background.setWantsLayer_(True)

        self.network = NetworkView.alloc().initWithFrame_(
            NSMakeRect(0, 0, NETWORK_SIZE, NETWORK_SIZE))
        self.background.addSubview_(self.network)

        self.label = NSTextField.labelWithString_("")
        self.label.setAlignment_(NSTextAlignmentCenter)
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setFont_(NSFont.systemFontOfSize_weight_(
            12.0, NSFontWeightMedium))
        self.label.setHidden_(True)
        self.background.addSubview_(self.label)
        self.panel.setContentView_(self.background)

    def start(self, bounds=None) -> None:
        """Show and continuously animate the rewriting mascot."""
        AppHelper.callAfter(self._start, bounds)

    def move(self, bounds=None) -> None:
        """Keep the in-flight asset anchored as capture information improves."""
        AppHelper.callAfter(self._move, bounds)

    def complete(self, bounds=None) -> None:
        """Light the complete graph, hold briefly, then fade the asset out."""
        AppHelper.callAfter(self._complete, bounds)

    def show(self, text: str, bounds=None, *, auto_hide: float = 0) -> None:
        """Fallback text pill used for errors and asynchronous feedback."""
        AppHelper.callAfter(self._show_message, text, bounds, auto_hide)

    def _remember_bounds(self, bounds) -> None:
        if bounds is not None:
            self._last_bounds = tuple(float(value) for value in bounds)

    def _cancel_timer(self, name: str) -> None:
        timer = getattr(self, name)
        if timer is not None:
            timer.cancel()
            setattr(self, name, None)

    def _stop_animation(self) -> None:
        self._cancel_timer("_animation_timer")
        # Timer.cancel cannot recall callbacks already queued on Cocoa's loop.
        self._animation_generation += 1

    def _start(self, bounds) -> None:
        self._cancel_timer("_hide_timer")
        self._stop_animation()
        self._remember_bounds(bounds)
        self._mode = "working"
        self._started_at = time.monotonic()
        self._completed_at = None
        self._configure_network()
        self.network.setAnimationState_completed_(0.0, False)
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()
        self._schedule_animation()

    def _move(self, bounds) -> None:
        self._remember_bounds(bounds)
        if self._mode in {"working", "complete"}:
            self._position(NETWORK_SIZE, NETWORK_SIZE)

    def _complete(self, bounds) -> None:
        if self._mode != "working":
            return
        self._cancel_timer("_hide_timer")
        self._stop_animation()
        self._remember_bounds(bounds)
        self._mode = "complete"
        self._completed_at = max(0.0, time.monotonic() - self._started_at)
        self._configure_network()
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()
        self.network.setAnimationState_completed_(
            self._completed_at * PHASE_SPEED, True)
        self._schedule_animation()

    def _configure_network(self) -> None:
        self._position(NETWORK_SIZE, NETWORK_SIZE)
        self.background.setFrame_(NSMakeRect(0, 0, NETWORK_SIZE, NETWORK_SIZE))
        layer = self.background.layer()
        layer.setCornerRadius_(0)
        layer.setMasksToBounds_(False)
        layer.setBackgroundColor_(NSColor.clearColor().CGColor())
        layer.setBorderWidth_(0)
        self.network.setFrame_(NSMakeRect(0, 0, NETWORK_SIZE, NETWORK_SIZE))
        self.network.setHidden_(False)
        self.label.setHidden_(True)

    def _show_message(self, text: str, bounds, auto_hide: float) -> None:
        self._cancel_timer("_hide_timer")
        self._stop_animation()
        self._remember_bounds(bounds)
        self._mode = "message"
        width = _text_width(text)
        self._position(width, MESSAGE_HEIGHT)
        self.background.setFrame_(NSMakeRect(0, 0, width, MESSAGE_HEIGHT))
        layer = self.background.layer()
        layer.setCornerRadius_(12.0)
        layer.setMasksToBounds_(True)
        layer.setBackgroundColor_(_ink(0.94).CGColor())
        layer.setBorderWidth_(0)
        self.network.setHidden_(True)
        self.label.setHidden_(False)
        self.label.setFrame_(NSMakeRect(12, 0, width - 24, MESSAGE_HEIGHT))
        self.label.setStringValue_(text)
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()
        if auto_hide:
            self._hide_timer = threading.Timer(auto_hide, self.hide)
            self._hide_timer.daemon = True
            self._hide_timer.start()

    def _schedule_animation(self) -> None:
        if self._mode not in {"working", "complete"}:
            return
        if self._animation_timer is not None:
            return
        generation = self._animation_generation
        self._animation_timer = threading.Timer(
            FRAME_SECONDS, lambda: AppHelper.callAfter(self._animate, generation))
        self._animation_timer.daemon = True
        self._animation_timer.start()

    def _animate(self, generation: int) -> None:
        if generation != self._animation_generation:
            return
        self._animation_timer = None
        if self._mode not in {"working", "complete"}:
            return
        elapsed = max(0.0, time.monotonic() - self._started_at)
        completed = self._mode == "complete"
        if completed:
            finish_elapsed = max(0.0, elapsed - self._completed_at)
            if finish_elapsed >= COMPLETE_SECONDS:
                self._hide()
                return
            self.panel.setAlphaValue_(min(
                1.0, (COMPLETE_SECONDS - finish_elapsed) / FADE_SECONDS))
        self.network.setAnimationState_completed_(elapsed * PHASE_SPEED, completed)
        self._schedule_animation()

    def _position(self, width: float, height: float) -> None:
        self.panel.setFrame_display_(
            NSMakeRect(*self._origin(width, height), width, height), True)

    def hide(self) -> None:
        AppHelper.callAfter(self._hide)

    def shutdown(self) -> None:
        """Synchronously release timers and the panel on the Cocoa thread."""
        self._hide()

    def _hide(self) -> None:
        self._cancel_timer("_hide_timer")
        self._stop_animation()
        self._mode = None
        self._completed_at = None
        self.panel.orderOut_(None)
        self.panel.setAlphaValue_(1.0)

    def _origin(self, width: float, height: float) -> tuple[float, float]:
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
            if panel_ax_y + height > ax_bottom:
                panel_ax_y = max(ax_top, y - height - PANEL_GAP)
            origin_x = x + field_width - width
            origin_y = primary_height - panel_ax_y - height
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
                           - height - PANEL_GAP))
        return origin_x, origin_y
