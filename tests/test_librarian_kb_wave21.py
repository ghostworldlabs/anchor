"""Wave 21 Unit & Integration Test Suite for `librarian_kb.py` (Librarian Knowledge Base
& Generalized Product-Manifold Engine).

Covers:
  1. Lorentz Hyperboloid & Poincare Ball stereographic isometry + Mobius recentering
  2. Mixed-Curvature Product Manifold metric axioms & triangle inequality
  3. Unstructured Python AST + Markdown section chunking with SHA-256 provenance
  4. Full 19-skill ecosystem ingestion (Skills, Tools, Peer Skills, Knowledge Sources, Repos)
  5. Hybrid BM25 (FTS5) + Product-Manifold geodesic search & token-budget routing
  6. Librarian execution logging & Piaget assimilation (usage counts + outcome credit)
  7. Poincare ecosystem map generation and isometric focus recentering
"""

from __future__ import annotations

import hashlib
import math
import random
import sys
from pathlib import Path

import pytest

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
if str(ANCHOR_ROOT) not in sys.path:
    sys.path.insert(0, str(ANCHOR_ROOT))

import librarian_kb as lkb


# ── 1. Lorentz / Poincare / Mobius Mathematical Identities ───────────────────

def test_lorentz_poincare_stereographic_roundtrip_and_isometry():
    """Verify Pi_{L->B} and Pi_{B->L} are mutual inverses and preserve hyperbolic distance."""
    pts_poincare = [
        [0.0, 0.0],
        [0.35, -0.25],
        [-0.62, 0.41],
        [0.88, -0.19],
    ]
    for z in pts_poincare:
        x = lkb.poincare_to_lorentz(z, kappa=1.0)
        # Check Lorentz hyperboloid sheet constraint <x, x>_L = -1, x_0 > 0
        assert x[0] >= 1.0
        assert math.isclose(lkb.lorentz_inner(x, x), -1.0, rel_tol=1e-11, abs_tol=1e-11)
        z_back = lkb.lorentz_to_poincare(x, kappa=1.0)
        assert math.isclose(z[0], z_back[0], rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(z[1], z_back[1], rel_tol=1e-9, abs_tol=1e-9)

    # Check geodesic distance matches Poincare ball formula
    for i in range(len(pts_poincare)):
        for j in range(i + 1, len(pts_poincare)):
            u, v = pts_poincare[i], pts_poincare[j]
            xu = lkb.poincare_to_lorentz(u)
            xv = lkb.poincare_to_lorentz(v)
            d_lor = lkb.lorentz_distance(xu, xv)

            u2 = u[0] ** 2 + u[1] ** 2
            v2 = v[0] ** 2 + v[1] ** 2
            diff2 = (u[0] - v[0]) ** 2 + (u[1] - v[1]) ** 2
            d_poin = math.acosh(1.0 + 2.0 * diff2 / ((1.0 - u2) * (1.0 - v2)))
            assert math.isclose(d_lor, d_poin, rel_tol=1e-9, abs_tol=1e-9)


def test_mobius_recenter_isometry_and_origin_mapping():
    """Verify Mobius recentering maps the focus node to (0, 0) and preserves hyperbolic distance."""
    focus = [0.42, -0.31]
    other = [-0.28, 0.53]

    centered_focus = lkb.mobius_recenter(focus, focus)
    assert math.isclose(centered_focus[0], 0.0, abs_tol=1e-12)
    assert math.isclose(centered_focus[1], 0.0, abs_tol=1e-12)

    centered_other = lkb.mobius_recenter(other, focus)
    assert math.hypot(centered_other[0], centered_other[1]) < 1.0

    # Hyperbolic distance between focus and other before vs. after recentering must match
    d_before = lkb.lorentz_distance(lkb.poincare_to_lorentz(focus), lkb.poincare_to_lorentz(other))
    d_after = lkb.lorentz_distance(
        lkb.poincare_to_lorentz(centered_focus),
        lkb.poincare_to_lorentz(centered_other),
    )
    assert math.isclose(d_before, d_after, rel_tol=1e-9, abs_tol=1e-9)


def test_lorentz_inner_product_knn_rank_monotonicity():
    """Verify ranking by -<q, x_i>_L is 100% rank-identical to ranking by geodesic distance d_L(q, x_i)."""
    rng = random.Random(42)
    candidates = [
        lkb.poincare_to_lorentz([rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6)])
        for _ in range(100)
    ]
    query = lkb.poincare_to_lorentz([0.25, -0.15])

    order_geodesic = sorted(range(len(candidates)), key=lambda i: lkb.lorentz_distance(query, candidates[i]))
    order_inner = sorted(range(len(candidates)), key=lambda i: -lkb.lorentz_inner(query, candidates[i]))
    assert order_geodesic == order_inner


