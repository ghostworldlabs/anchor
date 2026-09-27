"""high_seat_card — a card's parts say what the cockpit says (W2, High Seat). The facts-equal lint: the Status
fragment's rows are compose_status's facts, read through the same readers."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward_cockpit import high_seat_card as card  # noqa: E402
from steward_cockpit import steward_campaign as campaign  # noqa: E402

PID = "6765ece4b3bc43b0b0b0907b92b17280"


def _effort(tmp_path):
    d = tmp_path / "mba"
    d.mkdir()
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> Revise BA 815 for 2026.\n\n## Active effort\n\nLecture 3.\n", encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"human_wait": "approve the Lecture 3 AI supplement", "current_step_id": "lec3",
                                             "next_recommended": "Lecture 4 supplement", "why_next": "it follows"}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": [
        {"id": "syl", "name": "Syllabus", "status": "done"},
        {"id": "lec3", "name": "Lecture 3 AI supplement", "status": "waiting", "waiting_on": "your read", "due": "2026-10-10"},
        {"id": "lec4", "name": "Lecture 4 AI supplement", "status": "planned"},
    ]}), encoding="utf-8")
    (d / "DELIVERABLES.md").write_text("| What | Where | Date | Step |\n|---|---|---|---|\n| Lecture 3 AI supplement, draft 2 | `drafts/lec3.md` | 2026-09-26 | lec3 |\n", encoding="utf-8")
    (d / "drafts").mkdir()
    (d / "drafts" / "lec3.md").write_text("# draft\n", encoding="utf-8")
    return d


def test_status_rows_are_compose_status_facts(tmp_path):
    d = _effort(tmp_path)
    fresh = campaign.compose_status(str(d), None)
    facts = [(f["label"], str(f["value"])) for f in ((fresh.get("compact") or {}).get("facts") or [])]
    out = card.card_part(PID, "status", str(d), "MBA Teaching AI")
    assert out["ok"] and out["part"] == "status"
    for label, value in facts:
        assert "<th>%s</th>" % card.esc(label) in out["html"]
        assert card.esc(value) in out["html"]
    assert 'href="/project/%s"' % PID in out["html"]


def test_next_deliverables_and_plan_read_the_same_record(tmp_path):
    d = _effort(tmp_path)
    nxt = card.card_part(PID, "next", str(d), "MBA Teaching AI")["html"]
    assert "Decide</span>approve the Lecture 3 AI supplement" in nxt
    assert "Next in the plan" in nxt and "Lecture 3 AI supplement" in nxt
    dl = card.card_part(PID, "deliverables", str(d), "MBA Teaching AI")["html"]
    assert "Lecture 3 AI supplement, draft 2" in dl
    pl = card.card_part(PID, "plan", str(d), "MBA Teaching AI")["html"]
    assert "1 of 3 steps done" in pl and "Not done &middot; 2" in pl and "due 2026-10-10" in pl
    assert "Open the plan in the cockpit" in pl


def test_missing_record_and_unknown_part_answer_honestly(tmp_path):
    empty = tmp_path / "quiet"
    empty.mkdir()
    out = card.card_part("abc", "status", str(empty), "Quiet one")
    assert out["ok"] and "No steward record for Quiet one yet" in out["html"]
    bad = card.card_part("abc", "gossip", str(empty), "Quiet one")
    assert bad["ok"] is False and bad["error"] == "unknown part"


def test_a_decision_record_may_name_what_it_depends_on(tmp_path, monkeypatch):
    from steward_cockpit import question_context as qc
    rec = qc.normalize_question_context({"question": "Approve the draft?", "response_text": "Approve the draft? I recommend yes.",
                                         "depends_on": ["Lecture 3 AI supplement, draft 2", 5, "  ", "the rubric"]})
    assert rec["depends_on"] == ["Lecture 3 AI supplement, draft 2", "the rubric"]
    assert qc.normalize_question_context({"question": "Go?", "depends_on": "one thing"})["depends_on"] == ["one thing"]
    d = _effort(tmp_path)
    state = tmp_path / "proto-state.json"
    state.write_text(json.dumps({str(d): {"question_context": {"question": "Approve the draft?", "response_text": "Approve the draft?",
                                                                "depends_on": ["Lecture 3 AI supplement, draft 2", "the rubric"]}}}), encoding="utf-8")
    from steward_cockpit import steward_engine as eng
    monkeypatch.setattr(eng, "STATE_FILE", state)
    html = card.card_part(PID, "next", str(d), "MBA Teaching AI")["html"]
    assert "Depends on</span>" in html and "Lecture 3 AI supplement, draft 2" in html and "the rubric" in html
