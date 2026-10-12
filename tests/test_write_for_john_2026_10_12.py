"""John 2026-10-12: plans and reports open in plain words, and the finish stays light (Book 1 v2, calc history plan)."""
from steward_cockpit import steward_engine as se


def test_every_duty_tells_the_steward_to_write_for_john():
    for duty in (se.SMALL_DUTY, se.EFFORT_DUTY):
        assert "WRITE FOR JOHN" in duty and "plain sentences a non-programmer follows" in duty
    assert "Show John the plan in plain words" in se.SIZE_OR_HOLD


def test_the_finish_is_kept_light():
    assert "no extra receipt, hash or provenance files unless he asks" in se.WRITE_FOR_JOHN