# ── 2. Product-Manifold Metric & Triangle Inequality ─────────────────────────

def test_product_manifold_metric_axioms_and_triangle_inequality():
    """Verify d_M satisfies identity, symmetry, and triangle inequality over 250 random triples."""
    rng = random.Random(20261022)

    def _rand_node(idx: int):
        px = rng.uniform(-0.65, 0.65)
        py = rng.uniform(-0.65, 0.65)
        lor = lkb.poincare_to_lorentz([px, py])
        angle = rng.uniform(0.0, 2.0 * math.pi)
        sph = [math.cos(angle), math.sin(angle)]
        euc = lkb.compute_euclidean_embedding(f"node_{idx} token_{idx % 7}", kind="tool", ring=(idx % 3))
        return {"lorentz_vec": lor, "spherical_vec": sph, "euclidean_vec": euc}

    nodes = [_rand_node(i) for i in range(40)]
    for n in nodes[:10]:
        assert math.isclose(lkb.product_manifold_distance(n, n), 0.0, abs_tol=1e-9)

    for _ in range(250):
        a, b, c = rng.sample(nodes, 3)
        dab = lkb.product_manifold_distance(a, b, weights=(1.0, 0.5, 0.5))
        dba = lkb.product_manifold_distance(b, a, weights=(1.0, 0.5, 0.5))
        dbc = lkb.product_manifold_distance(b, c, weights=(1.0, 0.5, 0.5))
        dac = lkb.product_manifold_distance(a, c, weights=(1.0, 0.5, 0.5))
        assert math.isclose(dab, dba, rel_tol=1e-12, abs_tol=1e-12)
        assert dac <= dab + dbc + 1e-10


# ── 3. Unstructured Code AST & Markdown Section Chunking ─────────────────────

def test_unstructured_ast_and_markdown_chunking(tmp_path: Path):
    """Verify Python AST symbols and Markdown headings are extracted with exact line spans & SHA-256."""
    py_file = tmp_path / "sample_tool.py"
    py_source = (
        '"""Sample tool module."""\n\n'
        "class EngineRunner:\n"
        '    """Executes multi-wave plans."""\n'
        "    def run(self):\n"
        "        return 42\n\n"
        "def compute_metric(x, y):\n"
        '    """Compute hyperbolic metric."""\n'
        "    return x + y\n"
    )
    py_file.write_text(py_source, encoding="utf-8")

    symbols = lkb.extract_python_ast_symbols(py_file)
    assert len(symbols) == 2
    assert symbols[0]["name"] == "EngineRunner"
    assert symbols[0]["start_line"] == 3
    assert symbols[0]["end_line"] == 6
    excerpt_0 = "\n".join(py_source.splitlines()[2:6])
    assert symbols[0]["sha256"] == hashlib.sha256(excerpt_0.encode("utf-8")).hexdigest()

    assert symbols[1]["name"] == "compute_metric"
    assert symbols[1]["start_line"] == 8
    assert symbols[1]["end_line"] == 10

    md_file = tmp_path / "SKILL.md"
    md_source = (
        "# Alpha Skill\n"
        "Primary overview of Alpha.\n\n"
        "## Stage 1 Intake\n"
        "Lock the North Star and verify scope.\n\n"
        "## Stage 2 Execution\n"
        "Run the deterministic verification gate.\n"
    )
    md_file.write_text(md_source, encoding="utf-8")

    sections = lkb.extract_markdown_sections(md_file)
    assert len(sections) == 3
    assert sections[0]["title"] == "Alpha Skill"
    assert sections[1]["title"] == "Stage 1 Intake"
    assert "North Star" in sections[1]["summary"]
    assert sections[2]["title"] == "Stage 2 Execution"


# ── 4. Hermetic & Full 19-Skill Ecosystem Ingestion + Hybrid Search + Logging ─

