"""W1+W2+W3 gate — re-architecture 2026-07 (frozen plan: IMPLEMENTATION-PLAN.md).

**W1 — Ground-Truth Instrumentation (census · anchors · tripwire):**

* the **anchor-freshness gate**: every structural anchor (the
  ``_PROJECT_WINDOW_JS`` assignment, the ``generate_html`` def, the
  ``render_project_window_html`` def, and their sentinel comments) re-locates
  UNAMBIGUOUSLY from the current source, and a moved/renamed/duplicated
  anchor fails LOUDLY (``AnchorError``) — no line numbers in later waves;
* the **interpolation census**: classifies every ``{…}`` interpolation in the
  two render surfaces as data/flag/markup-emitting, asserts
  ``_PROJECT_WINDOW_JS`` has ZERO interpolations, derives the actual shrink
  number, and raises the C1 amendment NOW when ground truth forces it;
* the **write-site tripwire**: records every ``.anchor/`` write with its
  product write site (the mechanical mutation-of-record inventory) and, in
  enforce mode, fails any mutation not paired with a journal event — the
  journal path itself allowlisted;
* the **gate artifacts**: the checked-in census report + mutation-set
  inventory are refreshed by this very gate run (consumed by later waves).

**W2 — Regression Rails (Playwright flows · contract shim · consumer token
paths):**

* the **five permanent Playwright flows** (``tests/rearch_flows.py`` — the
  reusable assets the extraction gate and every later pillar re-run):
  terminal open+type via stub PTY · pending-paste flush · drag-to-group ·
  maximize/restore · v12 dock click;
* the **contract-versioning shim**: ``window.ANCHOR_BOOT`` carries the build
  id on both pages, every ``_postJson``/``apiCall`` declares it
  (``X-Anchor-Build``), a mismatch answers a STRUCTURED 409, and the stale
  client renders the 'reload required' banner (Playwright-proven);
* **consumer token paths**: the standard ``Authorization`` header is accepted
  on every token gate (POST middleware + the ``?token=`` GET surface, which
  keeps the query param only because WS/SSE demand it), and the checked-in
  ``CONSUMER-INVENTORY.md`` enumerates every open-route consumer with its
  verified token path.

**W3 — Spikes, Pillar Flags & Process Rails:**

* the **ConPTY-across-processes spike** (``tools/conpty_spike.py``): the
  owner-side-PTY + loopback-IPC harness runs its deterministic stub leg here
  and records the verdict against the PRE-WRITTEN acceptance questions
  (latency bound · re-attach behavior · complexity budget) into the
  checked-in ``SPIKE-CONPTY-VERDICT.{json,md}`` (the real-ConPTY leg is
  opt-in via ``ANCHOR_SPIKE_REAL_CONPTY=1``, recorded honestly either way);
* the **cookie-through-WS spike** (``tools/cookie_ws_spike.py``): a real
  browser (Playwright) proves whether the auth cookie survives the WS
  upgrade — recorded into ``SPIKE-COOKIE-WS-VERDICT.{json,md}`` with the
  iPhone-PWA leg as an honest live-manual runbook cell and ``?token=``
  declared as the WS fallback;
* the **pre-restart drain** (``tools/pre_restart_drain.py``): close_session
  park + capture_session_docs + the warm-resume seed for every live PTY,
  proven against a stub PTY session (park → docs in main → cached summary →
  warm ``_build_continue_seed``), with the bounded summary generation unable
  to block a restart;
* the **four pillar off-switch flags** (``pillar_flags.py``): journal ·
  auth · supervisor · frontend, the named hybrid-state matrix + cross-pillar
  DAG (``PILLAR-DAG.md``, gate-refreshed), and the healthcheck assertion
  (``check_pillar_state``) that the CURRENT configuration is a NAMED state —
  loud failure on an unnamed/invalid one;
* the **process rails**: the three Butler user stories (the binding W12
  envelope target), the codified rituals (``PROCESS-RAILS.md``), and the
  Appendix-A traceability ledger (ideas 1–52 + mitigations 1–20, Mitigation
  9 explicitly reconciled) — the ledger diffed mechanically against the
  frozen plan's own citation lines;
* the **no-leak rail** (W3 amendment, 2026-07-03, human-authorized): every
  process the spike/tests spawn (claude.exe, PTY children) is reaped before
  the test returns — a session-end census sentinel (ONE batched CIM call)
  fails the run on any surviving spawned process, with the classifier
  proven on synthetic tables (``TestW3NoLeakRail``).
"""

import ast
import builtins
import importlib
import io
import json
import os
import re
import subprocess
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import pillar_flags as pf
from tools import anchors as anchors_mod
from tools import conpty_spike as cs
from tools import cookie_ws_spike as cw
from tools import interpolation_census as census_mod
from tools import pre_restart_drain as drain_mod
from tools import write_tripwire as wt
from tools.anchors import AnchorError, locate_anchors
from tools.interpolation_census import (
    CLASS_DATA,
    CLASS_FLAG,
    CLASS_MARKUP,
    CLASSES,
    CensusError,
    classify_expression,
    run_census,
    write_report,
)

REPO_ROOT = anchors_mod.REPO_ROOT
ANCHOR_GUI = REPO_ROOT / "anchor_gui.py"
ARTIFACT_DIR = census_mod.DEFAULT_ARTIFACT_DIR


# ──────────────────────────────────────────────────────────────────────────
# synthetic-source builder (for the loud-failure paths)
# ──────────────────────────────────────────────────────────────────────────

def _synthetic_source(js_sentinel="# ANCHOR[rearch]: PROJECT_WINDOW_JS",
                      js_assign='_PROJECT_WINDOW_JS = r"""\nvar x = 1;\n"""',
                      extra=""):
    return textwrap.dedent("""\
    {js_sentinel}
    {js_assign}


    # ANCHOR[rearch]: GENERATE_HTML
    def generate_html(projects, tasks, inbox):
        n = len(projects)
        return f"<html>{{n}}</html>"


    # ANCHOR[rearch]: RENDER_PROJECT_WINDOW
    def render_project_window_html(project_id):
        return f"<html>{{project_id}}</html>"
    {extra}
    """).format(js_sentinel=js_sentinel, js_assign=js_assign, extra=extra)


# ──────────────────────────────────────────────────────────────────────────
# 1) Anchor-freshness gate
# ──────────────────────────────────────────────────────────────────────────

class TestAnchorFreshnessGate:
    def test_real_source_all_anchors_relocate_unambiguously(self):
        res = locate_anchors(path=ANCHOR_GUI)
        # all three structures + all three sentinels, each exactly once
        assert set(res["structural"]) == set(anchors_mod.STRUCTURAL_KEYS)
        assert set(res["sentinels"]) >= set(anchors_mod.EXPECTED_SENTINELS)
        for name, key in anchors_mod.EXPECTED_SENTINELS.items():
            s_line = res["sentinels"][name]
            n_line = res["structural"][key]["lineno"]
            assert 0 < n_line - s_line <= anchors_mod.SENTINEL_ADJACENCY, (
                f"sentinel {name} not adjacent to {key}")
        # the JS assignment is the multi-thousand-line blob, not a stub
        js = res["structural"]["project_window_js_assign"]
        assert js["end_lineno"] - js["lineno"] > 1000

    def test_synthetic_valid_source_passes(self):
        res = locate_anchors(source=_synthetic_source())
        assert res["structural"]["generate_html_def"]["lineno"] > 0

    def test_duplicated_sentinel_fails_loudly(self):
        src = _synthetic_source(
            extra="\n\n# ANCHOR[rearch]: GENERATE_HTML\nX = 1\n")
        with pytest.raises(AnchorError, match="DUPLICATED"):
            locate_anchors(source=src)

    def test_missing_structure_fails_loudly(self):
        src = _synthetic_source(
            js_assign='_PROJECT_WINDOW_JS_RENAMED = r"""\nvar x = 1;\n"""')
        with pytest.raises(AnchorError, match="NOT FOUND"):
            locate_anchors(source=src)

    def test_missing_sentinel_fails_loudly(self):
        src = _synthetic_source(js_sentinel="# no sentinel here")
        with pytest.raises(AnchorError,
                           match="PROJECT_WINDOW_JS.*NOT\\s+FOUND"):
            locate_anchors(source=src)

    def test_ambiguous_structure_fails_loudly(self):
        # a second module-level generate_html def (legal Python, stale anchor)
        src = _synthetic_source(
            extra="\n\ndef generate_html(a, b, c):\n    return ''\n")
        with pytest.raises(AnchorError, match="AMBIGUOUS"):
            locate_anchors(source=src)

    def test_drifted_sentinel_fails_loudly(self):
        pad = "\n".join(f"PAD_{i} = {i}"
                        for i in range(anchors_mod.SENTINEL_ADJACENCY + 2))
        src = _synthetic_source(
            js_assign=pad + '\n_PROJECT_WINDOW_JS = r"""\nvar x = 1;\n"""')
        with pytest.raises(AnchorError, match="DRIFTED"):
            locate_anchors(source=src)


# ──────────────────────────────────────────────────────────────────────────
# 2) Interpolation census — classification rules (mechanical, syntactic)
# ──────────────────────────────────────────────────────────────────────────

def _classify_fstring(expr_src):
    """Classify the single TOP-LEVEL interpolation of an f-string source."""
    tree = ast.parse(expr_src, mode="eval")
    joined = tree.body
    assert isinstance(joined, ast.JoinedStr)
    fvs = [v for v in joined.values if isinstance(v, ast.FormattedValue)]
    assert len(fvs) == 1, "test helper expects exactly one interpolation"
    return classify_expression(fvs[0].value)


