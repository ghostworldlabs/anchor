"""Every report is a link — in the plan outline and in the deliverables register (John, 2026-09-05).

The gate file for planning/reports-links-2026-09-05. Wave 1 extends it with the real proofs
(a finished run appends its register row with an Anchor route and the active step; a
/report or /artifact row is openable; a run: row carries its command; the two renderings read
the same rows). This seed is true today and stays true: the register's reader exists and the
containment rule stands for file rows.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402


def test_register_reader_exists_and_file_rows_stay_contained():
    td = tempfile.mkdtemp(prefix="reports-links-seed-")
    Path(td, "DELIVERABLES.md").write_text(
        "| What | Where | Date |\n|---|---|---|\n| outside | `../secret.md` | 2026-09-05 |\n", encoding="utf-8")
    got = campaign.read_deliverables(td)
    assert got["exists"] is True
    assert got["items"][0]["openable"] is False      # containment: outside the effort, never a link
