"""v1.2.3 share-prep gates.

Covers the three defects that reached the BUILT v1.2.2 bundle with every gate
green, plus the doctor/builder drift that share_sandbox G6a caught:

  1. the scrub-residue gate (the dangling-``AGENTS.md`` class),
  2. the emitted collaborator run contract (``AGENTS.md`` / ``AUTONOMOUS-MODE.md``),
  3. VERSION <-> pyproject stamp agreement, and
  4. doctor deriving its declared-optional set FROM the builder instead of
     keeping a second copy that drifts.

NOTE (scanner discipline): keep every literal token value in this file < 8
chars so the shipped copy can never trip the auth-token-value pattern in
distro's no-personal-data scan.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import distro
import doctor as doctor_mod

REPO = Path(__file__).resolve().parents[1]


# ── 1. the scrub-residue gate ───────────────────────────────────────────────

def _pair(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return [("vendor/bundled-skills/x/" + name, p)]


def test_scrub_residue_fires_on_the_v12_defect(tmp_path):
    """The exact string that shipped in 10 staged files must be caught."""
    hits = distro.scan_scrub_residue(_pair(
        tmp_path, "SKILL.md",
        "> **Tier definition:** canonical in `<path> Foundry\\AGENTS.md`.\n"))
    assert len(hits) == 1
    rel, cat, detail = hits[0]
    assert cat == "scrub-residue"
    assert "AGENTS.md" in detail


def test_scrub_residue_ignores_a_bare_placeholder(tmp_path):
    """A ``<path>`` token with NO file target is a deliberate placeholder.

    SOURCES.md uses it that way for provenance; flagging it would make the
    gate noisy enough to be switched off, which is how the refuted BROAD
    version of this gate would have died.
    """
    assert distro.scan_scrub_residue(_pair(
        tmp_path, "SOURCES.md",
        "| gandalf | <path> Foundry | `14ed949` |\n"
        "| crucible | <path> | `3ffa35a` |\n")) == []


def test_scrub_residue_does_not_cross_whitespace(tmp_path):
    """Regression: a scrubbed token inside JSON must not glue onto a later
    path across a space/quote boundary (a shell-regex false positive that a
    POSIX-ERE ``[^\\s]`` reading produced during the v1.2.3 investigation)."""
    assert distro.scan_scrub_residue(_pair(
        tmp_path, "gate-verdict.json",
        '{"note": "hardcoded trio-driver path (fil<path>": ["bin/analyze.mjs"]}\n'
    )) == []


def test_scrub_residue_skips_non_text(tmp_path):
    p = tmp_path / "mark.svg"
    p.write_text("<path> d=\"M0 0\"/>", encoding="utf-8")
    assert distro.scan_scrub_residue([("vendor/brand/mark.svg", p)]) == []


# ── 2. the emitted collaborator run contract ────────────────────────────────

def test_emit_share_docs_writes_both(tmp_path):
    out = distro.emit_share_docs(tmp_path, root=REPO)
    names = sorted(rel for rel, _p in out)
    assert names == ["AGENTS.md", "AUTONOMOUS-MODE.md"]
    for _rel, p in out:
        assert p.is_file() and p.stat().st_size > 0


def test_emitted_agents_md_carries_the_locked_status_table(tmp_path):
    """The whole point of shipping it: every vendored SKILL.md defers the
    10-minute cadence to ``AGENTS.md``, so the format must actually be in it."""
    distro.emit_share_docs(tmp_path, root=REPO)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    for row in ("Summary", "Effort", "Doing", "Status", "Tests",
                "Blocker", "Procs", "Journal", "ETA", "To do"):
        assert row in text, "status-table row missing: %s" % row
    assert "[HH:MM]" in text


def test_emit_share_docs_fails_closed_on_a_missing_source(tmp_path):
    """Silently shipping without it would re-create the dangling-pointer bug."""
    empty = tmp_path / "no-such-root"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        distro.emit_share_docs(tmp_path, root=empty)


def test_emitted_docs_are_themselves_residue_free(tmp_path):
    """The fix must not introduce the very defect it exists to prevent."""
    out = distro.emit_share_docs(tmp_path, root=REPO)
    assert distro.scan_scrub_residue(out) == []


# ── 3. version stamps agree ─────────────────────────────────────────────────

def test_version_and_pyproject_agree():
    """v1.2.2 shipped VERSION=1.2.2 against pyproject 1.1.3 — G3 could not
    catch it because the gate hard-coded the literal instead of the invariant."""
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "%s"' % version in pyproject


def test_g3_gate_is_not_pinned_to_a_release_literal():
    src = (REPO / "tools" / "share_sandbox.py").read_text(encoding="utf-8")
    head, _, tail = src.partition("G3 version alignment")
    window = head[-800:] + tail[:400]
    assert '== "1.1.3"' not in window


# ── 4. doctor derives from the builder (no second list) ─────────────────────

def test_doctor_optional_set_derives_from_the_builder():
    """share_sandbox G6a: a correctly-built package made doctor announce
    'This install is INCOMPLETE'. doctor kept its own copy of the
    declared-optional list and the builder's grew past it."""
    assert set(distro._OPTIONAL_FIRST_PARTY) <= set(doctor_mod.OPTIONAL_ABSENT)


def test_doctor_keeps_the_historical_fallback():
    assert {"update_transaction", "tools"} <= set(doctor_mod.OPTIONAL_ABSENT)


def test_doctor_reports_no_missing_modules_on_this_tree():
    assert doctor_mod.find_missing_modules() == {}