class TestCensusClassification:
    def test_markup_literal_angle_bracket(self):
        cls, rule = _classify_fstring(
            'f"{f\'<span>{x}</span>\' if x else \'\'}"')
        assert cls == CLASS_MARKUP and rule == "literal-contains-<"

    def test_markup_renderer_call(self):
        cls, rule = _classify_fstring('f"{render_cost_rollup_html(p, f)}"')
        assert cls == CLASS_MARKUP and "call-to-renderer" in rule

    def test_markup_suffix_call(self):
        cls, rule = _classify_fstring('f"{cache_bust_script()}"')
        assert cls == CLASS_MARKUP

    def test_markup_named_variable(self):
        cls, rule = _classify_fstring('f"{health_banner_html}"')
        assert cls == CLASS_MARKUP and "markup-named-var" in rule

    def test_flag_ternary(self):
        cls, rule = _classify_fstring(
            "f\"{'checked' if t else ''}\"")
        assert cls == CLASS_FLAG and rule == "ternary-selection"

    def test_flag_named_variable(self):
        cls, rule = _classify_fstring('f"{auth_required_js}"')
        assert cls == CLASS_FLAG and "flag-named-var" in rule

    def test_data_default(self):
        for src in ('f"{esc(t)}"', 'f"{count}"', 'f"{cost:.4f}"',
                    'f"{html_lib.escape(name)}"'):
            cls, rule = _classify_fstring(src)
            assert cls == CLASS_DATA, src

    def test_precedence_markup_beats_flag(self):
        # a ternary whose arms carry markup is markup-emitting, never a flag
        cls, _ = _classify_fstring("f\"{'<b>on</b>' if x else ''}\"")
        assert cls == CLASS_MARKUP


# ──────────────────────────────────────────────────────────────────────────
# 3) Interpolation census — the real anchor_gui.py
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_census():
    return run_census(path=ANCHOR_GUI)


class TestCensusRealSource:
    def test_project_window_js_has_zero_interpolations(self, real_census):
        assert real_census["project_window_js"]["interpolations"] == 0
        # and it is the real multi-thousand-line blob
        assert real_census["project_window_js"]["lines"] > 1000

    def test_every_interpolation_is_classified(self, real_census):
        fns = real_census["functions"]
        assert set(fns) == {"generate_html", "render_project_window_html"}
        for name, f in fns.items():
            assert f["total"] == len(f["interpolations"]) > 0, name
            assert f["total"] == sum(f["counts"].values()), name
            for r in f["interpolations"]:
                assert r["class"] in CLASSES
                assert r["rule"]
        t = real_census["totals"]
        assert t["all"] == sum(
            f["total"] for f in fns.values()) == (
            t[CLASS_DATA] + t[CLASS_FLAG] + t[CLASS_MARKUP])

    def test_shrink_number_is_derived_from_located_spans(self, real_census):
        spans = real_census["blob_spans"]
        derived = sum(
            e - s + 1 for blobs in spans.values() for s, e in blobs)
        assert real_census["derived_shrink_lines"] == derived
        # _PROJECT_WINDOW_JS is always one whole extractable blob
        assert spans["_PROJECT_WINDOW_JS"] == [list(
            map(int, real_census["project_window_js"]["span"]))]

    def test_amendment_decision_is_consistent(self, real_census):
        required = real_census["amendment_required"]
        reasons = real_census["amendment_reasons"]
        assert required == bool(reasons)
        # ground truth: below-bar shrink or above-threshold markup ⇒ raised
        over_markup = (real_census["totals"][CLASS_MARKUP]
                       > real_census["markup_emitting_threshold"])
        under_bar = (real_census["derived_shrink_lines"]
                     < real_census["shrink_bar_lines"])
        assert required == (over_markup or under_bar)

    def test_census_refuses_stale_anchors(self):
        src = _synthetic_source(js_sentinel="# gone")
        with pytest.raises(AnchorError):
            run_census(source=src)

    def test_census_fails_loudly_on_fstring_pwjs(self):
        src = _synthetic_source(
            js_assign='_PROJECT_WINDOW_JS = f"""\nvar x = {x};\n"""')
        with pytest.raises(CensusError, match="f-string"):
            run_census(source=src)


class TestCensusGateArtifacts:
    """The checked-in census report is REFRESHED by this gate run."""

    def test_write_report_refreshes_checked_in_artifacts(self, real_census):
        written = write_report(real_census, out_dir=ARTIFACT_DIR)
        json_path = ARTIFACT_DIR / census_mod.REPORT_JSON_NAME
        md_path = ARTIFACT_DIR / census_mod.REPORT_MD_NAME
        amend_path = ARTIFACT_DIR / census_mod.AMENDMENT_NAME
        assert json_path in written and json_path.exists()
        assert md_path in written and md_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["derived_shrink_lines"] == (
            real_census["derived_shrink_lines"])
        assert payload["totals"]["all"] == real_census["totals"]["all"]
        # amendment artifact exists IFF the census requires it (never a lie)
        assert amend_path.exists() == real_census["amendment_required"]
        md = md_path.read_text(encoding="utf-8")
        assert "Derived shrink number" in md
        assert str(real_census["derived_shrink_lines"]) in md


# ──────────────────────────────────────────────────────────────────────────
# 4) Write-site tripwire — mechanics
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tripwire_guard():
    """Isolate + clean up the tripwire for a test, whatever happens.

    When a SESSION-WIDE tripwire is already active (the orchestrator's
    dedicated ``ANCHOR_WRITE_TRIPWIRE=inventory`` full-suite inventory run),
    these isolated mechanics tests skip: they install/uninstall the tripwire
    themselves and assert exact inventory contents, which would both tear
    down and pollute the session-wide recording. They are proven by the
    normal (env-off) gate run; the inventory run is a coverage run.
    """
    if wt.is_installed() or wt.env_requested_mode(os.environ) is not None:
        pytest.skip("session-wide write-site tripwire active "
                    "(inventory run) — isolated tripwire tests are "
                    "proven in the default gate run")
    yield
    wt.uninstall()
    wt.clear_inventory()


def _store_dir(tmp_path, pid="a1b2c3d4e5f6a7b8"):
    d = tmp_path / ".anchor" / "projects" / pid / "planning"
    d.mkdir(parents=True)
    return d


class TestTripwireInventory:
    def test_records_anchor_writes_with_normalized_store(
            self, tmp_path, tripwire_guard):
        with wt.active(mode=wt.MODE_INVENTORY):
            d = _store_dir(tmp_path)
            tmp = d / "index.json.tmp"
            tmp.write_text("{}", encoding="utf-8")      # Path → io.open
            os.replace(str(tmp), str(d / "index.json"))  # atomic idiom
            with open(d / "log.txt", "a", encoding="utf-8") as fh:
                fh.write("x")                            # builtins.open
            os.remove(d / "log.txt")
        inv = wt.inventory()
        stores = {(r["store"], r["op"]) for r in inv}
        norm = ".anchor/projects/<id>/planning"
        assert (f"{norm}/index.json", "write") in stores
        assert (f"{norm}/index.json", "replace") in stores
        assert (f"{norm}/log.txt", "write") in stores
        assert (f"{norm}/log.txt", "remove") in stores
        # site resolution: this write happened in test code — honest fallback
        for r in inv:
            assert r["site"].startswith("tests/"), r
            assert r["count"] >= 1

    def test_non_anchor_writes_are_ignored(self, tmp_path, tripwire_guard):
        with wt.active(mode=wt.MODE_INVENTORY):
            (tmp_path / "plain.txt").write_text("x", encoding="utf-8")
        assert wt.inventory() == []

    def test_reads_are_never_recorded(self, tmp_path, tripwire_guard):
        d = _store_dir(tmp_path)
        target = d / "index.json"
        target.write_text("{}", encoding="utf-8")
        with wt.active(mode=wt.MODE_INVENTORY):
            assert target.read_text(encoding="utf-8") == "{}"
        assert wt.inventory() == []

    def test_uninstall_restores_originals(self, tripwire_guard):
        orig_open = builtins.open
        orig_io_open = io.open
        orig_replace = os.replace
        with wt.active(mode=wt.MODE_INVENTORY):
            assert getattr(builtins.open, "_anchor_tripwire", False)
            assert getattr(io.open, "_anchor_tripwire", False)
            assert getattr(os.replace, "_anchor_tripwire", False)
        assert builtins.open is orig_open
        assert io.open is orig_io_open
        assert os.replace is orig_replace
        assert not wt.is_installed()

    def test_store_path_normalization(self):
        cs = wt.classify_store_path
        assert cs("/x/.anchor/sessions.json.tmp") == ".anchor/sessions.json"
        assert cs("/x/.anchor/projects/aaaabbbbccccdddd/grass/idea-abc12/"
                  "card.json") == (
            ".anchor/projects/<id>/grass/idea-<id>/card.json")
        assert cs("C:\\d\\.anchor\\projects\\"
                  "0f3ab9d2-1111-2222-3333-444455556666\\index.json") == (
            ".anchor/projects/<id>/index.json")
        assert cs("/x/.anchor/runs/12345/out.log") == (
            ".anchor/runs/<n>/out.log")
        assert cs("/x/no-store/file.json") is None

    def test_journal_path_detection(self):
        assert wt.is_journal_path("/x/.anchor/projects/ab12cd34/journal/"
                                  "2026-07.jsonl")
        assert wt.is_journal_path("/x/.anchor/projects/ab12cd34/"
                                  "journal.jsonl")
        assert wt.is_journal_path("/x/.anchor/projects/ab12cd34/"
                                  "journal.jsonl.tmp")
        assert not wt.is_journal_path("/x/.anchor/projects/ab12cd34/"
                                      "index.json")

    def test_env_seam_mode_mapping(self):
        assert wt.env_requested_mode({}) is None
        assert wt.env_requested_mode(
            {"ANCHOR_WRITE_TRIPWIRE": ""}) is None
        assert wt.env_requested_mode(
            {"ANCHOR_WRITE_TRIPWIRE": "1"}) == wt.MODE_INVENTORY
        assert wt.env_requested_mode(
            {"ANCHOR_WRITE_TRIPWIRE": "inventory"}) == wt.MODE_INVENTORY
        assert wt.env_requested_mode(
            {"ANCHOR_WRITE_TRIPWIRE": "ENFORCE"}) == wt.MODE_ENFORCE


