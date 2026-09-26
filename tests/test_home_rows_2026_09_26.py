"""home_rows + the W1a rules — every row on the home is a fact from a project's steward record (High Seat).

Hermetic: temp project folders carry a strip, a roadmap projection and a persisted status summary.
"""
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import home_attention as ha  # noqa: E402
import home_rows as hr  # noqa: E402

TODAY = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 17, 30)


def _project(tmp_path, pid, name, steps=(), wait=None, lead="", nxt="", why=""):
    d = tmp_path / name.replace(" ", "_")
    d.mkdir()
    (d / "strip.json").write_text(json.dumps({"human_wait": wait, "next_recommended": nxt, "why_next": why}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": list(steps)}), encoding="utf-8")
    if lead:
        (d / ".ecgberht").mkdir()
        (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-26T17:00", "lead_line": lead, "plan": {}}), encoding="utf-8")
    return {"id": pid, "name": name, "folder_path": str(d)}


def _world(tmp_path):
    mba = _project(tmp_path, "6765ece4", "MBA Teaching AI", steps=[
        {"id": "lec3", "name": "Lecture 3 AI supplement", "status": "waiting", "due": "2026-10-10"},
        {"id": "hw2", "name": "retool homework 2", "status": "planned", "due": "2026-10-27"},
        {"id": "syl", "name": "Syllabus", "status": "done", "due": "2026-09-01"},
        {"id": "old", "name": "Block 1 quiz", "status": "planned", "due": "2026-09-20"},
    ], wait="approve the Lecture 3 AI supplement", lead="Next: Lecture 3 — the interface lesson is final.")
    trusts = _project(tmp_path, "9405abe0", "Family Trusts", steps=[
        {"id": "val", "name": "Company valuations into the package", "status": "active", "due": "2026-10-08"},
    ], nxt="Send the three valuation figures", why="the package closes on them")
    empty = _project(tmp_path, "aaaaaaaa", "Quiet project")
    return mba, trusts, empty


def test_project_facts_read_the_record_and_never_the_done_steps(tmp_path):
    mba, trusts, empty = _world(tmp_path)
    f = hr.project_facts(mba, TODAY)
    assert f["has_record"] and f["href"] == "/project/6765ece4"
    assert f["needs_you"] == "approve the Lecture 3 AI supplement"
    assert f["lead"].startswith("Next: Lecture 3")
    assert [s["due"] for s in f["dated"]] == ["2026-09-20", "2026-10-10", "2026-10-27"]   # soonest first; the done syllabus is out
    assert f["nearest_due"] == "2026-09-20"
    t = hr.project_facts(trusts, TODAY)
    assert t["needs_you"] == ""
    assert t["lead"] == "Next: Send the three valuation figures — the package closes on them"   # no summary: the strip's next + why
    e = hr.project_facts(empty, TODAY)
    assert e["has_record"] and e["dated"] == [] and e["nearest_due"] == "" and e["lead"] == ""
    nothing = hr.project_facts({"id": "x", "name": "no folder"}, TODAY)
    assert nothing["has_record"] is False and nothing["dated"] == []


def test_the_rows_are_facts_from_the_records_in_rule_order(tmp_path):
    facts = hr.all_project_facts(_world(tmp_path), TODAY)
    rows = ha.build_attention(projects=facts, today=TODAY, now=NOW, limit=10)
    assert [r["rule"] for r in rows] == ["needs-you", "overdue", "due-soon", "due-soon", "due-soon"]
    assert rows[0]["text"] == "MBA Teaching AI is waiting on you" and rows[0]["why"] == "approve the Lecture 3 AI supplement"
    assert rows[1]["text"] == "Block 1 quiz" and rows[1]["why"] == "due Sep 20 (6 days ago) · MBA Teaching AI"
    assert rows[1]["href"] == "/project/6765ece4#plan" and rows[1]["kind"] == "step"
    assert [r["text"] for r in rows[2:]] == ["Company valuations into the package", "Lecture 3 AI supplement", "retool homework 2"]
    assert rows[2]["why"] == "due Oct 8 · Family Trusts"
    assert all(r["rule_label"] for r in rows)


def test_a_session_row_for_the_same_project_is_not_repeated_and_far_dates_stay_out(tmp_path):
    facts = hr.all_project_facts(_world(tmp_path), TODAY)
    sess = [{"status": "needs-attention", "project_id": "6765ece4", "lane": "plan", "label": "",
             "updated_at": NOW.timestamp(), "created_at": NOW.timestamp()}]
    rows = ha.build_attention(sessions=sess, projects=facts, today=TODAY, now=NOW,
                              project_names={"6765ece4": "MBA Teaching AI"}, limit=10)
    waits = [r for r in rows if r["rule"] == "needs-you"]
    assert len(waits) == 1 and waits[0]["why"] == "plan session needs an answer"
    # a step dated beyond five weeks does not raise a row
    far = date(2026, 12, 1)
    facts2 = hr.all_project_facts(_world(tmp_path / "later"), far) if (tmp_path / "later").mkdir() is None else []
    rows_far = ha.build_attention(projects=facts2, today=date(2026, 8, 1), now=datetime(2026, 8, 1, 9), limit=10)
    assert [r["rule"] for r in rows_far] == ["needs-you"]


def test_the_brief_is_bullets_of_facts(tmp_path):
    facts = hr.all_project_facts(_world(tmp_path), TODAY)
    rows = ha.build_attention(projects=facts, today=TODAY, now=NOW, limit=10)
    b = ha.brief_bullets(rows, facts, today=TODAY, seat_name="High Seat")
    assert b[0] == "MBA Teaching AI is waiting on you — approve the Lecture 3 AI supplement."
    assert b[1] == "Nothing is due this week; the nearest date is Sep 20 (Block 1 quiz, MBA Teaching AI)." or b[1].startswith("Nothing is due this week")
    assert b[-1] == "You can act from here. Opening the High Seat is optional."
    assert len(b) <= 4
    quiet = ha.brief_bullets([], [], today=TODAY)
    assert quiet[0] == "Nothing is waiting on you." and quiet[1] == "Nothing carries a date yet."


def test_the_week_in_words_and_the_short_date():
    assert hr.week_in_words(date(2026, 9, 26)) == "this week Sep 21–27"
    assert hr.week_in_words(date(2026, 9, 30)) == "this week Sep 28 – Oct 4"
    assert hr.short_date("2026-10-08") == "Oct 8"
    assert hr.short_date("junk") == "junk"
