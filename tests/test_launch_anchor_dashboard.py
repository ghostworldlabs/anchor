"""Service-aware dashboard launcher — simple onboard shell Wave 1."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import launch_anchor_dashboard as lad  # noqa: E402
import share_onboard as sob  # noqa: E402

URL = sob.DEFAULT_LOCAL_DASHBOARD_URL


def test_already_running_skips_start_and_opens_browser():
    opens = []
    starts = []

    def probe(url):
        return True

    def start():
        starts.append(1)
        return {"attempted": True, "started": True}

    r = lad.ensure_dashboard_running(
        url=URL,
        probe_fn=probe,
        start_fn=start,
        open_fn=lambda u: opens.append(u),
        retries=1,
        sleep_s=0,
    )
    assert r["ok"] is True
    assert r["already_running"] is True
    assert r["start_attempted"] is False
    assert starts == []
    assert opens == [URL]


def test_down_then_start_then_open():
    opens = []
    state = {"n": 0}

    def probe(url):
        state["n"] += 1
        # first probe fail; after start succeed
        return state["n"] >= 2

    def start():
        return {"attempted": True, "started": True}

    r = lad.ensure_dashboard_running(
        url=URL,
        probe_fn=probe,
        start_fn=start,
        open_fn=lambda u: opens.append(u),
        retries=3,
        sleep_s=0,
    )
    assert r["start_attempted"] is True
    assert r["ok"] is True
    assert opens == [URL]


def test_refuses_non_local_url():
    r = lad.ensure_dashboard_running(
        url="https://example.com",
        open_fn=lambda u: None,
        sleep_s=0,
    )
    assert r["ok"] is False
    assert "non_local_dashboard_url" in r["reason_codes"]


def test_still_down_after_start_is_not_ok():
    r = lad.ensure_dashboard_running(
        url=URL,
        probe_fn=lambda u: False,
        start_fn=lambda: {"attempted": True, "started": False},
        open_fn=lambda u: None,
        retries=2,
        sleep_s=0,
    )
    assert r["ok"] is False
    assert "anchor_service_unavailable" in r["reason_codes"]