class TestTripwireEnforce:
    """The future permanent C3 completeness gate — contract proven NOW."""

    def test_unpaired_mutation_fails(self, tmp_path, tripwire_guard):
        d = _store_dir(tmp_path)
        with wt.active(mode=wt.MODE_ENFORCE):
            with pytest.raises(wt.TripwireViolation,
                               match="unjournaled mutation"):
                (d / "index.json").write_text("{}", encoding="utf-8")
        # and the blocked write never happened
        assert not (d / "index.json").exists()

    def test_journal_paired_mutation_passes(self, tmp_path, tripwire_guard):
        d = _store_dir(tmp_path)
        with wt.active(mode=wt.MODE_ENFORCE):
            with wt.journal_event():
                (d / "index.json").write_text("{}", encoding="utf-8")
        assert (d / "index.json").exists()

    def test_journal_path_itself_is_allowlisted(
            self, tmp_path, tripwire_guard):
        d = _store_dir(tmp_path)
        with wt.active(mode=wt.MODE_ENFORCE):
            # journal appends need no pairing — the journal IS the pairing
            (d / "journal.jsonl").write_text("{}", encoding="utf-8")
            jdir = d / "journal"
            with wt.journal_event():
                jdir.mkdir()
            (jdir / "2026-07.jsonl").write_text("{}", encoding="utf-8")
        assert (d / "journal.jsonl").exists()

    def test_mark_clear_imperative_pairing(self, tmp_path, tripwire_guard):
        d = _store_dir(tmp_path)
        with wt.active(mode=wt.MODE_ENFORCE):
            wt.mark_journal_event()
            try:
                (d / "index.json").write_text("{}", encoding="utf-8")
            finally:
                wt.clear_journal_event()
            with pytest.raises(wt.TripwireViolation):
                (d / "index.json").write_text("{}", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────
# 5) Mutation-of-record inventory — real product write sites + the artifact
# ──────────────────────────────────────────────────────────────────────────

class TestMutationInventoryArtifact:
    def test_product_write_sites_are_captured_and_artifact_refreshed(
            self, tmp_path, monkeypatch, tripwire_guard):
        import effort_history
        import session_registry

        monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
        folder = tmp_path / "proj"
        folder.mkdir()

        with wt.active(mode=wt.MODE_INVENTORY):
            rec = session_registry.register_session(
                "pid-w1", "research", label="w1 tripwire walk")
            session_registry.update_session(
                rec["session_id"], status=session_registry.STATUS_DONE)
            effort_history.add_idea(folder, "pid-w1", "w1 idea",
                                    notes="tripwire")
            inv = wt.inventory()
            # the registry's atomic save is attributed to PRODUCT code
            reg_sites = {r["site"] for r in inv
                         if r["store"] == ".anchor/sessions.json"}
            assert "session_registry.py:_save_sessions" in reg_sites
            reg_ops = {r["op"] for r in inv
                       if r["store"] == ".anchor/sessions.json"}
            assert {"write", "replace"} <= reg_ops
            # the grass-idea store write is attributed to effort_history
            eh_entries = [r for r in inv
                          if r["site"].startswith("effort_history.py:")]
            assert eh_entries, (
                f"no effort_history write site captured: {inv}")
            for r in eh_entries:
                assert r["store"].startswith(".anchor/projects/"), r

            # refresh the checked-in gate artifact (merge-accumulating, so
            # the full-suite + healthcheck tripwire runs fold into it too)
            path = wt.write_inventory(
                ARTIFACT_DIR / "MUTATION-INVENTORY.json", merge=True)

        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload["entries"]
        assert entries and all(
            set(e) == {"store", "op", "site", "count"} for e in entries)
        assert any(e["site"] == "session_registry.py:_save_sessions"
                   for e in entries)
        assert payload["journal_allowlist"]["filenames"] == ["journal.jsonl"]
        # deterministically sorted (stable, diffable, checked in)
        assert entries == sorted(
            entries, key=lambda r: (r["store"], r["site"], r["op"]))

    def test_write_inventory_merge_accumulates_counts(
            self, tmp_path, tripwire_guard):
        with wt.active(mode=wt.MODE_INVENTORY):
            d = _store_dir(tmp_path)
            (d / "index.json").write_text("{}", encoding="utf-8")
            out = tmp_path / "inv.json"
            wt.write_inventory(out, merge=True)
            first = json.loads(out.read_text(encoding="utf-8"))["entries"]
            wt.write_inventory(out, merge=True)
            second = json.loads(out.read_text(encoding="utf-8"))["entries"]
        assert len(first) == len(second) == 1
        assert second[0]["count"] == 2 * first[0]["count"]


# ══════════════════════════════════════════════════════════════════════════
# W2 — Regression Rails (Playwright flows · contract shim · consumer tokens)
# ══════════════════════════════════════════════════════════════════════════

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture
def w2_env(tmp_path, monkeypatch):
    """Hermetic W2 server env: tmp data dir, stub PTY, fake runner, no token
    (individual tests flip ANCHOR_TOKEN on via monkeypatch — the auth helpers
    read the env per call)."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt-base"))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "gate_adapter", "handoff",
                "terminal_session", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield {"gui": gui, "tmp": tmp_path}
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.fixture
def w2_server(w2_env):
    gui = w2_env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield w2_env, f"http://127.0.0.1:{port}"
    finally:
        time.sleep(0.1)
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def _http(base, path, method="GET", payload=None, headers=None, timeout=6.0):
    """Tiny urllib helper → (status, parsed-or-raw body)."""
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers=hdrs,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        status = e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


_BOOT_RE = re.compile(r"window\.ANCHOR_BOOT = (\{[^;]*\});")


def _extract_boot(html):
    m = _BOOT_RE.search(html)
    assert m, "window.ANCHOR_BOOT not found in the page"
    return json.loads(m.group(1))


def _mk_w2_project(w2_env, name, git=True):
    from tests import rearch_flows as flows
    folder = w2_env["tmp"] / name
    if git:
        flows.git_init(folder)
    else:
        folder.mkdir(parents=True, exist_ok=True)
    return flows.mkproject(folder, name)["id"], folder


# ──────────────────────────────────────────────────────────────────────────
# 6) W2 — contract-versioning shim (ANCHOR_BOOT · X-Anchor-Build · 409)
# ──────────────────────────────────────────────────────────────────────────

class TestW2ContractShim:
    def test_anchor_boot_on_home_dashboard(self, w2_server):
        w2_env, base = w2_server
        gui = w2_env["gui"]
        status, html = _http(base, "/")
        assert status == 200
        boot = _extract_boot(html)
        assert boot["schema_ver"] == gui.ANCHOR_BOOT_SCHEMA_VER == 1
        assert boot["build_id"] == gui.BUILD_ID
        assert boot["auth_required"] is False

    def test_anchor_boot_on_project_window(self, w2_server):
        w2_env, base = w2_server
        gui = w2_env["gui"]
        pid, _ = _mk_w2_project(w2_env, "BootPW", git=False)
        status, html = _http(base, f"/project/{pid}")
        assert status == 200
        boot = _extract_boot(html)
        assert boot["build_id"] == gui.BUILD_ID
        assert boot["schema_ver"] == 1

    def test_boot_reflects_auth_flag(self, w2_server, monkeypatch):
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
        _, html = _http(base, "/")
        boot = _extract_boot(html)
        assert boot["auth_required"] is True
        # presence only — the token VALUE is never embedded in served HTML.
        assert "s3cret" not in html

    def test_postjson_senders_declare_build_and_render_banner(self, w2_env):
        """Every _postJson sender carries X-Anchor-Build, and both pages ship
        the 409 → 'reload required' banner path (the client half of the
        shim, present in the LAST pre-migration release by design)."""
        gui = w2_env["gui"]
        pw_js = gui._PROJECT_WINDOW_JS
        assert "X-Anchor-Build" in pw_js
        assert "_showReloadBanner" in pw_js
        assert "anchorReloadBanner" in pw_js
        assert "build-mismatch" in pw_js
        html = gui.generate_html(*gui.gather_all())
        assert "X-Anchor-Build" in html          # apiCall's _doFetch
        assert "_showReloadBanner" in html
        assert "anchorReloadBanner" in html
        assert "build-mismatch" in html
        # brace discipline: the f-string page leaked no doubled braces.
        assert "{{" not in html and "}}" not in html

    def test_build_mismatch_answers_structured_409(self, w2_server):
        w2_env, base = w2_server
        gui = w2_env["gui"]
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"X-Anchor-Build": "stale-build-123"})
        assert status == 409
        assert body["ok"] is False
        assert body["error"] == gui.BUILD_MISMATCH_ERROR == "build-mismatch"
        assert body["server_build"] == gui.BUILD_ID
        assert body["client_build"] == "stale-build-123"
        assert body["action"] == "reload"

    def test_matching_or_absent_build_never_blocked(self, w2_server):
        """The current client (matching build) and every build-less consumer
        (healthcheck, CLI, curl) pass the shim untouched."""
        w2_env, base = w2_server
        gui = w2_env["gui"]
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"X-Anchor-Build": gui.BUILD_ID})
        assert status == 200 and "ok" in body
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"})
        assert status == 200 and "ok" in body

    def test_mismatch_beats_auth_prompt(self, w2_server, monkeypatch):
        """A stale tab learns 'reload required' (409) rather than being asked
        to re-enter a token (401) — the shim is checked first by design."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"X-Anchor-Build": "stale-build-123"})
        assert status == 409 and body["error"] == "build-mismatch"


# ──────────────────────────────────────────────────────────────────────────
# 7) W2 — Authorization-header token paths (representative routes)
# ──────────────────────────────────────────────────────────────────────────

class TestW2AuthorizationHeader:
    def test_token_from_authorization_parsing(self):
        import paths
        f = paths.token_from_authorization
        assert f("Bearer abc123") == "abc123"
        assert f("bearer abc123") == "abc123"      # scheme case-insensitive
        assert f("BEARER  abc123 ") == "abc123"
        assert f("abc123") == "abc123"             # bare token convenience
        assert f("") is None
        assert f("   ") is None
        assert f(None) is None
        assert f("Bearer ") is None                # scheme with no token

    def test_post_accepts_authorization_bearer(self, w2_server, monkeypatch):
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
        # no credentials → 401
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"})
        assert status == 401 and body["error"] == "unauthorized"
        # Authorization: Bearer <token> → accepted
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"Authorization": "Bearer s3cret"})
        assert status == 200 and "ok" in body
        # wrong bearer → 401
        status, _ = _http(base, "/api/done", method="POST",
                          payload={"text": "__w2_probe__"},
                          headers={"Authorization": "Bearer nope"})
        assert status == 401
        # the legacy browser path (X-Anchor-Token) still works unchanged
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"X-Anchor-Token": "s3cret"})
        assert status == 200 and "ok" in body

    def test_gated_get_accepts_authorization(self, w2_server, monkeypatch):
        """A representative token-gated read GET (the healthcheck-walk class of
        consumer): Authorization passes the gate (the 400 for missing params
        PROVES auth ran first and passed); tokenless is 401."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
        path = "/api/rnd/session_doc_roles"
        status, body = _http(base, path)
        assert status == 401 and body["error"] == "unauthorized"
        status, _ = _http(base, path,
                          headers={"Authorization": "Bearer s3cret"})
        assert status == 400          # auth passed; params missing
        # ?token= keeps working (browser reads keep it until the W9 cutover)
        status, _ = _http(base, path + "?token=s3cret")
        assert status == 400

    def test_sse_transport_retains_query_token(self, w2_server, monkeypatch):
        """WS/SSE are the ONLY transports that still NEED ?token= (browsers
        can't set headers there) — and the header path works on them too."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
        path = "/api/rnd/term_stream2"
        status, body = _http(base, path)
        assert status == 401 and body["error"] == "unauthorized"
        status, _ = _http(base, path + "?token=s3cret")
        assert status == 400          # auth passed; session missing
        status, _ = _http(base, path,
                          headers={"Authorization": "Bearer s3cret"})
        assert status == 400

    def test_healthcheck_post_helper_presents_authorization(
            self, w2_server, monkeypatch):
        """The healthcheck endpoint walk — the canonical non-browser consumer
        — really presents the token via the Authorization header (functional:
        its own _post succeeds against a token-requiring server)."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
        import anchor_healthcheck as hc
        data = hc._post(base, "/api/done", {"text": "__w2_probe__"})
        assert "ok" in data           # 200 through the Bearer path
        # and the helper's source sends Authorization, not X-Anchor-Token
        import inspect
        src = inspect.getsource(hc._post)
        assert "Authorization" in src and "Bearer" in src
        assert "X-Anchor-Token" not in src


# ──────────────────────────────────────────────────────────────────────────
# 8) W2 — consumer-enumeration inventory (checked-in gate artifact)
# ──────────────────────────────────────────────────────────────────────────

class TestW2ConsumerInventory:
    INVENTORY = ARTIFACT_DIR / "CONSUMER-INVENTORY.md"

    def test_inventory_enumerates_every_consumer_class(self):
        assert self.INVENTORY.exists(), (
            "the W2 consumer-enumeration inventory is a checked-in artifact")
        text = self.INVENTORY.read_text(encoding="utf-8")
        # every consumer class the frozen plan names must be enumerated:
        for required in (
                "anchor_healthcheck.py",          # healthcheck endpoint walk
                "fix_anchor_stale.ps1",           # personal script
                "setup_service_as_john.ps1",      # personal script
                "AnchorDashboard.vbs",            # launchers
                "launch_anchor.pyw",              # launchers
                "Anchor Health Check",            # scheduled task
                "Anchor Server",                  # scheduled task (disabled)
                "anchor.py",                      # repo code (CLI, no HTTP)
                "_PROJECT_WINDOW_JS",             # browser client (project)
                "generate_html",                  # browser client (home)
                "Authorization",                  # the token path column
        ):
            assert required in text, f"inventory missing consumer: {required}"
        # ?token= is documented as WS/SSE-only going forward
        assert "WS/SSE" in text

    def test_inventory_claims_are_real_in_consumer_source(self):
        """The two consumers the inventory claims were given a header token
        path in W2 really carry it in their source."""
        hc_src = (REPO_ROOT / "anchor_healthcheck.py").read_text(
            encoding="utf-8")
        assert 'headers["Authorization"] = f"Bearer {token}"' in hc_src
        ps_src = (REPO_ROOT / "fix_anchor_stale.ps1").read_text(
            encoding="utf-8")
        assert "Authorization" in ps_src and "ANCHOR_TOKEN" in ps_src


# ──────────────────────────────────────────────────────────────────────────
# 9) W2 — the five permanent Playwright flows (tests/rearch_flows.py)
# ──────────────────────────────────────────────────────────────────────────

_needs_git = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


def _browser_page(p, viewport=None):
    b = p.chromium.launch()
    pg = b.new_page(**({"viewport": viewport} if viewport else {}))
    errors = []
    pg.on("console",
          lambda m: errors.append(m.text) if m.type == "error" else None)
    return b, pg, errors


class TestW2PlaywrightFlows:
    @_needs_git
    def test_flow_terminal_open_and_type(self, w2_server):
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        from tests import rearch_flows as flows
        w2_env, base = w2_server
        pid, _ = _mk_w2_project(w2_env, "FlowTerm")
        rec = flows.start_live_session(pid, "research")
        sid = rec["session_id"]
        try:
            with sync_playwright() as p:
                b, pg, errors = _browser_page(p)
                flows.flow_terminal_open_and_type(pg, base, pid, sid)
                assert not errors, f"JS console errors: {errors}"
                b.close()
        finally:
            flows.kill_quietly(sid)

    @_needs_git
    def test_flow_pending_paste_flush(self, w2_server):
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        from tests import rearch_flows as flows
        import session_registry as reg
        w2_env, base = w2_server
        pid, folder = _mk_w2_project(w2_env, "FlowPaste")
        src_sid, doc_rel = flows.research_session_with_doc(pid, folder)
        new_sid = None
        try:
            with sync_playwright() as p:
                b, pg, errors = _browser_page(p)
                new_sid = flows.flow_pending_paste_flush(pg, base, pid,
                                                         doc_rel)
                assert not errors, f"JS console errors: {errors}"
                b.close()
            # backend truth: the planning session links to its research source
            plan = [r for r in reg.list_sessions(project_id=pid)
                    if r.get("lane") in ("plan", "planning")]
            assert any(r.get("parent_session_id") == src_sid for r in plan)
        finally:
            for r in reg.list_sessions(project_id=pid):
                flows.kill_quietly(r["session_id"])

    def test_flow_drag_to_group(self, w2_server):
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        from tests import rearch_flows as flows
        w2_env, base = w2_server
        pid, folder = _mk_w2_project(w2_env, "FlowDrag", git=False)
        with sync_playwright() as p:
            b, pg, _errors = _browser_page(p)
            flows.flow_drag_to_group(pg, base, pid, group="Research")
            b.close()
        import rnd_registry as rnd
        assert rnd.get_project(pid)["group"] == "Research"
        assert Path(rnd.get_project(pid)["folder_path"]).resolve() == \
            folder.resolve()

    @_needs_git
    def test_flow_maximize_restore(self, w2_server):
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        from tests import rearch_flows as flows
        w2_env, base = w2_server
        pid, _ = _mk_w2_project(w2_env, "FlowMax")
        rec = flows.start_live_session(pid, "research")
        sid = rec["session_id"]
        try:
            with sync_playwright() as p:
                b, pg, errors = _browser_page(
                    p, viewport={"width": 1280, "height": 900})
                pg.on("dialog", lambda d: d.accept())
                flows.flow_maximize_restore(pg, base, pid, sid)
                assert not errors, f"JS console errors: {errors}"
                b.close()
        finally:
            flows.kill_quietly(sid)

    @_needs_git
    def test_flow_dock_click(self, w2_server):
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        from tests import rearch_flows as flows
        w2_env, base = w2_server
        pid, _ = _mk_w2_project(w2_env, "FlowDock")
        rec = flows.start_live_session(pid, "research", effort_managed=True)
        sid = rec["session_id"]
        try:
            with sync_playwright() as p:
                b, pg, errors = _browser_page(p)
                flows.flow_dock_click(pg, base, pid, sid)
                assert not errors, f"JS console errors: {errors}"
                b.close()
        finally:
            flows.kill_quietly(sid)

    def test_stale_tab_renders_reload_banner(self, w2_server):
        """The W2 acceptance GWT, end to end in a real browser: a tab whose
        ANCHOR_BOOT build id is stale issues a _postJson → the server answers
        the structured 409 → the client renders the 'reload required' banner
        instead of failing opaquely."""
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        w2_env, base = w2_server
        pid, _ = _mk_w2_project(w2_env, "FlowStale", git=False)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            statuses = []
            pg.on("response",
                  lambda r: statuses.append(r.status)
                  if "/api/rnd/set_notes" in r.url else None)
            pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
            # the page booted with the CURRENT build id
            boot_bid = pg.evaluate(
                "() => window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id")
            assert boot_bid == w2_env["gui"].BUILD_ID
            # simulate the stale tab: it declares a pre-deploy build id
            pg.evaluate("() => { window.ANCHOR_BOOT.build_id = 'stale-tab'; }")
            pg.evaluate(
                "(pid) => { _postJson('/api/rnd/set_notes',"
                " {project_id: pid, notes: 'w2'}); }", pid)
            pg.wait_for_selector("#anchorReloadBanner", timeout=6000)
            banner = pg.eval_on_selector("#anchorReloadBanner",
                                         "e => e.textContent")
            assert "updated" in banner and "Reload" in banner
            assert 409 in statuses, "the mutating POST did not answer 409"
            b.close()


# ══════════════════════════════════════════════════════════════════════════
# W3 — Spikes, Pillar Flags & Process Rails
# ══════════════════════════════════════════════════════════════════════════

PLAN_PATH = REPO_ROOT / "IMPLEMENTATION-PLAN.md"


def _flag_env(frontend=None, auth=None, journal=None, supervisor=None,
              **extra):
    """Build a hermetic pillar-flag env dict (unset flags stay at defaults)."""
    env = {}
    for flag, value in ((pf.FLAG_FRONTEND, frontend), (pf.FLAG_AUTH, auth),
                        (pf.FLAG_JOURNAL, journal),
                        (pf.FLAG_SUPERVISOR, supervisor)):
        if value is not None:
            env[pf.FLAG_ENV[flag]] = value
    env.update(extra)
    return env


# ──────────────────────────────────────────────────────────────────────────
# 10) W3 — the four pillar off-switch flags + named hybrid-state matrix
# ──────────────────────────────────────────────────────────────────────────

class TestW3PillarFlags:
    def test_unset_env_is_todays_live_behavior_the_baseline_state(self):
        """A host with none of the four env vars set resolves to every
        pillar's PRE-MIGRATION default — and that combination is the named
        ``baseline`` state (the flags are rails laid AHEAD of the pillars)."""
        assert pf.current_flags(env={}) == pf.FLAG_DEFAULTS
        row = pf.assert_named_state(env={})
        assert row["name"] == "baseline"
        assert row["flags"] == pf.FLAG_DEFAULTS
        assert row["support"]

    def test_invalid_flag_value_fails_loudly_never_falls_back(self):
        with pytest.raises(pf.PillarStateError) as e:
            pf.current_flags(env=_flag_env(frontend="spa"))
        assert "ANCHOR_FRONTEND" in str(e.value)
        assert "spa" in str(e.value)
        # the healthcheck assertion path fails the same way (never a default)
        with pytest.raises(pf.PillarStateError):
            pf.assert_named_state(env=_flag_env(auth="enforced-typo"))

    def test_auth_warn_alias_honored_only_when_mode_unset(self):
        """``ANCHOR_AUTH_WARN=1`` (the W8 soak flag) aliases to warn — but an
        explicit ``ANCHOR_AUTH_MODE`` always wins."""
        flags = pf.current_flags(env=_flag_env(ANCHOR_AUTH_WARN="1"))
        assert flags[pf.FLAG_AUTH] == "warn"
        flags = pf.current_flags(
            env=_flag_env(auth="open", ANCHOR_AUTH_WARN="1"))
        assert flags[pf.FLAG_AUTH] == "open"

    def test_every_named_matrix_row_passes_the_assertion(self):
        for row in pf.HYBRID_STATE_MATRIX:
            env = {pf.FLAG_ENV[f]: v for f, v in row["flags"].items()}
            got = pf.assert_named_state(env=env)
            assert got["name"] == row["name"]
            assert got["support"] == row["support"]

    def test_unnamed_combination_fails_loudly(self):
        """journal=on against the otherwise-baseline flags is NOT a named row
        (the journal lands on the static frontend ladder) — loud failure."""
        env = _flag_env(journal="on")
        assert pf.state_name(pf.current_flags(env=env)) is None
        with pytest.raises(pf.PillarStateError) as e:
            pf.assert_named_state(env=env)
        msg = str(e.value)
        assert "UNNAMED" in msg
        assert "baseline" in msg, "the error must name the supported states"

    def test_dag_forbidden_combination_names_the_violated_edge(self):
        """auth=enforce against the embedded frontend violates the one DAG
        edge — the failure message carries the edge and its reason."""
        env = _flag_env(auth="enforce")            # frontend stays embedded
        flags = pf.current_flags(env=env)
        violations = pf.dag_violations(flags)
        assert len(violations) == 1
        assert "auth=enforce requires frontend=static" in violations[0]
        with pytest.raises(pf.PillarStateError) as e:
            pf.assert_named_state(env=env)
        assert "DAG violation" in str(e.value)

    def test_matrix_rows_are_valid_unique_and_dag_legal(self):
        names = [r["name"] for r in pf.HYBRID_STATE_MATRIX]
        assert len(names) == len(set(names)), "matrix state names must be unique"
        for row in pf.HYBRID_STATE_MATRIX:
            assert set(row["flags"]) == set(pf.FLAG_ORDER)
            for flag, value in row["flags"].items():
                assert value in pf.FLAG_VALUES[flag], (row["name"], flag)
            assert pf.dag_violations(row["flags"]) == [], \
                f"named state {row['name']} violates the DAG"
            assert row["support"].strip(), "every row carries a support note"
        # the six deployment-ladder states are all named rows, in the matrix
        for name in pf.LADDER_STATES:
            assert pf.get_state(name) is not None

    def test_single_pillar_revert_closure(self):
        """The revert-compatibility rule, mechanically: from every ladder
        state, stepping any one advanced pillar DOWN one rung lands in a
        NAMED row — and where the DAG forbids the single-flag revert
        (frontend back to embedded under auth=enforce), the documented
        COMPOUND revert (auth→warn with it) lands named instead."""
        for name in pf.LADDER_STATES:
            row = pf.get_state(name)
            for flag in pf.FLAG_ORDER:
                order = pf.FLAG_VALUES[flag]
                idx = order.index(row["flags"][flag])
                if idx == 0:
                    continue                      # already at its baseline rung
                reverted = dict(row["flags"])
                reverted[flag] = order[idx - 1]
                if pf.dag_violations(reverted):
                    # only the documented edge may forbid a single-flag revert
                    assert flag == pf.FLAG_FRONTEND
                    assert row["flags"][pf.FLAG_AUTH] == "enforce"
                    reverted[pf.FLAG_AUTH] = "warn"      # the compound revert
                    assert pf.dag_violations(reverted) == []
                landing = pf.state_name(reverted)
                assert landing is not None, (
                    f"reverting {flag} from {name} lands UNNAMED: {reverted}")

    def test_matrix_doc_is_gate_refreshed_and_faithful(self, tmp_path):
        """`PILLAR-DAG.md` is a mechanical rendering of the module (refreshed
        by this very gate run, like the W1 census artifacts) — and a stale
        copy is rewritten to match."""
        # a stale/hand-edited copy is repaired
        stale = tmp_path / pf.MATRIX_DOC_NAME
        stale.write_text("# hand-edited drift\n", encoding="utf-8")
        out = pf.write_matrix_doc(out_dir=tmp_path)
        assert out == stale
        assert out.read_text(encoding="utf-8") == pf.render_matrix_md()
        # refresh the CHECKED-IN gate artifact and hold it faithful
        path = pf.write_matrix_doc()
        assert path == ARTIFACT_DIR / pf.MATRIX_DOC_NAME
        text = path.read_text(encoding="utf-8")
        assert text == pf.render_matrix_md()
        for row in pf.HYBRID_STATE_MATRIX:
            assert row["name"] in text
        assert "Revert-compatibility rule" in text
        assert "auth=enforce → requires frontend=static" in text


class TestW3HealthcheckPillarState:
    """The healthcheck asserts the CURRENT live configuration is a NAMED
    hybrid state (the W3 acceptance GWT)."""

    def _clean(self, monkeypatch):
        for var in list(pf.FLAG_ENV.values()) + [pf.AUTH_WARN_ALIAS_ENV]:
            monkeypatch.delenv(var, raising=False)

    def test_clean_env_passes_as_baseline(self, monkeypatch):
        self._clean(monkeypatch)
        import anchor_healthcheck as hc
        report = hc.Report()
        hc.check_pillar_state(report)
        name, ok, detail = report.checks[-1]
        assert "pillar" in name
        assert ok, detail
        assert "baseline" in detail
        assert not report.has_issues

    def test_named_nonbaseline_state_passes(self, monkeypatch):
        self._clean(monkeypatch)
        monkeypatch.setenv("ANCHOR_FRONTEND", "static")     # c1-static
        import anchor_healthcheck as hc
        report = hc.Report()
        hc.check_pillar_state(report)
        _, ok, detail = report.checks[-1]
        assert ok, detail
        assert "c1-static" in detail

    def test_unnamed_state_fails_the_check_loudly(self, monkeypatch):
        self._clean(monkeypatch)
        monkeypatch.setenv("ANCHOR_JOURNAL", "on")          # unnamed vs baseline
        import anchor_healthcheck as hc
        report = hc.Report()
        hc.check_pillar_state(report)
        _, ok, detail = report.checks[-1]
        assert not ok
        assert "UNNAMED" in detail
        assert report.has_issues

    def test_invalid_flag_value_fails_the_check(self, monkeypatch):
        self._clean(monkeypatch)
        monkeypatch.setenv("ANCHOR_SUPERVISOR", "sidecar")
        import anchor_healthcheck as hc
        report = hc.Report()
        hc.check_pillar_state(report)
        _, ok, detail = report.checks[-1]
        assert not ok
        assert "sidecar" in detail


# ──────────────────────────────────────────────────────────────────────────
# 11) W3 — ConPTY-across-processes spike (harness + recorded verdict)
# ──────────────────────────────────────────────────────────────────────────

class TestW3ConPTYSpike:
    def test_acceptance_questions_are_prewritten(self):
        """The three questions are frozen IN THE HARNESS (before any run) and
        carry their concrete bounds."""
        ids = [q["id"] for q in cs.ACCEPTANCE_QUESTIONS]
        assert ids == ["Q-LATENCY", "Q-REATTACH", "Q-COMPLEXITY"]
        joined = " ".join(q["question"] for q in cs.ACCEPTANCE_QUESTIONS)
        assert f"{cs.LATENCY_BOUND_MS:.0f} ms" in joined
        assert str(cs.COMPLEXITY_BUDGET_LINES) in joined

    def test_stub_leg_answers_the_questions_and_records_the_verdict(
            self, tmp_path, monkeypatch):
        """The deterministic stub leg: a REAL separate owner process holds the
        PTY, the client detaches (the dashboard 'restart'), a new connection
        re-attaches with full replay + live I/O — every byte crossing a
        genuine process boundary. The verdict is recorded into the CHECKED-IN
        artifacts (gate-refreshed, like the W1 census)."""
        monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
        result = cs.run_spike(backend="stub")
        assert result["backend"] == "stub" and result["ran"] is True
        answers = result["answers"]
        assert set(answers) == {"Q-LATENCY", "Q-REATTACH", "Q-COMPLEXITY"}
        # the across-process OWNERSHIP architecture holds deterministically
        assert answers["Q-REATTACH"]["pass"] is True, answers["Q-REATTACH"]
        assert answers["Q-COMPLEXITY"]["pass"] is True, answers["Q-COMPLEXITY"]
        assert answers["Q-LATENCY"]["median_ms"] > 0.0
        assert answers["Q-LATENCY"]["pass"] is True, (
            f"cross-process echo median exceeded the pre-written bound: "
            f"{answers['Q-LATENCY']}")
        assert result["verdict"] == "YES"

        jp, mp = cs.record_verdict(result)      # the checked-in gate artifact
        assert jp == ARTIFACT_DIR / cs.VERDICT_JSON_NAME
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["questions"] == list(cs.ACCEPTANCE_QUESTIONS)
        assert payload["legs"]["stub"]["ran"] is True
        md = mp.read_text(encoding="utf-8")
        assert "Verdict: YES" in md
        # the real-ConPTY leg is recorded HONESTLY: a leg that has not run
        # renders NOT YET RUN (a prior recorded real run is never erased)
        if not (payload["legs"].get("real") or {}).get("ran"):
            assert "NOT YET RUN" in md

    @pytest.mark.skipif(
        not os.environ.get("ANCHOR_SPIKE_REAL_CONPTY"),
        reason="real-ConPTY leg is opt-in (ANCHOR_SPIKE_REAL_CONPTY=1)")
    def test_real_conpty_leg_opt_in_runs_and_records(self):
        result = cs.run_spike(backend="real")
        assert result["ran"] is True and result["backend"] == "real"
        jp, _ = cs.record_verdict(result)
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["legs"]["real"]["ran"] is True

    def test_record_verdict_is_diff_stable_across_green_reruns(self, tmp_path):
        """A green re-run whose only difference is the volatile measurement
        (median ms / detail text) does NOT rewrite the artifacts — git status
        stays clean; a REAL change (an answer flips) does rewrite."""
        leg = {
            "backend": "stub", "ran": True, "verdict": "YES",
            "answers": {
                "Q-LATENCY": {"pass": True, "median_ms": 12.3,
                              "detail": "median 12.3 ms over 5 rounds"},
                "Q-REATTACH": {"pass": True, "detail": "replayed"},
                "Q-COMPLEXITY": {"pass": True, "detail": "300 lines"},
            },
        }
        jp, mp = cs.record_verdict(dict(leg), out_dir=tmp_path)
        j1 = jp.read_text(encoding="utf-8")
        m1 = mp.read_text(encoding="utf-8")

        rerun = json.loads(json.dumps(leg))
        rerun["answers"]["Q-LATENCY"]["median_ms"] = 47.9
        rerun["answers"]["Q-LATENCY"]["detail"] = "median 47.9 ms over 5 rounds"
        cs.record_verdict(rerun, out_dir=tmp_path)
        assert jp.read_text(encoding="utf-8") == j1
        assert mp.read_text(encoding="utf-8") == m1

        flipped = json.loads(json.dumps(leg))
        flipped["answers"]["Q-REATTACH"]["pass"] = False
        flipped["verdict"] = "NO"
        cs.record_verdict(flipped, out_dir=tmp_path)
        assert jp.read_text(encoding="utf-8") != j1
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["legs"]["stub"]["verdict"] == "NO"

    def test_unrun_leg_is_recorded_honestly_and_no_verdict_is_fabricated(
            self, tmp_path):
        """An artifact with NO recorded legs claims nothing: both legs render
        as NOT YET RUN, and the NO-routing (the pre-designed drain) is
        documented for W17."""
        jp, mp = cs.record_verdict(None, out_dir=tmp_path)
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["legs"] == {}
        md = mp.read_text(encoding="utf-8")
        assert md.count("NOT YET RUN") == 2
        assert "pre_restart_drain" in md, \
            "a NO verdict must route W17 to the pre-designed drain"


# ──────────────────────────────────────────────────────────────────────────
# 12) W3 — cookie-through-WS-upgrade spike (real browser + recorded verdict)
# ──────────────────────────────────────────────────────────────────────────

class TestW3CookieWSSpike:
    def test_acceptance_questions_and_fallback_are_prewritten(self):
        ids = [q["id"] for q in cw.ACCEPTANCE_QUESTIONS]
        assert ids == ["Q-COOKIE-DESKTOP", "Q-COOKIE-PWA", "Q-FALLBACK"]
        pwa_q = cw.ACCEPTANCE_QUESTIONS[1]["question"]
        assert "Tailscale" in pwa_q and "PWA" in pwa_q
        assert "?token=" in cw.FALLBACK_DECLARATION
        assert "WS/SSE" in cw.FALLBACK_DECLARATION

    def test_evaluate_desktop_judges_the_captured_upgrade(self):
        good = ("GET /spike-ws HTTP/1.1\r\nHost: t\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Cookie: {cw.COOKIE_NAME}={cw.COOKIE_VALUE}\r\n\r\n")
        assert cw.evaluate_desktop({"ws_request": good})["pass"] is True
        # cookie missing from the upgrade → honest NO
        no_cookie = ("GET /spike-ws HTTP/1.1\r\nHost: t\r\n"
                     "Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        verdict = cw.evaluate_desktop({"ws_request": no_cookie})
        assert verdict["pass"] is False
        # nothing captured → honest NO with the reason, never fabricated
        empty = cw.evaluate_desktop({"ws_request": None})
        assert empty["pass"] is False
        assert "no WebSocket upgrade request" in empty["detail"]

    def test_capture_server_sets_cookie_and_captures_the_upgrade_verbatim(
            self):
        """The stdlib harness itself: GET / answers the cookie-setting page;
        a client-shaped upgrade request to /spike-ws is captured raw."""
        import socket as sk
        port, state, stop = cw.start_capture_server()
        try:
            s = sk.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(b"GET / HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            s.close()
            assert b"Set-Cookie: " + cw.COOKIE_NAME.encode() in data
            assert b"cookie-ws spike page" in data

            s = sk.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(("GET /spike-ws HTTP/1.1\r\nHost: t\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Cookie: {cw.COOKIE_NAME}={cw.COOKIE_VALUE}\r\n"
                       "\r\n").encode("latin-1"))
            for _ in range(100):
                if state["ws_request"] is not None:
                    break
                time.sleep(0.05)
            s.close()
        finally:
            stop()
        assert state["ws_request"] is not None
        assert cw.evaluate_desktop(state)["pass"] is True

    def test_desktop_leg_real_browser_records_the_checked_in_verdict(self):
        """THE mechanical desktop leg: a REAL browser (Playwright Chromium)
        loads the cookie-setting page then opens a same-origin ws:// — the
        captured upgrade request answers Q-COOKIE-DESKTOP, recorded into the
        CHECKED-IN artifacts."""
        pytest.importorskip("playwright.sync_api")
        from playwright.sync_api import sync_playwright
        port, state, stop = cw.start_capture_server()
        try:
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page()
                pg.goto(f"http://127.0.0.1:{port}/")
                assert "cookie-ws spike page" in pg.content()
                pg.evaluate(
                    "(url) => { try { new WebSocket(url); } catch (e) {} }",
                    f"ws://127.0.0.1:{port}{cw.WS_PATH}")
                for _ in range(160):
                    if state["ws_request"] is not None:
                        break
                    time.sleep(0.05)
                b.close()
        finally:
            stop()
        assert state["ws_request"] is not None, \
            "the browser never attempted the WS upgrade"
        answer = cw.evaluate_desktop(state)
        assert answer["pass"] is True, (
            f"desktop browser did not carry the cookie through the WS "
            f"upgrade: {answer}")

        jp, mp = cw.record_verdict(desktop_result={
            "ran": True, "browser": "chromium", "answer": answer})
        assert jp == ARTIFACT_DIR / cw.VERDICT_JSON_NAME
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["legs"]["desktop"]["answer"]["pass"] is True
        assert payload["fallback_declared"] is True
        md = mp.read_text(encoding="utf-8")
        assert "Verdict: YES" in md

    def test_pwa_leg_honest_runbook_and_declared_fallback(self, tmp_path):
        """The iPhone-PWA leg CANNOT run in CI: until the live manual runbook
        runs with John it is recorded honestly as NOT YET RUN (with the
        runbook + the recording command), and ?token= is DECLARED as the WS
        fallback unconditionally."""
        jp, mp = cw.record_verdict(out_dir=tmp_path)
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["legs"] == {}
        assert payload["fallback_declared"] is True
        assert payload["fallback"] == cw.FALLBACK_DECLARATION
        md = mp.read_text(encoding="utf-8")
        assert "NOT YET RUN" in md
        assert "Tailscale" in md
        assert "--record-pwa" in md, "the runbook's recording command"
        assert "UNPROVEN" in md, \
            "W9 must treat the PWA as unproven until the leg runs"
        assert "DECLARED" in md

        # the manual runbook's recording path merges the leg in honestly
        cw.record_verdict(pwa_result={
            "ran": True,
            "answer": {"pass": True, "detail": "manual runbook run"}},
            out_dir=tmp_path)
        payload = json.loads(jp.read_text(encoding="utf-8"))
        assert payload["legs"]["pwa"]["ran"] is True
        md = mp.read_text(encoding="utf-8")
        assert "manual runbook run" in md


# ──────────────────────────────────────────────────────────────────────────
# 13) W3 — pre-designed graceful pre-restart drain (proven on a stub PTY)
# ──────────────────────────────────────────────────────────────────────────

class TestW3PreRestartDrain:
    @staticmethod
    def _start_with_doc(pid, lane="plan", doc="MASTER-PLAN.md"):
        """A live stub-PTY session with an UNSAVED produced doc in its
        worktree — the W3 acceptance GWT's given."""
        import terminal_session as ts
        rec = ts.start_session(pid, lane, backend="claude")
        wt_dir = Path(rec["worktree_path"])
        pdir = wt_dir / "planning" / "rearch-w3"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / doc).write_text(
            "# Master Plan\n## North Star\nDrain parks warm.\n",
            encoding="utf-8")
        return rec

    @_needs_git
    def test_drain_parks_live_sessions_warm(self, w2_env):
        """The W3 acceptance GWT: a live stub-PTY session with unsaved
        produced docs → drain → parked via close_session, docs captured to
        main, and a warm-resume seed exists so the post-restart reopen is
        WARM, not cold."""
        import pty_manager
        import session_registry as reg
        import summarizer
        gui = w2_env["gui"]
        pid, folder = _mk_w2_project(w2_env, "DrainWarm")
        rec = self._start_with_doc(pid)
        sid = rec["session_id"]
        assert sid in pty_manager.live_sessions()

        report = drain_mod.drain()
        assert report["ok"] is True and report["dry_run"] is False
        entry = next(e for e in report["drained"] if e["session_id"] == sid)

        # (1) parked via close_session: PTY stopped, record kept IDLE
        assert entry["parked"] is True
        assert entry["status"] == reg.STATUS_IDLE
        assert sid not in pty_manager.live_sessions()
        assert reg.get_session(sid)["status"] == reg.STATUS_IDLE
        assert reg.get_session(sid)["status"] not in reg.TERMINAL_STATUSES

        # (2) the produced docs were captured into MAIN before any reap
        assert any("MASTER-PLAN.md" in p for p in entry["docs_persisted"])
        assert (folder / "planning" / "rearch-w3" / "MASTER-PLAN.md").exists()

        # (3) the warm-resume seed: summary CACHED + the REAL resume seed of
        # anchor_gui yields a non-empty warm open (never cold)
        assert entry["seed"] in ("generated", "cached")
        assert summarizer.load_cached(str(folder), pid, "planning",
                                      sid) is not None
        seed = gui._build_continue_seed(str(folder), pid, "plan", sid)
        assert seed, "the post-restart reopen must be WARM, not cold"

        # idempotent: a parked session is not drained again
        again = drain_mod.drain()
        assert all(e["session_id"] != sid for e in again["drained"])

    @_needs_git
    def test_dry_run_enumerates_without_mutating(self, w2_env):
        import pty_manager
        import session_registry as reg
        from tests import rearch_flows as flows
        pid, _ = _mk_w2_project(w2_env, "DrainDry")
        rec = self._start_with_doc(pid, lane="research")
        sid = rec["session_id"]
        try:
            report = drain_mod.drain(dry_run=True)
            assert report["dry_run"] is True
            entry = next(e for e in report["drained"]
                         if e["session_id"] == sid)
            assert entry.get("would_drain") is True
            assert "parked" not in entry
            # nothing mutated: still live, still RUNNING
            assert sid in pty_manager.live_sessions()
            assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING
        finally:
            flows.kill_quietly(sid)

    @_needs_git
    def test_wedged_summary_generation_cannot_block_the_restart(
            self, w2_env, monkeypatch):
        """The bounded warm-seed generation: a wedged model call times out
        honestly (seed='timeout'), the session is STILL parked, and the drain
        returns fast — a restart can never hang on a summary. The module
        global is read at call time (test-tunable)."""
        import session_registry as reg
        import summarizer
        pid, _ = _mk_w2_project(w2_env, "DrainWedge")
        rec = self._start_with_doc(pid)
        sid = rec["session_id"]

        wedge = threading.Event()

        def _wedged(*a, **k):
            wedge.wait(30)                      # a wedged model call

        monkeypatch.setattr(summarizer, "summarize_session", _wedged)
        t0 = time.monotonic()
        report = drain_mod.drain(summary_timeout=0.2)
        elapsed = time.monotonic() - t0
        entry = next(e for e in report["drained"] if e["session_id"] == sid)
        assert entry["parked"] is True, "the park must proceed regardless"
        assert entry["seed"] == "timeout"
        assert elapsed < 15, "a wedged summary must never block the restart"
        assert reg.get_session(sid)["status"] == reg.STATUS_IDLE

        # DRAIN_SUMMARY_TIMEOUT is the module-global default, read per call
        monkeypatch.setattr(drain_mod, "DRAIN_SUMMARY_TIMEOUT", 0.1)
        t0 = time.monotonic()
        assert drain_mod.ensure_warm_seed(pid, "plan", sid) == "timeout"
        assert time.monotonic() - t0 < 10
        wedge.set()

    @_needs_git
    def test_per_session_failure_never_blocks_the_rest(
            self, w2_env, monkeypatch):
        """Best-effort: one session's park failing is recorded honestly and
        the drain proceeds to the next session (never raises)."""
        import terminal_session as ts
        from tests import rearch_flows as flows
        pid, _ = _mk_w2_project(w2_env, "DrainBestEffort")
        a = self._start_with_doc(pid)
        b = self._start_with_doc(pid)
        real_close = ts.close_session

        def _flaky(sid, project_id=None):
            if sid == a["session_id"]:
                raise RuntimeError("boom-park")
            return real_close(sid, project_id=project_id)

        monkeypatch.setattr(ts, "close_session", _flaky)
        try:
            report = drain_mod.drain(summary_timeout=0.1)
            assert report["ok"] is True
            by = {e["session_id"]: e for e in report["drained"]}
            assert by[a["session_id"]]["parked"] is False
            assert "boom-park" in by[a["session_id"]]["error"]
            assert by[b["session_id"]]["parked"] is True
        finally:
            flows.kill_quietly(a["session_id"])
            flows.kill_quietly(b["session_id"])

    def test_unresolvable_project_is_honest_unavailable(self, w2_env):
        """No project/folder → the seed is honestly 'unavailable' (no cache
        written, nothing fabricated, nothing raised)."""
        assert drain_mod.ensure_warm_seed(
            "no-such-project", "plan", "no-such-session") == "unavailable"


