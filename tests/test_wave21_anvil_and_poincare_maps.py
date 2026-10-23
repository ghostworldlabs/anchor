"""Wave 21 — Anvil 3-Level Programmatic Mapping, Pure-Core/Imperative-Shell
Remapping Proposals, Interactive Step-Through Walkthroughs, and Expanded
Poincaré Knowledge Maps (Material + Tools + Peer Skills + Librarian KB Sources)
across all 19 Skill Foundry skills.
"""
import hashlib
import json
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

import foundry_page as page


EXPECTED_19_SKILLS = {
    "aegis",
    "anvil",
    "chekhov",
    "crucible",
    "einstein",
    "financialanalyst",
    "foreman",
    "gandalf",
    "jumper",
    "legalbeagle",
    "literaturereview",
    "ramanujan",
    "researchprime",
    "steward-portfolio",
    "steward-project",
    "steward-starchart",
    "superjump",
    "tidyidy",
    "zombiehunter",
}


def test_all_19_skills_have_zero_issue_process_and_poincare_maps():
    cat = page.catalog()
    skill_ids = {s["id"] for s in cat["skills"]}
    assert skill_ids == EXPECTED_19_SKILLS, f"Expected 19 skills, got {skill_ids}"

    for s in cat["skills"]:
        sid = s["id"]
        assert s["walkthrough"] == "source-anchored draft", f"{sid} walkthrough should not be unfinished"
        assert s["anvilMapped"] is True, f"{sid} should be anvilMapped"

        detail = page.skill_detail(sid)
        assert detail is not None, f"skill_detail({sid}) returned None"
        assert detail["libraryIssues"] == [], f"{sid} libraryIssues: {detail['libraryIssues']}"

        proc = detail["processMap"]
        assert proc["status"] == "source-anchored draft", f"{sid} processMap status={proc['status']} issues={proc['issues']}"
        assert proc["issues"] == [], f"{sid} processMap issues: {proc['issues']}"
        assert len(proc["steps"]) >= 5, f"{sid} expected >=5 process steps"

        know = detail["knowledgeMap"]
        assert know["status"] == "seeded draft", f"{sid} knowledgeMap status={know['status']} issues={know['issues']}"
        assert know["issues"] == [], f"{sid} knowledgeMap issues: {know['issues']}"
        assert len(know["nodes"]) >= 12, f"{sid} expected >=12 Poincaré nodes, got {len(know['nodes'])}"

        # Verify that the skill's Library and Poincaré map include all 4 categories:
        # material, tools, skills (peer skills), and references (KB sources/journals)
        res_by_id = {str(r["id"]): r for r in detail["resources"]}
        lib_cats = {r.get("category") for r in detail["libraryResources"]}
        assert {"material", "tools", "skills", "references"} <= lib_cats, (
            f"{sid} missing library categories: {lib_cats}"
        )

        node_cats = {
            res_by_id[str(n["resourceId"])].get("category")
            for n in know["nodes"]
            if str(n.get("resourceId")) in res_by_id
        }
        assert {"material", "tools", "skills", "references"} <= node_cats, (
            f"{sid} Poincaré nodes missing categories: {node_cats}"
        )


def test_all_19_skills_have_verified_anvil_3_level_map_remapping_and_walkthrough():
    for sid in sorted(EXPECTED_19_SKILLS):
        detail = page.skill_detail(sid)
        anvil = detail.get("anvilMap")
        assert isinstance(anvil, dict), f"{sid} missing anvilMap"
        assert anvil.get("status") == "verified", f"{sid} anvilMap status={anvil.get('status')}"
        assert anvil.get("schema") == "anvil-skill-map/v1"
        assert anvil.get("skill_id") == sid
        assert anvil.get("total_loc", 0) > 0
        assert anvil.get("ast_functions_count", 0) > 0

        # Parable of the Oranges split
        orange = anvil.get("orange_split") or {}
        assert orange.get("juice_core_modules"), f"{sid} missing juice_core_modules"
        assert orange.get("peel_io_contracts"), f"{sid} missing peel_io_contracts"
        assert orange.get("null_space_candidates"), f"{sid} missing null_space_candidates"

        # Pure-Core / Imperative-Shell Remapping Proposal
        remap = anvil.get("remapping_proposal") or {}
        assert remap.get("current_architecture")
        assert len(remap.get("proposed_functional_core") or []) >= 2
        assert len(remap.get("proposed_imperative_shell") or []) >= 2
        assert remap.get("cognitive_load_reduction_pct", 0) >= 20
        diff = remap.get("before_after_diff_preview") or {}
        assert diff.get("before_code") and diff.get("after_functional_core_code") and diff.get("unified_diff")

        # 3-Level Progressive Abstraction Nodes (INGEST -> COMPUTE -> VERIFY -> EMIT)
        pnodes = anvil.get("progressive_nodes") or []
        assert len(pnodes) >= 4
        stages = [n.get("stage") for n in pnodes]
        assert stages == ["INGEST", "COMPUTE", "VERIFY", "EMIT"]
        for n in pnodes:
            l1 = n.get("level1_summary") or {}
            l2 = n.get("level2_mechanics") or {}
            l3 = n.get("level3_code") or {}
            assert l1.get("purpose") and l1.get("tools_used") and l1.get("peer_skills") and l1.get("kb_sources")
            assert l2.get("subflow_steps") and l2.get("formal_invariant_or_equation") and "<math" in (l2.get("mathml") or "")
            assert l3.get("file_path") and l3.get("original_excerpt") and l3.get("refactored_core_preview")

        # Interactive Step-Through Walkthrough
        frames = anvil.get("interactive_walkthrough") or []
        assert len(frames) >= 5
        for idx, fr in enumerate(frames, 1):
            assert fr.get("step_index") == idx
            assert fr.get("claimed_vs_actual_status") == "ACCURATE"
            assert fr.get("input_state") and fr.get("operation_performed") and fr.get("output_state")
            assert isinstance(fr.get("tools_invoked"), list)
            assert isinstance(fr.get("peer_skills_invoked"), list)
            assert isinstance(fr.get("librarian_kb_reads"), list)
            anchor = fr.get("source_anchor") or {}
            assert anchor.get("href", "").startswith("/foundry/source?")


def test_anvil_workbench_http_and_api_routes_for_skills():
    import anchor_gui

    srv = anchor_gui.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for sid in ("anvil", "researchprime", "gandalf", "crucible", "foreman", "steward-starchart"):
            with urlopen(f"{base_url}/api/foundry/anvil?skill={sid}") as resp:
                assert resp.status == 200
                data = json.load(resp)
                assert data["schema"] == "anvil-skill-map/v1"
                assert data["skill_id"] == sid
                assert data["status"] == "verified"

            with urlopen(f"{base_url}/foundry/anvil?skill={sid}") as resp:
                assert resp.status == 200
                html_text = resp.read().decode("utf-8")
                assert "ANVIL_WORKBENCH_DATA" in html_text
                assert "3-Level Progressive Map" in html_text
                assert "Interactive Step-Through Debugger" in html_text
                assert "Expanded Poincaré Disk" in html_text
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
