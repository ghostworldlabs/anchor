"""Cockpit workflow Wave E (2026-09-21) — John's cold read of the MBA Teaching AI cockpit.

His words: "The summaries are shorter now, for the context with each question, but they are too short.
Probably 2 to 3 sentences, use bullet formats. The list is better under status. Still confused with the
checks and flags on the plan. Maybe we can have a Red flag list (unfinished work) at the bottom of the plan."

- E1 the decision's context is two or three sentences, as bullets (the parser keeps up to three).
- E2 "Do now" sits under the lead line in the status pane; Current work and review keeps the files.
- E3 a red-flag list of unfinished work at the bottom of the plan; two marks on the tree (done, waiting on
  you) from structured facts only; colour carries no state; one legend line.
"""
import json

from steward_cockpit import question_context as qc


def test_the_stake_is_a_list_of_up_to_three_sentences_that_survives_a_reload():
    text = ("Too early. The guide gates the build path. John has been away for a week. The trial follows it. "
            "I recommend keeping this version. It passed the independent check. Keep it?")
    d = qc.parse_decision(text)
    assert d["stake"] == ["The guide gates the build path.", "John has been away for a week.", "The trial follows it."]
    assert d["recommendation"] == "I recommend keeping this version." and d["why"] == "It passed the independent check."
    saved = qc.save_question_context("Keep it?", text, asked_at=1)
    assert saved["stake"] == d["stake"]
    again = qc.normalize_question_context(json.loads(json.dumps(saved)))
    assert again["stake"] == d["stake"]                                       # no clip on reload
    legacy = qc.normalize_question_context({**saved, "stake": "One old sentence."})
    assert legacy["stake"] == ["One old sentence."]
    assert qc.parse_decision("Nothing decided. What now?")["stake"] == []