# ──────────────────────────────────────────────────────────────────────────
# 14) W3 — process rails: Butler stories · rituals · Appendix-A ledger
# ──────────────────────────────────────────────────────────────────────────

class TestW3ButlerStories:
    DOC = ARTIFACT_DIR / "BUTLER-USER-STORIES.md"

    def test_three_binding_stories_with_envelope_answer_paths(self):
        assert self.DOC.exists(), \
            "the Butler user stories are a checked-in W3 artifact"
        md = self.DOC.read_text(encoding="utf-8")
        assert re.findall(r"^## Story (\d+)", md, flags=re.M) == \
            ["1", "2", "3"]
        # every story is answerable from ENVELOPE FIELDS ALONE — each carries
        # its answer path, and the binding envelope fields are all named
        assert md.count("**Envelope answer path:**") == 3
        for field in ("correlation_id", "causation_id", "actor", "seq",
                      "ts", "schema_ver"):
            assert field in md, f"envelope field {field} missing"
        # the stories BIND the W12 envelope (the Phase-4 validation target)
        assert "W12" in md
        assert "BINDING" in md or "binding" in md
        # the amendment path: the envelope changes, never the story
        assert "amendment" in md.lower()


class TestW3ProcessRails:
    DOC = ARTIFACT_DIR / "PROCESS-RAILS.md"

    def test_the_codified_rituals_are_checked_in(self):
        assert self.DOC.exists(), \
            "the codified rituals are a checked-in W3 artifact"
        md = self.DOC.read_text(encoding="utf-8")
        for ritual in ("Per-wave live-service smoke checklist",
                       "Healthcheck SLO",
                       "Auth-flip sequencing rule",
                       "Soft merge-freeze protocol"):
            assert ritual in md, f"ritual missing: {ritual}"

    def test_smoke_checklist_covers_the_live_service(self):
        md = self.DOC.read_text(encoding="utf-8")
        assert "nssm restart anchor" in md
        assert "ANCHOR_BOOT" in md, "the new-build assert (no stale supervisor)"
        assert "anchor_healthcheck.py" in md
        assert "8777" in md

    def test_healthcheck_slo_has_the_three_mandated_terms(self):
        md = self.DOC.read_text(encoding="utf-8")
        assert "15 minutes" in md, "the wall-time cap"
        assert "Zero known flakes" in md
        assert "20 consecutive green" in md and "5AM" in md, \
            "the 20× nightly promotion rule"

    def test_auth_flip_sequencing_rule(self):
        md = self.DOC.read_text(encoding="utf-8")
        assert "NEVER ships in the same deploy" in md
        # warn soaks BEFORE enforce, and rollback is a FLAG, not a revert
        assert md.index("warn") < md.index("enforce")
        assert "never a code revert" in md
        assert "ANCHOR_AUTH_MODE" in md

    def test_merge_freeze_protocol(self):
        md = self.DOC.read_text(encoding="utf-8")
        assert "anchor_gui.py" in md
        assert "REBASES" in md, "the urgent-fix exception path"
        assert "byte-parity" in md
        assert "W6" in md, "the freeze lifts at the C1 exit gate"


