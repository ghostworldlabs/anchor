"""Cockpit workflow Wave E (2026-09-21) — John's cold read of the MBA Teaching AI cockpit.

His words: "The summaries are shorter now, for the context with each question, but they are too short.
Probably 2 to 3 sentences, use bullet formats. The list is better under status. Still confused with the
checks and flags on the plan. Maybe we can have a Red flag list (unfinished work) at the bottom of the plan."

- E1 the decision's context is two or three sentences, as bullets (the parser keeps up to three).
- E2 "Do now" sits under the lead line in the status pane; Current work and review keeps the files.
- E3 a red-flag list of unfinished work at the bottom of the plan; two marks on the tree (done, waiting on
  you) from structured facts only; colour carries no state; one legend line.
"""
from pathlib import Path

from steward_cockpit import question_context as qc

JS = Path(__file__).resolve().parents[1].joinpath("steward_cockpit", "static", "shared.js").read_text(encoding="utf-8")
CSS = Path(__file__).resolve().parents[1].joinpath("steward_cockpit", "static", "shared.css").read_text(encoding="utf-8")


def test_the_stake_keeps_up_to_three_sentences():
    text = ("Too early. The guide gates the build path. John has been away for a week. The trial follows it. "
            "I recommend keeping this version. It passed the independent check. Keep it?")
    d = qc.parse_decision(text)
    assert d["stake"] == "The guide gates the build path. John has been away for a week. The trial follows it."
    assert d["recommendation"] == "I recommend keeping this version." and d["why"] == "It passed the independent check."


def test_lint_the_tile_is_bullets_with_room_for_two_or_three_sentences():
    body = JS.split("function fillQuestionPanel(host, q)")[1].split("function paintActionNeeded")[0]
    assert 'el("ul", "action-bullets")' in body and ".slice(0, 3).forEach(sentence => bullets.appendChild(el(\"li\", \"action-stake\"" in body
    assert "let budget = 900;" in body
    assert body.index('"Accept recommendation"') < body.index('el("details", "action-context")')


def test_lint_do_now_sits_under_the_lead_and_the_pin_block_keeps_the_files():
    status = JS.split("function renderStatus(stat)")[1].split("function stepDeliverables")[0]
    assert status.index("compact.appendChild(leadEl)") < status.index("paintDoNow(doNow)") < status.index("compact.appendChild(tab)")
    assert "function paintDoNow(host)" in JS
    assert 'paintDoNow(document.querySelector(".blk.status.latest [data-donow]"))' in JS      # refreshed on the deliverables cadence
    pin = JS.split("const p=el('div','navpin')")[1].split("target.appendChild(p);")[0]
    assert "'Do now')" not in pin and "Files awaiting you" in pin and "No files awaiting review." in pin   # no second Do now list


def test_lint_two_marks_from_structured_facts_and_the_red_flag_list():
    marks = JS.split("function stepWaitsOnJohn(st)")[1].split("function currentQuestion()")[0]
    assert "hasWaitingOn(st.waiting_on)" in marks and 'st.status === "waiting" || st.status === "blocked"' in marks   # a text wait counts only when the steward set the status
    assert "pending_steward_review" not in marks                                       # the steward's own wait is not John's
    assert 'return {glyph: "", cls: "todo"' in marks                                   # no third glyph
    assert "function notDoneList(map, stepRows)" in JS and '"Not done \\u00b7 " + open.length' in JS
    assert "list.appendChild(notDoneList(map, stepRows));" in JS                      # at the bottom of the plan
    assert "\\u2713 done \\u00b7 \\u2691 waiting on you" in JS                          # one legend line
    assert ".steps li.active { color: var(--text); }" in CSS and "font-weight: 600" not in CSS.split(".steps li.active")[1].split("\n")[0]
