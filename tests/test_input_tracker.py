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


def test_clear_and_focus_change_keep_last_nonempty_snapshot():
    tracker = EditTracker(timeout_s=15)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    tracker.observe(_snapshot("human final"), now=1)
    event = tracker.observe(_snapshot(""), now=2)
    assert event is not None and event.final_text == "human final"
    assert event.trigger == "cleared"

    tracker.start(_snapshot("again"), translate_id="tr-2",
                  original="raw", polished="again", now=3)
    event = tracker.observe(replace(_snapshot("other"), identity="box-2"),
                            now=4)
    assert event is not None and event.final_text == "again"
    assert event.trigger == "focus_changed"


def test_edit_refreshes_timeout():
    tracker = EditTracker(timeout_s=5)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot("edited"), now=4) is None
    assert tracker.observe(_snapshot("edited"), now=8) is None
    event = tracker.observe(_snapshot("edited"), now=9.1)
    assert event is not None and event.trigger == "timeout"


def test_pointer_recheck_inside_same_input_keeps_tracking():
    tracker = EditTracker(timeout_s=15)
    tracker.start(_snapshot("polished"), translate_id="tr-1",
                  original="raw", polished="polished", now=0)
    assert tracker.observe(_snapshot("polished"), now=1) is None
    assert tracker.active is True
