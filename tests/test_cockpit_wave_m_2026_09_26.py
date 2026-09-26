"""Wave M (2026-09-26): the sweep rides the server's existing reconcile tick - one clock for sleeping stewards."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_reconcile_tick_runs_the_silence_sweep():
    src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
    body = src.split("def _reconcile_sessions_tick(")[1].split("_RECONCILE_TICK_LOCK = threading.Lock()")[0]
    assert "proceed_on_silence_sweep()" in body
