from unittest.mock import Mock

import pytest

pytest.importorskip("AppKit")
pytest.importorskip("Quartz")  # Register Core Graphics bridges, as the client does.

from memtranslator.hotkey import overlay
from memtranslator.hotkey.overlay import COMPLETE_SECONDS, NETWORK_SIZE, PHASE_SPEED


class FakeTimer:
    def __init__(self, delay, callback):
        self.delay, self.callback = delay, callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def state(monkeypatch):
    """Exercise the real state machine without windows, timers, or event taps."""
    monkeypatch.setattr(overlay.threading, "Timer", FakeTimer)
    clock = [100.0]
    monkeypatch.setattr(overlay.time, "monotonic", lambda: clock[0])
    instance = overlay.StatusOverlay.__new__(overlay.StatusOverlay)
    instance._hide_timer = instance._animation_timer = None
    instance._last_bounds = instance._mode = None
    instance._started_at = 0.0
    instance._completed_at = None
    instance._animation_generation = 0
    instance.panel, instance.network = Mock(), Mock()
    instance.background, instance.label = Mock(), Mock()
    instance._position = Mock()
    return instance, clock


def test_completed_animation_uses_elapsed_time_and_hides_even_if_frames_are_late(state):
    instance, clock = state
    instance._start((10, 20, 300, 80))
    assert instance._animation_timer.daemon is True
    assert instance._animation_timer.started is True
    instance.panel.setAlphaValue_.assert_called_with(1)
    clock[0] += 10
    instance._animate(instance._animation_generation)
    instance.panel.setAlphaValue_.assert_called_with(1)
    instance._complete(None)
    instance.network.setAnimationState_completed_.assert_called_with(10 * PHASE_SPEED, True)
    assert instance._started_at == 100
    assert instance._completed_at == 10
    clock[0] += COMPLETE_SECONDS + 1
    instance._animate(instance._animation_generation)
    assert instance._mode is None
    assert instance._animation_timer is None
    instance.panel.orderOut_.assert_called_once_with(None)


def test_queued_old_frame_cannot_interrupt_a_new_rewrite(state):
    instance, _ = state
    instance._start(None)
    old_timer = instance._animation_timer
    old_generation = instance._animation_generation
    instance._start(None)
    new_timer = instance._animation_timer
    instance.network.reset_mock()
    instance._animate(old_generation)
    assert old_timer.cancelled is True
    assert instance._animation_timer is new_timer
    instance.network.setAnimationState_completed_.assert_not_called()


@pytest.mark.parametrize("duration", [0.01, 0.2, 1.96, 13.37, 3600])
def test_network_waits_for_explicit_success_and_preserves_phase(state, duration):
    instance, clock = state
    instance._start(None)
    clock[0] += duration
    instance._animate(instance._animation_generation)
    before = instance.network.setAnimationState_completed_.call_args.args
    assert before == (pytest.approx(duration * PHASE_SPEED), False)
    assert instance._mode == "working"
    instance._complete(None)
    after = instance.network.setAnimationState_completed_.call_args.args
    assert after == (before[0], True)
    instance.panel.setAlphaValue_.assert_called_with(1)
    completion = instance._completed_at
    clock[0] += 0.2
    instance._animate(instance._animation_generation)
    during = instance.network.setAnimationState_completed_.call_args.args
    assert during == (pytest.approx((duration + 0.2) * PHASE_SPEED), True)
    instance._complete(None)  # A duplicate callback cannot restart the finish.
    assert instance._completed_at == completion


def test_new_rewrite_resets_completion_and_ignores_previous_success_frames(state):
    instance, clock = state
    instance._start(None)
    clock[0] += 2
    instance._complete(None)
    old_generation = instance._animation_generation
    old_timer = instance._animation_timer
    instance._start(None)
    assert instance._completed_at is None
    assert instance._started_at == clock[0]
    assert old_timer.cancelled
    instance.network.setAnimationState_completed_.assert_called_with(0, False)
    instance.network.reset_mock()
    instance._animate(old_generation)
    instance.network.setAnimationState_completed_.assert_not_called()
    assert instance._mode == "working"


def test_error_message_cancels_animation_and_cannot_play_success(state):
    instance, _ = state
    instance._start(None)
    old_generation = instance._animation_generation
    instance._show_message("Write failed", None, 1.6)
    instance._complete(None)
    instance._animate(old_generation)
    assert instance._mode == "message"
    assert instance._animation_timer is None
    assert instance._hide_timer.daemon is True
    instance.network.setHidden_.assert_called_with(True)
    instance.label.setStringValue_.assert_called_with("Write failed")


