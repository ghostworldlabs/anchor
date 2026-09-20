"""Cockpit workflow Wave B (2026-09-20) — the Anchor side of "the steward states its next act".

STUB GATE for PLAN.md v3 rows B3 and B4 (Skill Foundry/planning/cockpit-workflow-2026-09-19):

- B3 off-path steps fold by default: the plan tree keeps the sequence open and folds done, parked and
  supporting steps; a group with several active steps and no pin says so in its title.
- B4 the goal re-read note: the engine now appends the goal_flip at close, so the reader flags a missing
  re-read only for a close older than a day.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path


def _campaign(tmp, close_at, with_flip=False):
    d = Path(tmp) / "camp"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text("## North star\n\nShip the guide.\n", encoding="utf-8")
    events = [{"kind": "status_flip", "step_id": "s1", "to": "done", "at": close_at, "receipt": {"who": "steward", "why": "landed"}}]
    if with_flip:
        events.append({"kind": "goal_flip", "step_id": "s1", "verdict": "reaffirmed", "scope": "s1", "receipt": {"who": "engine", "why": "close"}})
    (d / "roadmap.json").write_text(json.dumps({
        "schema": "ecgberht-roadmap-v0", "roadmap_events": events,
        "roadmap_projection": [{"id": "s1", "name": "Survey", "status": "done"}, {"id": "s2", "name": "Guide", "status": "active"}],
    }), encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"schema": "ecgberht-strip-v0", "phase": "slice", "active_effort": "Guide",
                                              "current_step_id": "s2", "next_recommended": "Draft the guide", "why_next": "it gates the trial",
                                              "human_wait": "", "receipts": []}), encoding="utf-8")
    return d


def test_a_close_younger_than_a_day_is_not_yet_a_missed_re_read(tmp_path):
    from steward_cockpit import steward_campaign as sc
    fresh = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    m = sc.read_map(str(_campaign(tmp_path / "fresh", fresh)))
    assert m["goal_reread"] is True
    st = sc.compose_status(str(tmp_path / "fresh" / "camp"), {"busy": False})
    assert "goal not re-read" not in " ".join(st["now"])
    old = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
    m = sc.read_map(str(_campaign(tmp_path / "old", old)))
    assert m["goal_reread"] is False                                        # two days without the flip: the note stands
    assert sc.read_map(str(_campaign(tmp_path / "flipped", old, with_flip=True)))["goal_reread"] is True
    m = sc.read_map(str(_campaign(tmp_path / "dated", (datetime.now() - timedelta(days=3)).date().isoformat())))
    assert m["goal_reread"] is False                                        # a date-only stamp (the CLI's todayIso) reads too
    assert sc.read_map(str(_campaign(tmp_path / "today", datetime.now().date().isoformat())))["goal_reread"] is True


def test_the_plan_tree_keeps_the_sequence_open_and_folds_the_rest():
    js = Path(__file__).resolve().parents[1].joinpath("steward_cockpit", "static", "shared.js").read_text(encoding="utf-8")
    body = js.split("function renderGroup(g,parent)")[1].split("if(stepRows)model.roots.forEach")[0]
    assert "const offPath=st=>stepDone(st)||st.status==='parked';" in body
    assert "s.step.navigation.role==='primary'&&!offPath(s.step)" in body              # the open sequence
    assert "s.step.navigation.role!=='primary'||offPath(s.step)" in body                # the fold
    assert "'Done, parked and supporting steps · '" in body
    assert "' active — pin one'" in body and "actives.length>1&&!pinned" in body       # the honest count in the title
