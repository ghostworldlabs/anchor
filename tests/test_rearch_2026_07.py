"""W1 gate — Ground-Truth Instrumentation (census · anchors · tripwire).

Re-architecture 2026-07, Wave 1 (frozen plan: IMPLEMENTATION-PLAN.md). Gates:

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
"""

import ast
import builtins
import io
import json
import os
import textwrap

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