def test_new_mark_clears_message_background_and_shutdown_releases_timers(state):
    instance, _ = state
    instance._show_message("Saved", None, 1.2)
    message_timer = instance._hide_timer
    instance._start(None)
    assert message_timer.cancelled is True
    instance.background.layer().setMasksToBounds_.assert_called_with(False)
    instance.background.layer().setCornerRadius_.assert_called_with(0)
    animation_timer = instance._animation_timer
    instance.shutdown()
    assert animation_timer.cancelled is True
    assert instance._mode is None
    instance._complete(None)
    assert instance._mode is None


@pytest.mark.parametrize("elapsed,opacity,hidden", [
    (0.2, 1, False), (0.45, 1, False), (0.675, 0.5, False), (1.0, 1, True)])
def test_completed_graph_holds_then_fades_out(state, elapsed, opacity, hidden):
    instance, clock = state
    instance._start(None)
    clock[0] += 3
    instance._complete(None)
    clock[0] += elapsed
    instance._animate(instance._animation_generation)
    instance.panel.setAlphaValue_.assert_called_with(pytest.approx(opacity))
    assert (instance._mode is None) is hidden


def render_native_frame(phase, completed=False, bitmap=None, view=None, pixel_scale=1):
    from AppKit import NSBitmapImageRep, NSCalibratedRGBColorSpace, NSGraphicsContext
    from Quartz import CGContextScaleCTM

    size = int(NETWORK_SIZE * pixel_scale)
    if bitmap is None:
        bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, size, size, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    if view is None:
        view = overlay.NetworkView.alloc().initWithFrame_(
            overlay.NSMakeRect(0, 0, NETWORK_SIZE, NETWORK_SIZE))
    NSGraphicsContext.saveGraphicsState()
    try:
        context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
        NSGraphicsContext.setCurrentContext_(context)
        CGContextScaleCTM(context.CGContext(), pixel_scale, pixel_scale)
        view.setAnimationState_completed_(phase, completed)
        view.drawRect_(view.bounds())
    finally:
        NSGraphicsContext.restoreGraphicsState()
    return bitmap, view


@pytest.mark.parametrize("phase,completed", [
    (0, False), (3.8, False), (6, False), (4, True)])
@pytest.mark.parametrize("pixel_scale", [1, 2])
def test_native_drawing_has_a_radial_backdrop_and_transparent_perimeter(
        phase, completed, pixel_scale):
    bitmap, _ = render_native_frame(phase, completed, pixel_scale=pixel_scale)
    size = int(NETWORK_SIZE * pixel_scale)
    # These points stay clear of nodes and edges in every state.
    inner = bitmap.colorAtX_y_(size // 2, int(35 * pixel_scale))
    outer = bitmap.colorAtX_y_(size // 2, int(5 * pixel_scale))
    assert inner.alphaComponent() > 0.8
    assert inner.redComponent() > 0.95
    assert 0 < outer.alphaComponent() < 0.3
    for coordinate in range(size):
        for x, y in ((0, coordinate), (size - 1, coordinate),
                     (coordinate, 0), (coordinate, size - 1)):
            assert bitmap.colorAtX_y_(x, y).alphaComponent() < 0.02


def test_native_network_builds_nodes_then_edges():
    first, _ = render_native_frame(0)
    nodes, _ = render_native_frame(2.3)
    edges, _ = render_native_frame(5.3)
    # The center node arrives third; this lower-left edge arrives later.
    center = first.colorAtX_y_(45, 45)
    assert 0.94 < center.alphaComponent() < 1
    assert center.redComponent() > 0.95  # White core, not a transparent hole.
    assert nodes.colorAtX_y_(45, 45).redComponent() < 0.2
    edge_pixels = [(x, y) for x in range(33, 36) for y in range(54, 57)]
    assert min(nodes.colorAtX_y_(x, y).redComponent() for x, y in edge_pixels) > 0.95
    assert min(edges.colorAtX_y_(x, y).redComponent() for x, y in edge_pixels) < 0.85


def test_native_drawing_clears_the_previous_graph_and_halo():
    previous, view = render_native_frame(4.6, True)
    reused, _ = render_native_frame(0, bitmap=previous, view=view)
    fresh, _ = render_native_frame(0)
    for x in range(0, int(NETWORK_SIZE), 3):
        for y in range(0, int(NETWORK_SIZE), 3):
            actual = reused.colorAtX_y_(x, y)
            expected = fresh.colorAtX_y_(x, y)
            assert actual.alphaComponent() == pytest.approx(expected.alphaComponent())
            assert actual.redComponent() == pytest.approx(expected.redComponent())
