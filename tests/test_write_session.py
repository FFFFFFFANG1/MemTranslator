from memtranslator.hotkey.models import InputSnapshot, TextRange
from memtranslator.hotkey.session import PendingWrites


def _snapshot(text: str, identity: str = "box-1") -> InputSnapshot:
    return InputSnapshot(
        identity=identity,
        full_text=text,
        target_range=TextRange(0, len(text)),
        app_name="Slack",
        app_bundle_id="com.tinyspeck.slackmacgap",
        role="AXTextArea",
    )


def test_learn_hotkey_builds_feedback_from_the_current_snapshot():
    session = PendingWrites(feedback_timeout_s=15)
    session.start(
        _snapshot("written"),
        translate_id="tr-1",
        original="raw",
        written="written",
        now=0,
    )

    plan = session.plan_learn(_snapshot("written, human-edited"), now=2)

    assert plan.stale is False
    assert plan.translate_id == "tr-1"
    assert plan.feedback is not None
    assert plan.feedback.final_text == "written, human-edited"
    assert plan.feedback.trigger == "learn_hotkey"
    assert session.commit(plan) is True
    assert session.active is False


def test_other_composer_neither_learns_nor_dismisses_pending_write():
    session = PendingWrites(feedback_timeout_s=15)
    session.start(
        _snapshot("written"),
        translate_id="tr-1",
        original="raw",
        written="written",
        now=0,
    )
    other = _snapshot("unrelated", identity="box-2")

    plan = session.plan_learn(other, now=2)

    assert plan.translate_id is None
    assert plan.feedback is None
    assert plan.generation is None
    assert session.commit(plan) is False
    assert session.dismiss(other) is False
    assert session.active is True


def test_returning_to_the_same_composer_can_still_learn():
    session = PendingWrites(feedback_timeout_s=15)
    session.start(
        _snapshot("written"),
        translate_id="tr-1",
        original="raw",
        written="written",
        now=0,
    )
    assert session.dismiss(_snapshot("other", identity="box-2")) is False

    plan = session.plan_learn(_snapshot("written after returning"), now=3)

    assert plan.feedback is not None
    assert plan.feedback.final_text == "written after returning"


def test_plain_enter_dismisses_only_the_matching_composer():
    session = PendingWrites()
    session.start(
        _snapshot("written"),
        translate_id="tr-1",
        original="raw",
        written="written",
        now=0,
    )

    assert session.dismiss(_snapshot("other", identity="box-2")) is False
    assert session.active is True
    assert session.dismiss(_snapshot("written")) is True
    assert session.active is False


def test_repeated_write_keeps_first_origin_but_feedback_targets_latest_write():
    session = PendingWrites(feedback_timeout_s=15)
    session.start(
        _snapshot("written once"),
        translate_id="tr-1",
        original="raw",
        written="written once",
        now=0,
    )
    session.start(
        _snapshot("written twice"),
        translate_id="tr-2",
        original="written once",
        written="written twice",
        now=1,
    )

    plan = session.plan_learn(_snapshot("written twice, edited"), now=2)

    assert plan.translate_id == "tr-1"
    assert plan.feedback is not None
    assert plan.feedback.translate_id == "tr-2"
    assert plan.feedback.original == "written once"


def test_expired_unchanged_write_keeps_provenance_without_feedback():
    session = PendingWrites(feedback_timeout_s=5)
    session.start(
        _snapshot("written"),
        translate_id="tr-1",
        original="raw",
        written="written",
        now=0,
    )

    plan = session.plan_learn(_snapshot("written"), now=5.1)

    assert plan.stale is False
    assert plan.translate_id == "tr-1"
    assert plan.feedback is None


def test_expired_changed_write_fails_closed():
    session = PendingWrites(feedback_timeout_s=5)
    session.start(
        _snapshot("written"),
        translate_id="tr-1",
        original="raw",
        written="written",
        now=0,
    )

    plan = session.plan_learn(_snapshot("possibly another message"), now=5.1)

    assert plan.stale is True
    assert plan.translate_id is None
    assert plan.feedback is None
    assert session.active is True


def test_old_plan_cannot_consume_a_new_generation():
    session = PendingWrites()
    session.start(
        _snapshot("first"),
        translate_id="tr-1",
        original="raw",
        written="first",
        now=0,
    )
    old_plan = session.plan_learn(_snapshot("first"), now=1)
    session.start(
        _snapshot("second"),
        translate_id="tr-2",
        original="first",
        written="second",
        now=2,
    )

    assert session.commit(old_plan) is False
    assert session.active is True


def test_each_composer_keeps_an_independent_pending_write():
    session = PendingWrites(feedback_timeout_s=15)
    session.start(
        _snapshot("written A", identity="box-a"),
        translate_id="tr-a",
        original="raw A",
        written="written A",
        now=0,
    )
    session.start(
        _snapshot("written B", identity="box-b"),
        translate_id="tr-b",
        original="raw B",
        written="written B",
        now=1,
    )

    plan_a = session.plan_learn(
        _snapshot("written A, edited", identity="box-a"), now=2)

    assert plan_a.translate_id == "tr-a"
    assert plan_a.feedback is not None
    assert session.commit(plan_a) is True
    assert session.active is True

    plan_b = session.plan_learn(
        _snapshot("written B", identity="box-b"), now=3)
    assert plan_b.translate_id == "tr-b"