def test_hermetic_skill_ingestion_hybrid_query_and_logging(tmp_path: Path):
    """Test full LibrarianKB lifecycle in a hermetic temp workspace."""
    skill_dir = tmp_path / "anvil"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Anvil Codebase Comprehension\n"
        "Programmatic 3-level abstraction mapping and LibCST remapping.\n\n"
        "## Null Space Verification\n"
        "Verify zero behavioral drift during refactoring.\n",
        encoding="utf-8",
    )
    (skill_dir / "HUMAN.md").write_text(
        "# Anvil Human Guide\nOne-sentence purpose: deep codebase comprehension.\n",
        encoding="utf-8",
    )
    (skill_dir / "remap_engine.py").write_text(
        '"""AST remapping tool."""\n'
        "def verify_null_space(ast_tree):\n"
        '    """Deterministic AST invariant check."""\n'
        "    return True\n",
        encoding="utf-8",
    )
    jdir = skill_dir / "journal"
    jdir.mkdir()
    (jdir / "0001-libcst-edge-case.md").write_text(
        "# Lesson 0001: LibCST Whitespace Preservation\n"
        "Always preserve trailing comments on function decorators.\n",
        encoding="utf-8",
    )

    db_file = tmp_path / "test_librarian.sqlite3"
    kb = lkb.LibrarianKB(db_path=db_file)
    stats = kb.ingest_skill_ecosystem(tmp_path)

    assert stats["skills_ingested"] == 1
    assert stats["nodes_ingested"] >= 7
    assert stats["edges_ingested"] >= 6

    # Check ecosystem map contains skill, tool, peer_skill, knowledge_source, repository, code_symbol
    eco = kb.poincare_ecosystem_map(skill_id="anvil")
    assert eco["schema"] == "foundry-librarian-ecosystem-map/v1"
    assert eco["geometry_mode"] == "seeded-product-manifold"
    kinds_present = {n["kind"] for n in eco["nodes"]}
    assert "skill" in kinds_present
    assert "tool" in kinds_present
    assert "peer_skill" in kinds_present
    assert "knowledge_source" in kinds_present
    assert "repository" in kinds_present
    assert "code_symbol" in kinds_present

    # Hybrid query with strict token budget
    q_res = kb.query_hybrid("Null Space LibCST AST invariant", skill_id="anvil", token_budget=1200, limit=5)
    assert len(q_res["results"]) >= 1
    assert q_res["tokens_loaded"] <= 1200
    assert q_res["tokens_saved"] > 0

    # Log execution and verify Piaget assimilation updates usage_count and outcome_credit
    log_entry = kb.log_execution(
        skill_id="anvil",
        task_summary="Remap legacy parser with Null Space check",
        tools_used=["remap_engine.py"],
        peer_skills=["gandalf"],
        sources_used=["SKILL.md", "0001-libcst-edge-case"],
        outcome="success",
        run_id="run-test-wave21-001",
        tokens_loaded=q_res["tokens_loaded"],
        tokens_saved=q_res["tokens_saved"],
    )
    assert log_entry["run_id"] == "run-test-wave21-001"
    assert len(log_entry["nodes_accessed"]) >= 3

    logs = kb.get_access_logs(skill_id="anvil")
    assert len(logs) == 1
    assert logs[0]["task_summary"] == "Remap legacy parser with Null Space check"

    # Re-fetch ecosystem map: geometry_mode upgrades to assimilated-usage-weighted
    eco_after = kb.poincare_ecosystem_map(skill_id="anvil", focus_node_id="skill:anvil")
    assert eco_after["geometry_mode"] == "assimilated-usage-weighted"
    assert eco_after["logged_runs"] == 1
    root_node = next(n for n in eco_after["nodes"] if n["node_id"] == "skill:anvil")
    assert root_node["usage_count"] == 1
    assert root_node["success_count"] == 1
    assert root_node["outcome_credit"] > 0.5
    assert math.isclose(root_node["display_x"], 0.0, abs_tol=1e-6)
    assert math.isclose(root_node["display_y"], 0.0, abs_tol=1e-6)


def test_canonical_19_skills_ingestion(tmp_path: Path):
    """Verify `ingest_skill_ecosystem()` discovers and indexes all 19 canonical Foundry skills."""
    db_file = tmp_path / "canonical_19.sqlite3"
    kb = lkb.LibrarianKB(db_path=db_file)
    stats = kb.ingest_skill_ecosystem()
    assert stats["skills_ingested"] == 19
    assert stats["nodes_ingested"] >= 150
    assert stats["edges_ingested"] >= 150

    full_map = kb.poincare_ecosystem_map()
    assert full_map["kind_counts"]["skill"] == 19
    assert full_map["kind_counts"]["tool"] >= 15
    assert full_map["kind_counts"]["peer_skill"] >= 10
    assert full_map["kind_counts"]["knowledge_source"] >= 30
    assert full_map["kind_counts"]["repository"] == 19