class TestW3AppendixALedger:
    """The traceability ledger is DIFFED MECHANICALLY against the frozen
    plan's own citation lines — demonstrated, not narrated."""

    LEDGER = ARTIFACT_DIR / "APPENDIX-A-TRACEABILITY.md"
    _CITE = re.compile(
        r"\(Master Plan Phase \d+;(?: D\d+;)?"
        r" Integrated ([0-9, ]+?)(?:; Mitigations? ([0-9, ]+?))?\)")

    def _plan_citations(self):
        text = PLAN_PATH.read_text(encoding="utf-8")
        waves = [(int(m.group(1)), m.start())
                 for m in re.finditer(r"^## Wave (\d+)", text, flags=re.M)]
        assert len(waves) == 18, "the frozen plan has 18 waves"
        ideas, mits = {}, {}
        for i, (num, start) in enumerate(waves):
            end = waves[i + 1][1] if i + 1 < len(waves) else len(text)
            m = self._CITE.search(text, start, end)
            assert m, f"wave {num} has no (Master Plan …) citation line"
            for n in re.findall(r"\d+", m.group(1)):
                ideas.setdefault(int(n), set()).add(f"W{num}")
            if m.group(2):
                for n in re.findall(r"\d+", m.group(2)):
                    mits.setdefault(int(n), set()).add(f"W{num}")
        return ideas, mits

    def _ledger_tables(self):
        assert self.LEDGER.exists(), \
            "the Appendix-A traceability ledger is a checked-in W3 artifact"
        md = self.LEDGER.read_text(encoding="utf-8")
        ideas = {int(m.group(1)): set(re.findall(r"W\d+", m.group(2)))
                 for m in re.finditer(r"^\| I-(\d+) \| ([^|]*)\|",
                                      md, flags=re.M)}
        mits = {int(m.group(1)): set(re.findall(r"W\d+", m.group(2)))
                for m in re.finditer(r"^\| M-(\d+) \| ([^|]*)\|",
                                     md, flags=re.M)}
        return ideas, mits, md

    def test_ledger_matches_the_frozen_plan_mechanically(self):
        plan_ideas, plan_mits = self._plan_citations()
        led_ideas, led_mits, _ = self._ledger_tables()
        # the ledger enumerates ideas 1–52 and mitigations 1–20 exhaustively
        assert set(led_ideas) == set(range(1, 53))
        assert set(led_mits) == set(range(1, 21))
        # ideas: every ledger row equals the plan's own citations — and every
        # idea is cited by at least one wave (zero silently dropped)
        for i in range(1, 53):
            assert led_ideas[i] == plan_ideas.get(i, set()), \
                f"I-{i} drifted from the frozen plan's citations"
        assert set(plan_ideas) == set(range(1, 53)), \
            "an integrated idea is cited by NO wave (silent drop)"
        # mitigations: exact per row; M-9 is cited by ZERO waves (by design,
        # reconciled explicitly) and every other mitigation lands somewhere
        for n in range(1, 21):
            assert led_mits[n] == plan_mits.get(n, set()), \
                f"M-{n} drifted from the frozen plan's citations"
        assert 9 not in plan_mits and led_mits[9] == set()
        assert set(plan_mits) == set(range(1, 21)) - {9}

    def test_mitigation_9_is_explicitly_reconciled(self):
        _, _, md = self._ledger_tables()
        assert "## Mitigation 9 — the explicit reconciliation" in md
        tail = md.split("Mitigation 9", 1)[1]
        assert "W18" in tail, \
            "the reconciliation binds W18's closure to resolve M-9"
        assert "OPEN reconciliation item" in md


