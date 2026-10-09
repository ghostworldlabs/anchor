"""S7 of the slim plan (night 2026-10-10): John approved the slim Foreman/Crucible design (2026-10-09, "go ahead ...
include the crucible/foreman plan"). The hold lifts; the steward SIZES the work (small = a code job; a feature =
Crucible slim then Foreman slim as skill jobs, on John's approval; multi-part = standard, on his word); Foreman
started from Anchor runs slim unless a profile is named. ANCHOR_FOREMAN_CRUCIBLE_HOLD=1 puts the hold back."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, skill_jobs  # noqa: E402


def test_the_hold_stays_by_default_and_lifts_only_by_hand(monkeypatch):
    # final review 2026-10-10 (BLOCKER): Foreman as a skill job would write the project outside the protected
    # code-job lifecycle - the hold stays until it runs through that lifecycle
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    assert code_jobs.foreman_crucible_held() is True
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    assert code_jobs.foreman_crucible_held() is False


def test_foreman_from_anchor_runs_slim_unless_a_profile_is_named():
    run = ["node", r"C:\dev\trio\foreman\bin\run-live.mjs", r"C:\work\proj", "--git"]
    assert skill_jobs.with_profile(run)[-2:] == ["--profile", "slim"]
    named = run + ["--profile", "standard"]
    assert skill_jobs.with_profile(named) == named
    other = ["node", r"C:\dev\trio\crucible\bin\slim.mjs", "out", "--task", "x"]
    assert skill_jobs.with_profile(other) == other


def test_held_by_default_the_hold_sentence_stands_and_lifted_the_steward_sizes_the_work(monkeypatch):
    import steward_cockpit.steward_engine as se
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    se = importlib.reload(se)
    assert "Foreman and Crucible are on hold" in se.CONTRACT and "SIZE THE WORK" not in se.CONTRACT
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    se = importlib.reload(se)
    for text in (se.CONTRACT, se.EFFORT_DUTY, se.EFFORT_RULES):
        assert "SIZE THE WORK" in text and "on hold" not in text
    assert "crucible/bin/slim.mjs" in se.SIZE_OR_HOLD and "foreman/bin/run-live.mjs" in se.SIZE_OR_HOLD
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    importlib.reload(se)


def test_a_held_skill_root_still_refuses_foreman(monkeypatch, tmp_path):
    root = tmp_path / "trio"
    script = root / "foreman" / "bin" / "run-live.mjs"
    script.parent.mkdir(parents=True)
    script.write_text("//", encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(root))
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    ok, why = skill_jobs.validate(["node", str(script), "proj"])
    assert not ok and "hold" in why
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    assert skill_jobs.validate(["node", str(script), "proj"]) == (True, "")