def test_ensure_populated_seeds_19_skills_and_activity_logs(tmp_path: Path):
    """Verify `ensure_populated()` idempotently ingests all 19 skills and seeds initial activity logs."""
    db_file = tmp_path / "seeded_19.sqlite3"
    kb = lkb.LibrarianKB(db_path=db_file)
    kb.ensure_populated(seed_activity=True)
    logs = kb.get_access_logs(limit=20)
    assert len(logs) >= 7
    rp_map = kb.poincare_ecosystem_map(skill_id="researchprime")
    assert rp_map["geometry_mode"] == "assimilated-usage-weighted"
    assert rp_map["logged_runs"] >= 1


# ── 5. Higher-Dimensional Poincare Sphere (B^3 / B^d) & Orthogonal Task Subspaces ─

def test_3d_and_nd_lorentz_poincare_isometry_and_boost_recenter():
    """Verify stereographic round-trip, geodesic distance isometry, and Lorentz boost
    recentering across 3D spheres (B^3 <-> L^3) and d-dimensional balls (d in {3, 4, 8, 16})."""
    rng = random.Random(20261022 + 3)
    for d in (3, 4, 8, 16):
        pts_poincare = []
        for _ in range(12):
            raw = [rng.gauss(0.0, 1.0) for _ in range(d)]
            norm = math.sqrt(sum(c * c for c in raw)) or 1.0
            radius = rng.uniform(0.08, 0.84)
            pts_poincare.append([c / norm * radius for c in raw])

        lorentz_pts = [lkb.poincare_to_lorentz(z, kappa=1.0) for z in pts_poincare]
        for z, x in zip(pts_poincare, lorentz_pts):
            assert len(x) == d + 1
            assert x[0] >= 1.0
            assert math.isclose(lkb.lorentz_inner(x, x), -1.0, rel_tol=1e-11, abs_tol=1e-11)
            z_back = lkb.lorentz_to_poincare(x, kappa=1.0)
            assert len(z_back) == d
            assert sum(c * c for c in z_back) < 1.0
            for a, b in zip(z, z_back):
                assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)

        # Verify pairwise distance isometry between B^d and L^d and under Lorentz boost recentering
        focus_x = lorentz_pts[0]
        boosted_origin = lkb.lorentz_boost_recenter(focus_x, focus_x, kappa=1.0)
        assert math.isclose(boosted_origin[0], 1.0, rel_tol=1e-9, abs_tol=1e-9)
        for coord in boosted_origin[1:]:
            assert math.isclose(coord, 0.0, abs_tol=1e-9)

        for i in range(len(pts_poincare)):
            for j in range(i + 1, len(pts_poincare)):
                u, v = pts_poincare[i], pts_poincare[j]
                xu, xv = lorentz_pts[i], lorentz_pts[j]
                d_lor = lkb.lorentz_distance(xu, xv, kappa=1.0)

                u_sq = sum(c * c for c in u)
                v_sq = sum(c * c for c in v)
                diff_sq = sum((a - b) ** 2 for a, b in zip(u, v))
                d_poin = math.acosh(1.0 + 2.0 * diff_sq / ((1.0 - u_sq) * (1.0 - v_sq)))
                assert math.isclose(d_lor, d_poin, rel_tol=1e-9, abs_tol=1e-9)

                # Boost both xu and xv by focus_x and verify distance invariance
                xu_b = lkb.lorentz_boost_recenter(xu, focus_x, kappa=1.0)
                xv_b = lkb.lorentz_boost_recenter(xv, focus_x, kappa=1.0)
                d_boosted = lkb.lorentz_distance(xu_b, xv_b, kappa=1.0)
                assert math.isclose(d_lor, d_boosted, rel_tol=1e-9, abs_tol=1e-9)


def test_lorentz_project_subspace_sheet_and_geodesic_modes():
    """Verify `lorentz_project_subspace` preserves the hyperboloid constraint, projects
    into open Poincare disks/spheres, and decouples orthogonal depths in `sheet` mode."""
    # 6D point in B^6 -> L^6
    z6 = [0.25, -0.30, 0.40, 0.15, -0.35, 0.20]
    x6 = lkb.poincare_to_lorentz(z6, kappa=1.0)

    for slice_axes in ((0, 1), (2, 3), (0, 2, 4)):
        proj_sheet = lkb.lorentz_project_subspace(x6, slice_axes, kappa=1.0, mode="sheet")
        proj_geo = lkb.lorentz_project_subspace(x6, slice_axes, kappa=1.0, mode="geodesic")

        assert len(proj_sheet) == len(slice_axes) + 1
        assert len(proj_geo) == len(slice_axes) + 1
        assert math.isclose(lkb.lorentz_inner(proj_sheet, proj_sheet), -1.0, rel_tol=1e-11, abs_tol=1e-11)
        assert math.isclose(lkb.lorentz_inner(proj_geo, proj_geo), -1.0, rel_tol=1e-11, abs_tol=1e-11)

        p_sheet = lkb.lorentz_to_poincare(proj_sheet, kappa=1.0)
        p_geo = lkb.lorentz_to_poincare(proj_geo, kappa=1.0)
        assert sum(c * c for c in p_sheet) < 1.0
        assert sum(c * c for c in p_geo) < 1.0


