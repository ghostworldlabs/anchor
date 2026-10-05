"""Landed is not live (his word, 2026-10-05): a job landed in Anchor's own repository tells the steward it waits for a
restart."""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from steward_cockpit import code_jobs as cj  # noqa: E402


def test_an_anchor_landing_says_it_waits_for_a_restart():
    assert "NOT LIVE YET" in cj.live_note({"landed": True, "repo": HERE})
    assert cj.live_note({"landed": False, "repo": HERE}) == ""
    assert cj.live_note({"landed": True, "repo": os.path.dirname(HERE)}) == "", "another repository is not the service"
    src = open(cj.__file__, encoding="utf-8").read()
    assert "live = live_note(job)" in src