# ──────────────────────────────────────────────────────────────────────────
# 15) W3 amendment (2026-07-03, human-authorized) — the no-leak rail
#
# HARD REQUIREMENT: every process the spike/tests spawn (claude.exe, PTY
# children) is reaped before the test returns — a gate run leaving ZERO
# leaked processes is part of W3's done-when. Enforced mechanically: a
# session-scoped autouse sentinel snapshots the host process table ONCE at
# session end (a single batched CIM call — never a shell storm) and fails
# the run if any flagged process survived.
# ──────────────────────────────────────────────────────────────────────────

#: Image names a leak can take here: the engine CLI itself, the PTY children
#: (real-ConPTY cmd.exe / pywinpty's agent), and python/pythonw (the spike
#: owner process, fake_claude, preview servers). Deliberately TIGHT — never
#: conhost/powershell (every console process owns one; the census's own
#: spawn) — so a legit foreign process is never flagged.
_LEAK_IMAGES = {"claude.exe", "cmd.exe", "winpty-agent.exe",
                "python.exe", "pythonw.exe"}


def _process_table_snapshot():
    """One batched CIM call → {pid: {"name", "ppid", "created"}} (Windows).

    ``created`` is seconds since the Unix epoch (converted from FILETIME).
    The single spawn per gate run is the sanctioned census exception to the
    no-shell-storm rule.
    """
    script = (
        "Get-CimInstance Win32_Process | Select-Object ProcessId,"
        "ParentProcessId,Name,@{N='FT';E={ if ($_.CreationDate) "
        "{ $_.CreationDate.ToFileTimeUtc() } else { 0 } }} | "
        "ConvertTo-Json -Compress")
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Tolerant on a census hiccup (empty stdout → empty table → nothing
    # flagged): the rail must never flake the suite on a WMI blip; the
    # orchestrator's own gate-time census remains the outer backstop.
    rows = json.loads(out.stdout or "[]")
    table = {}
    for r in rows if isinstance(rows, list) else [rows]:
        pid = r.get("ProcessId")
        if pid is None:
            continue
        ft = r.get("FT") or 0
        table[int(pid)] = {
            "name": (r.get("Name") or "").lower(),
            "ppid": int(r.get("ParentProcessId") or 0),
            "created": ft / 1e7 - 11644473600 if ft else 0.0,
        }
    return table


def _flag_leaked_processes(table, root_pid, started_at):
    """The pure leak classifier (unit-testable without spawning anything).

    A live process is a LEAK iff its image name is in :data:`_LEAK_IMAGES`,
    it is not the pytest process itself, and either:

    * it is a DESCENDANT of the pytest process (parent chain reaches
      ``root_pid``, each edge validated child-younger-than-parent so a
      recycled PID can never fake an edge), or
    * it is an ORPHAN born during this run — ``claude.exe`` created after
      ``started_at`` whose parent PID is no longer in the table (the exact
      signature of the 09:49 leak: the spawner died, the engine survived).

    A foreign process (John opening a claude session mid-run) is NEVER
    flagged: its parent (his terminal) is alive and outside our tree.
    """
    def _is_descendant(pid):
        seen = set()
        while pid and pid not in seen:
            seen.add(pid)
            row = table.get(pid)
            if row is None:
                return False
            ppid = row["ppid"]
            parent = table.get(ppid)
            if parent is None:
                return False
            if parent["created"] and row["created"] \
                    and parent["created"] > row["created"] + 1.0:
                return False               # recycled PID — not a real edge
            if ppid == root_pid:
                return True
            pid = ppid
        return False

    leaked = []
    for pid, row in table.items():
        if pid == root_pid or row["name"] not in _LEAK_IMAGES:
            continue
        orphan = (row["name"] == "claude.exe"
                  and row["created"] > started_at
                  and row["ppid"] not in table)
        if orphan or _is_descendant(pid):
            leaked.append({"pid": pid, "name": row["name"],
                           "ppid": row["ppid"],
                           "orphan": bool(orphan)})
    return sorted(leaked, key=lambda e: e["pid"])


@pytest.fixture(scope="session", autouse=True)
def _w3_no_leak_rail():
    """Session-end census: the gate run itself must leak ZERO processes."""
    if os.name != "nt":                    # the rail targets this Windows host
        yield
        return
    started_at = time.time()
    yield
    leaked = _flag_leaked_processes(_process_table_snapshot(), os.getpid(),
                                    started_at)
    if leaked:
        time.sleep(2.0)                    # grace: a child mid-exit is not a leak
        again = _flag_leaked_processes(_process_table_snapshot(), os.getpid(),
                                       started_at)
        still = {e["pid"] for e in again}
        leaked = [e for e in leaked if e["pid"] in still]
    assert not leaked, (
        "W3 no-leak rail: the run left live spawned processes "
        f"(reap them in the test that spawned them): {leaked}")


class TestW3NoLeakRail:
    """The classifier itself, proven on synthetic tables (no spawning)."""

    T0 = 1_000_000.0

    def _table(self):
        return {
            100: {"name": "python.exe", "ppid": 1, "created": self.T0 - 50},
            # our descendants: pytest(=100) → owner python → cmd child
            101: {"name": "python.exe", "ppid": 100, "created": self.T0 + 1},
            102: {"name": "cmd.exe", "ppid": 101, "created": self.T0 + 2},
            # an orphan claude born during the run (spawner already dead)
            103: {"name": "claude.exe", "ppid": 999, "created": self.T0 + 3},
            # John's own claude: parent alive, outside our tree — NEVER flagged
            200: {"name": "wt.exe", "ppid": 1, "created": self.T0 - 500},
            201: {"name": "claude.exe", "ppid": 200, "created": self.T0 + 4},
            # a conhost descendant of ours: not in the flag set
            104: {"name": "conhost.exe", "ppid": 101, "created": self.T0 + 2},
        }

    def test_descendants_and_orphans_are_flagged(self):
        leaked = _flag_leaked_processes(self._table(), 100, self.T0)
        got = {(e["pid"], e["orphan"]) for e in leaked}
        assert got == {(101, False), (102, False), (103, True)}

    def test_foreign_and_unlisted_images_never_flagged(self):
        leaked = _flag_leaked_processes(self._table(), 100, self.T0)
        pids = {e["pid"] for e in leaked}
        assert 201 not in pids, "a foreign claude must never be flagged"
        assert 104 not in pids, "conhost is outside the flag set"
        assert 100 not in pids, "the pytest root itself is exempt"

    def test_recycled_pid_cannot_fake_an_edge(self):
        table = self._table()
        # 105 claims parent 100, but 100 was created LONG after it —
        # a recycled PID; the edge is rejected, nothing flagged.
        table[105] = {"name": "python.exe", "ppid": 100,
                      "created": self.T0 - 5_000}
        leaked = _flag_leaked_processes(table, 100, self.T0)
        assert 105 not in {e["pid"] for e in leaked}

    def test_prexisting_claude_with_dead_parent_not_an_orphan_leak(self):
        table = self._table()
        # born BEFORE the run started → not ours, even though orphaned
        table[106] = {"name": "claude.exe", "ppid": 998,
                      "created": self.T0 - 100}
        leaked = _flag_leaked_processes(table, 100, self.T0)
        assert 106 not in {e["pid"] for e in leaked}