def test_3d_poincare_sphere_embedding_and_query_orthogonal_task(tmp_path: Path):
    """Verify 3D Poincare sphere coordinates (`poincare_3d`, `lorentz_3d`) and
    task-phase selective retrieval (`query_orthogonal_task`) across task stages."""
    skill_dir = tmp_path / "aegis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Aegis Security Scanner\n"
        "Intake and scope framing for AST taint and CWE vulnerability scanning.\n\n"
        "## Verification Gate\n"
        "Adversarial cross-family review and regression test verification.\n",
        encoding="utf-8",
    )
    (skill_dir / "taint_scanner.py").write_text(
        '"""AST taint analysis execution engine."""\n'
        "def compute_taint_flow(ast_node):\n"
        '    """Execute deterministic AST sink taint propagation."""\n'
        "    return []\n",
        encoding="utf-8",
    )
    jdir = skill_dir / "journal"
    jdir.mkdir()
    (jdir / "0001-ssrf-remediation-report.md").write_text(
        "# SSRF Deliverable Report\nEmitted final remediation receipt and summary.\n",
        encoding="utf-8",
    )

    db_file = tmp_path / "test_3d_orthogonal.sqlite3"
    kb = lkb.LibrarianKB(db_path=db_file)
    kb.ingest_skill_ecosystem(tmp_path)

    eco = kb.poincare_ecosystem_map(skill_id="aegis", focus_node_id="skill:aegis", slice_axes=(0, 2))
    assert eco["slice_axes"] == [0, 2]
    for node in eco["nodes"]:
        p3 = node["poincare_3d"]
        l3 = node["lorentz_3d"]
        p2_slice = node["poincare_slice_2d"]
        assert len(p3) == 3
        assert len(l3) == 4
        assert len(p2_slice) == 2
        assert sum(c * c for c in p3) < 1.0
        assert sum(c * c for c in p2_slice) < 1.0
        assert math.isclose(lkb.lorentz_inner(l3, l3), -1.0, rel_tol=1e-9, abs_tol=1e-9)

    # Verify modality separation along Axis Z (index 2):
    # Knowledge sources sit in northern hemisphere (z > 0), tools/code_symbols in southern hemisphere (z < 0)
    source_nodes = [n for n in eco["nodes"] if n["kind"] == "knowledge_source"]
    tool_nodes = [n for n in eco["nodes"] if n["kind"] in ("tool", "code_symbol")]
    assert all(n["poincare_3d"][2] > 0.0 for n in source_nodes)
    assert all(n["poincare_3d"][2] < 0.0 for n in tool_nodes)

    # Test query_orthogonal_task across different task phases and 2D slice planes
    res_compute = kb.query_orthogonal_task(
        "AST taint sink analysis",
        task_phase="compute",
        slice_axes=(0, 1),
        skill_id="aegis",
        token_budget=1400,
    )
    assert res_compute["task_phase"] == "compute"
    assert res_compute["slice_axis_names"] == ["domain_hierarchy", "task_phase_axis"]
    assert len(res_compute["results"]) >= 1
    assert res_compute["results"][0]["kind"] in ("tool", "code_symbol")

    res_collaborate = kb.query_orthogonal_task(
        "adversarial review composition",
        task_phase="collaborate",
        slice_axes=(1, 2),
        skill_id="aegis",
        token_budget=1400,
    )
    assert res_collaborate["task_phase"] == "collaborate"
    assert res_collaborate["slice_axis_names"] == ["task_phase_axis", "modality_axis"]
    assert res_collaborate["results"][0]["kind"] == "peer_skill"

    res_ingest = kb.query_orthogonal_task(
        "intake scope framing specification",
        task_phase="ingest",
        slice_axes=(0, 2),
        skill_id="aegis",
        token_budget=1400,
    )
    assert res_ingest["task_phase"] == "ingest"
    assert res_ingest["results"][0]["kind"] == "knowledge_source"


