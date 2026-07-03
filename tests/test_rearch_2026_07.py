"""W1+W2 gate — re-architecture 2026-07 (frozen plan: IMPLEMENTATION-PLAN.md).

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

from tools import anchors as anchors_mod
from tools import interpolation_census as census_mod
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
        assert cs("/x/.anchor/projects/0f3ab9d2c4e5f6a7/grass/idea-abc12/"
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
        monkeypatch.setenv("ANCHOR_TOKEN", "w2-s3cret")
        _, html = _http(base, "/")
        boot = _extract_boot(html)
        assert boot["auth_required"] is True
        # presence only — the token VALUE is never embedded in served HTML.
        assert "w2-s3cret" not in html

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
        monkeypatch.setenv("ANCHOR_TOKEN", "w2-s3cret")
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
        monkeypatch.setenv("ANCHOR_TOKEN", "w2-s3cret")
        # no credentials → 401
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"})
        assert status == 401 and body["error"] == "unauthorized"
        # Authorization: Bearer <token> → accepted
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"Authorization": "Bearer w2-s3cret"})
        assert status == 200 and "ok" in body
        # wrong bearer → 401
        status, _ = _http(base, "/api/done", method="POST",
                          payload={"text": "__w2_probe__"},
                          headers={"Authorization": "Bearer nope"})
        assert status == 401
        # the legacy browser path (X-Anchor-Token) still works unchanged
        status, body = _http(base, "/api/done", method="POST",
                             payload={"text": "__w2_probe__"},
                             headers={"X-Anchor-Token": "w2-s3cret"})
        assert status == 200 and "ok" in body

    def test_gated_get_accepts_authorization(self, w2_server, monkeypatch):
        """A representative token-gated read GET (the healthcheck-walk class of
        consumer): Authorization passes the gate (the 400 for missing params
        PROVES auth ran first and passed); tokenless is 401."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "w2-s3cret")
        path = "/api/rnd/session_doc_roles"
        status, body = _http(base, path)
        assert status == 401 and body["error"] == "unauthorized"
        status, _ = _http(base, path,
                          headers={"Authorization": "Bearer w2-s3cret"})
        assert status == 400          # auth passed; params missing
        # ?token= keeps working (browser reads keep it until the W9 cutover)
        status, _ = _http(base, path + "?token=w2-s3cret")
        assert status == 400

    def test_sse_transport_retains_query_token(self, w2_server, monkeypatch):
        """WS/SSE are the ONLY transports that still NEED ?token= (browsers
        can't set headers there) — and the header path works on them too."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "w2-s3cret")
        path = "/api/rnd/term_stream2"
        status, body = _http(base, path)
        assert status == 401 and body["error"] == "unauthorized"
        status, _ = _http(base, path + "?token=w2-s3cret")
        assert status == 400          # auth passed; session missing
        status, _ = _http(base, path,
                          headers={"Authorization": "Bearer w2-s3cret"})
        assert status == 400

    def test_healthcheck_post_helper_presents_authorization(
            self, w2_server, monkeypatch):
        """The healthcheck endpoint walk — the canonical non-browser consumer
        — really presents the token via the Authorization header (functional:
        its own _post succeeds against a token-requiring server)."""
        w2_env, base = w2_server
        monkeypatch.setenv("ANCHOR_TOKEN", "w2-s3cret")
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
