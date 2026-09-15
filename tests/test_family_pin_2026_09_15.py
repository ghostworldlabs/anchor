"""codex-discipline-2026-09-15 Wave 1.1 — the steward family pin (hermetic).

A launched steward keeps its family across dashboard default_cli changes; only
an explicit switch, a missing CLI, or dead auth changes it. Transient catalog
failures keep the family AND the last selection, journaled once per window.
"""
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import steward_engine as eng  # noqa: E402
import model_policy  # noqa: E402

SETTINGS = {"default_cli": "claude", "coding_family": "claude", "review_family": "grok",
            "settings_revision": 8, "model_policy": dict(model_policy.DEFAULT_POLICY)}
CODEX_SELECTION = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra",
                   "requested_policy": dict(model_policy.DEFAULT_POLICY)}


@pytest.fixture
def campaign(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="steward-pin-")
    monkeypatch.setattr(eng, "STATE_FILE", Path(tmp) / "state.json")
    monkeypatch.setattr("anchor_settings.load_settings", lambda: dict(SETTINGS))
    monkeypatch.setattr("anchor_settings.get_launch_settings", lambda: dict(SETTINGS))
    return tmp


def _launched_codex_engine(campaign):
    eng._update_state(str(campaign), {"cli": "chatgpt", "model_policy": dict(CODEX_SELECTION),
                                      "session_id": "01a09813-6605-7e13-b5ed-701477dd3d5e"})
    return eng.Engine(campaign, fake=True)


def test_launched_steward_keeps_its_family_when_the_dashboard_default_changes(campaign):
    e = _launched_codex_engine(campaign)
    assert e._family_pinned is True
    assert e.cli == "chatgpt"
    settings, target = e._desired_policy()
    assert settings["default_cli"] == "claude"
    assert target == "chatgpt"


def test_fresh_steward_is_seeded_by_the_dashboard_default(campaign):
    e = eng.Engine(campaign, fake=True)
    assert e._family_pinned is False
    _settings, target = e._desired_policy()
    assert target == "claude"


def test_explicit_switch_beats_the_pin(campaign):
    e = _launched_codex_engine(campaign)
    e.policy_override = {"family": "claude", "reason": "explicit_session_choice", "revision": 3}
    _settings, target = e._desired_policy()
    assert target == "claude"


def test_state_shows_pinned_family_and_no_false_pending_switch(campaign):
    e = _launched_codex_engine(campaign)
    st = e.state()
    assert st["cli"] == "chatgpt"
    assert st["selected_cli"] == "claude"
    assert st["family_pinned"] is True
    assert st["pending_switch"] is None


def test_transient_catalog_failure_keeps_family_and_last_selection(campaign, monkeypatch):
    e = _launched_codex_engine(campaign)
    journaled = []
    monkeypatch.setattr(e, "_journal_routing", lambda **event: journaled.append(event))
    monkeypatch.setattr(e, "_select_available_policy",
                        lambda *a, **k: pytest.fail("ladder must not be walked on a transient failure"))

    def timed_out(family, **_kw):
        raise model_policy.PolicyUnavailable(family, "CLI discovery TimeoutExpired")
    monkeypatch.setattr(model_policy, "resolve", timed_out)

    target, selection = e._pinned_selection(dict(SETTINGS), "chatgpt")
    assert target == "chatgpt"
    assert selection == CODEX_SELECTION
    assert journaled and journaled[0]["action"] == "stale_catalog"
    assert "gpt-6-astra/ultra" in journaled[0]["message"]
    # rate-limited: a second failure inside the window journals nothing new
    e._pinned_selection(dict(SETTINGS), "chatgpt")
    assert len(journaled) == 1
    e._stale_catalog_noted_at = time.time() - 601
    e._pinned_selection(dict(SETTINGS), "chatgpt")
    assert len(journaled) == 2


def test_missing_cli_walks_the_ladder_without_the_missing_family(campaign, monkeypatch):
    """Discovery runs off the request thread; a missing CLI found there makes
    the NEXT send walk the ladder (the current send still answers)."""
    e = _launched_codex_engine(campaign)
    seen = {}
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: None)

    def missing(family, **_kw):
        raise model_policy.PolicyUnavailable(family, "subscription CLI is not installed", code="cli_missing")
    monkeypatch.setattr(model_policy, "resolve", missing)
    monkeypatch.setattr(e, "_journal_routing", lambda **event: None)

    def ladder(settings, target, excluded=()):
        seen["excluded"] = tuple(excluded)
        return "claude", {"family": "claude", "model": "best", "effort": "max"}
    monkeypatch.setattr(e, "_select_available_policy", ladder)

    target, selection = e._pinned_selection(dict(SETTINGS), "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-6-astra")  # answered now
    e._catalog_refresh_thread.join(5)
    assert e._pinned_cli_missing is True
    target, _selection = e._pinned_selection(dict(SETTINGS), "chatgpt")
    assert target == "claude"
    assert seen["excluded"] == ("chatgpt",)


def test_healthy_probe_refreshes_the_selection_in_place(campaign, monkeypatch):
    e = _launched_codex_engine(campaign)
    newer = dict(CODEX_SELECTION, model="gpt-7-nova", stale=False)
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: dict(newer))
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **k: pytest.fail("fresh cache needs no probe"))
    target, selection = e._pinned_selection(dict(SETTINGS), "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-7-nova")
    assert "stale" not in selection


def test_busy_turn_never_probes(campaign, monkeypatch):
    e = _launched_codex_engine(campaign)
    e.busy = True
    monkeypatch.setattr(model_policy, "resolve",
                        lambda *a, **k: pytest.fail("no discovery while a turn is running"))
    assert e._pinned_selection(dict(SETTINGS), "chatgpt") == ("chatgpt", CODEX_SELECTION)
