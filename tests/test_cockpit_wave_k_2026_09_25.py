"""Wave K (2026-09-25): the steward's register rule asks the What cell to name the skill that made a work
product, so the cockpit's skill mark follows it (John: an edited chapter from Chekhov should carry its icon)."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_register_rule_asks_the_what_cell_to_name_the_skill():
    src = (REPO / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    rule = src.split("THE DELIVERABLES REGISTER")[1].split("PLAN DRIFT")[0]
    assert "names the skill that made the thing" in rule
    assert "Chekhov" in rule                     # the example is the skill John named
    assert "so its mark shows in the cockpit" in rule
