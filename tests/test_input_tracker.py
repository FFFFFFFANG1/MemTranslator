from dataclasses import replace

from memtranslator.hotkey.models import InputSnapshot, TextRange
from memtranslator.hotkey.tracker import EditTracker


def _snapshot(text: str, identity: str = "box-1") -> InputSnapshot:
    return InputSnapshot(identity=identity, full_text=text,
                         target_range=TextRange(0, len(text)),
                         app_name="Slack",
                         app_bundle_id="com.tinyspeck.slackmacgap",
                         role="AXTextArea")


def test_default_timeout_is_five_minutes():
    assert EditTracker().timeout_s == 5 * 60


def test_enter_finishes_with_latest_edited_text():
    tracker = EditTracker(timeout_s=15)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot("polished edited"), now=1) is None
    event = tracker.observe(_snapshot("polished edited"),
                            key="Enter", now=2)
    assert event is not None
    assert event.final_text == "polished edited"
    assert event.trigger == "enter"


def test_focus_change_parks_tracker_and_enter_elsewhere_is_ignored():
    tracker = EditTracker(timeout_s=15)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot("human final"), now=1) is None
    other = replace(_snapshot("code editor"), identity="box-2")
    assert tracker.observe(other, key="Enter", now=2) is None
    assert tracker.active is True

    event = tracker.observe(_snapshot("human final revised"),
                            key="Enter", now=3)
    assert event is not None
    assert event.final_text == "human final revised"
    assert event.trigger == "enter"


def test_clear_and_timeout_cancel_without_caching_feedback():
    tracker = EditTracker(timeout_s=5)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot(""), now=1) is None
    assert tracker.active is False

    tracker.start(_snapshot("again"), translate_id="tr-2",
                  original="raw", polished="again", now=2)
    assert tracker.observe(_snapshot("again"), now=7.1) is None
    assert tracker.active is False


def test_edit_refreshes_timeout():
    tracker = EditTracker(timeout_s=5)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot("edited"), now=4) is None
    assert tracker.observe(_snapshot("edited"), now=8) is None
    assert tracker.observe(_snapshot("edited"), now=9.1) is None
    assert tracker.active is False


def test_pointer_recheck_inside_same_input_keeps_tracking():
    tracker = EditTracker(timeout_s=15)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot("polished"), now=1) is None
    assert tracker.active is True
