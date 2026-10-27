import json
import os
import time
from pathlib import Path

from steward_cockpit import foundry_tools, steward_campaign, steward_engine


def test_small_duty_and_foundry_skills_enforce_legal_beagle_gate():
    """Issue 1: Small-duty and Foundry skill instructions must never bypass legal-beagle on statutory/legal edits."""
    assert "legal-beagle" in steward_engine.SMALL_DUTY
    assert "legal-round.mjs" in steward_engine.SMALL_DUTY
    assert "financial-analyst" in steward_engine.SMALL_DUTY
    assert "NEVER optional" in foundry_tools.FOUNDRY_SKILLS_SUMMARY
    assert "legal-round.mjs" in foundry_tools.FOUNDRY_SKILLS_SUMMARY


def test_stale_job_queue_pruning_clears_collected_and_dead_job_messages(tmp_path):
    """Issue 2: Collected job results and stale job observations are pruned so they cannot keep the green status light stuck."""
    camp = tmp_path / "Paper 1"
    ecg = camp / ".ecgberht"
    ecg.mkdir(parents=True)
    jobs_data = {
        "job-done-1": {
            "id": "job-done-1",
            "status": "done",
            "finished": "2026-10-21T16:40:00",
            "handoff": {"state": "collected"},
        },
        "job-live-2": {
            "id": "job-live-2",
            "status": "running",
            "started": "2026-10-23T14:57:44",
            "handoff": {"state": "pending"},
        },
    }
    (ecg / "code-jobs.json").write_text(json.dumps(jobs_data), encoding="utf-8")

    raw_queue = [
        {
            "text": "[job observation attention:job-done-1:silence:100] Background code job `job-done-1` has been silent.",
            "origin": "control",
            "allow_steward_routing": True,
        },
        {
            "text": "[job result job-done-1:done] Code job `job-done-1` finished.",
            "origin": "control",
            "allow_steward_routing": True,
        },
        {
            "text": "[job observation attention:job-live-2:silence:100] Older observation for live job.",
            "origin": "control",
            "allow_steward_routing": True,
        },
        {
            "text": "[job observation attention:job-live-2:silence:200] Newer observation for live job.",
            "origin": "control",
            "allow_steward_routing": True,
        },
        {
            "text": "Human follow-up question from John",
            "origin": "human",
        },
    ]

    filtered = steward_engine._filter_job_queue(str(camp), raw_queue)
    assert len(filtered) == 2
    assert filtered[0]["text"].startswith("[job observation attention:job-live-2:silence:200]")
    assert filtered[1]["text"] == "Human follow-up question from John"


def test_persist_status_table_and_compose_status_active_vs_idle_parity(tmp_path):
    """Issue 3: 10-min status tables in Steward dialogue persist to status_card.json, populate active status,
    and automatically clear in-flight Doing/Procs/ETA countdowns once the job finishes and goes idle."""
    camp = tmp_path / "Campaign"
    ecg = camp / ".ecgberht"
    ecg.mkdir(parents=True)
    (camp / "ECGBERHT.md").write_text("# Campaign\n\n## North Star\nTest goal\n", encoding="utf-8")
    (camp / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_projection": [
                    {"id": "step-1", "name": "Wave 1 Build", "status": "active"},
                    {"id": "step-2", "name": "Wave 2 Verify", "status": "proposed"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (camp / "strip.json").write_text(
        json.dumps({"current_step_id": "step-1", "next_recommended": "Complete Wave 1 -> Run Wave 2"}),
        encoding="utf-8",
    )

    chat_text = (
        "Here is our 10-minute status update:\n\n"
        "```text\n"
        "[14:56] Anvil + Ramanujan build · Paper 1\n"
        "─────────────────────────────────\n"
        "Effort   Unified Srinivas & Anvil Working Report (2 waves)\n"
        "Doing    Running Anvil code job to build fig6 and v4 report\n"
        "Status   1/2 waves · producing & cross-family review\n"
        "Tests    pass ✓ · gaussian_star.py pre-check passed\n"
        "Blocker  none\n"
        "Procs    py 1 · claude 0 · node 1\n"
        "Journal  journal/0019-srinivas-anvil-plan.md\n"
        "─────────────────────────────────\n"
        "ETA      ~12m (produce) -> ~4m (Claude review) -> ~16m total\n"
        "To do    Land v4 report -> register in DELIVERABLES.md\n"
        "```\n"
    )
    assert steward_campaign.persist_status_table_from_text(str(camp), chat_text) is True
    sc_path = ecg / "status_card.json"
    assert sc_path.is_file()
    saved_card = json.loads(sc_path.read_text(encoding="utf-8"))
    assert saved_card["effort"] == "Unified Srinivas & Anvil Working Report (2 waves)"
    assert len(saved_card["milestone_etas"]) == 3

    # 1. While the Steward is busy mid-turn (active run): status_card fields are surfaced in compact.facts and status_card
    now = time.time()
    active_status = steward_campaign.compose_status(
        str(camp),
        engine_state={"busy": True, "turn_started": now - 120, "activity": "Running Anvil wave"},
    )
    active_facts = {row["label"]: row["value"] for row in active_status["compact"]["facts"]}
    assert "Unified Srinivas & Anvil Working Report" in active_facts["Effort"]
    assert "Running Anvil code job" in active_facts["Doing"]
    assert "1/2 waves" in active_facts["Status"]
    assert "gaussian_star.py" in active_facts["Tests"]
    assert active_facts["Procs"] == "py 1 · claude 0 · node 1"
    assert active_facts["Journal"] == "journal/0019-srinivas-anvil-plan.md"
    assert active_status["status_card"]["eta"] == "~12m (produce) -> ~4m (Claude review) -> ~16m total"

    # 2. Once the job finishes AFTER status_card.json was written and the cockpit is idle:
    # stale in-flight Doing, Procs, ETA, and milestone_etas are NOT carried into the idle state.
    os.utime(sc_path, (now - 300, now - 300))
    (ecg / "code-jobs.json").write_text(
        json.dumps(
            {
                "job-1": {
                    "id": "job-1",
                    "status": "done",
                    "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 240)),
                    "finished": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 60)),
                }
            }
        ),
        encoding="utf-8",
    )
    idle_status = steward_campaign.compose_status(str(camp), engine_state={"busy": False})
    idle_facts = {row["label"]: row["value"] for row in idle_status["compact"]["facts"]}
    assert idle_facts["Doing"].startswith("Nobody is working right now")
    assert idle_facts["Status"] == "idle"
    assert idle_facts["ETA"] == "nothing running, so nothing to finish"
    assert idle_status["status_card"]["doing"] == "Idle — waiting for your input"
    assert idle_status["status_card"]["eta"] == "Idle (ready for next wave)"
    assert idle_status["status_card"]["milestone_etas"] is None
    # Non-inflight summary fields (Effort, Tests, Journal) remain preserved
    assert "Unified Srinivas & Anvil Working Report" in idle_facts["Effort"]
    assert "gaussian_star.py" in idle_facts["Tests"]
    assert idle_facts["Journal"] == "journal/0019-srinivas-anvil-plan.md"


def test_shared_js_does_not_poison_latest_status_id_or_treat_none_kind_as_running():
    """Frontend invariants in shared.js: chat-routed tables do not poison latestStatusId,
    run.kind === 'none'/'finished' is not treated as running, and syncCompactActivity refreshes Milestone ETAs."""
    shared_js = (Path(steward_engine.HERE) / "static" / "shared.js").read_text(encoding="utf-8")
    assert 'if (latestStatusId && latestStatusId.startsWith("chat-routed-")) latestStatusId = "";' in shared_js
    assert 'if (statusId && !statusId.startsWith("chat-routed-")) latestStatusId = statusId;' in shared_js
    assert "!/^(?:none|finished|halted|stopped|idle)$/.test(runKind)" in shared_js
    assert 'if (typeof renderStatus._lastRefreshEta === "function")' in shared_js


def test_compute_milestone_eta_parts_live_vs_idle_transition():
    """Execute computeMilestoneEtaParts from shared.js in Node to prove that:
    1) When running (busy: true), a 3-part milestone ETA is displayed live.
    2) When the run finishes and lastState flips to {busy: false, working_bg: false} (or run.kind === 'none'),
       stale countdowns ('~12m -> ~4m -> ~16m', '~2m for review', 'complete') are NOT stuck as 'Active wave'
       and instead transition cleanly to 'Ready now' / 'Ready for your review'."""
    import subprocess
    shared_js_path = Path(steward_engine.HERE) / "static" / "shared.js"
    js_src = shared_js_path.read_text(encoding="utf-8")
    start_marker = "const computeMilestoneEtaParts = (val) => {"
    end_marker = "    // 3-part milestone ETA: 1. Current step"
    fn_block = js_src[js_src.index(start_marker):js_src.index(end_marker)].strip()

    node_script = f"""
const assert = require("assert");
const oneLine = (s, n) => String(s || "").slice(0, n || 200);
const cleanTodoPhrase = (s) => String(s || "").trim();
const isNow = (st) => st && st.status === "active";
const stepNeedsAttention = (st) => Boolean(st && st.waiting_on_you);
const stepDone = (st) => Boolean(st && st.status === "done");
const factValue = (lbl, fb) => fb;

let _lastMap = {{
  steps_done: 1,
  steps_total: 2,
  heartbeat: {{ current_step_id: "w1" }},
  steps: [
    {{ id: "w1", name: "Wave 1 Build", status: "active" }},
    {{ id: "w2", name: "Wave 2 Verify", status: "proposed" }}
  ]
}};
let renderedAtMs = Date.now();
let sl = {{ name: "Wave 1 Build" }};
let p = {{ step: "Wave 1 Build", steps_done: 1, steps_total: 2, next: "Wave 2 Verify" }};
let bullets = ["Wave 1 Build", "Wave 2 Verify"];
let run = {{ kind: "code_job", label: "Anvil producing (5 min)" }};
let doingLine = "Running Anvil code job (5 min)";
let lastState = {{ busy: true, working_bg: true }};
let stat = {{
  status_card: {{
    eta: "~12m (produce) -> ~4m (Claude review) -> ~16m total"
  }}
}};

{fn_block}

// 1. While actively running: 3-part -> string is used
const activeParts = computeMilestoneEtaParts("~12m (produce) -> ~4m (Claude review) -> ~16m total");
assert.strictEqual(activeParts[0].v, "~12m (produce)");
assert.strictEqual(activeParts[1].v, "~4m (Claude review)");
assert.strictEqual(activeParts[2].v, "~16m total");

// 2. When lastState flips to idle, even before a new /api/status arrives:
// computeMilestoneEtaParts must NOT stay stuck on '~12m (produce)' or 'Active wave'!
lastState = {{ busy: false, working_bg: false }};
const unstuckParts = computeMilestoneEtaParts("~12m (produce) -> ~4m (Claude review) -> ~16m total");
assert(unstuckParts[0].v.startsWith("Ready now"), "Expected Ready now, got: " + unstuckParts[0].v);
assert(!unstuckParts[0].v.includes("Active wave"), "Must not show Active wave when idle: " + unstuckParts[0].v);

// 3. When stat has run.kind === 'none' and a stale countdown '~2m for cross-family review and landing' or 'complete':
lastState = null;
run = {{ kind: "none", label: "nothing running - quiet" }};
doingLine = "Nobody is working right now";
const idleSingleCountdown = computeMilestoneEtaParts("~2m for cross-family review and landing");
assert(idleSingleCountdown[0].v.startsWith("Ready now"), "Expected Ready now, got: " + idleSingleCountdown[0].v);
const idleComplete = computeMilestoneEtaParts("complete");
assert(idleComplete[0].v.startsWith("Ready now"), "Expected Ready now, got: " + idleComplete[0].v);
console.log("ALL_NODE_ASSERTIONS_PASSED");
"""
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"
    assert "ALL_NODE_ASSERTIONS_PASSED" in res.stdout


def test_docx_redline_tool_runs_legal_beagle_sources_gate(tmp_path):
    """Issue 1 (Wave 3): docx-redline --sources runs legal-beagle citation gate on produced .docx and fails closed on ungrounded citations."""
    import subprocess
    import sys

    md_file = tmp_path / "draft.md"
    md_file.write_text(
        "# Trust Notice\n\nUnder Utah Code § 75B-1-306, the settlor exercises a power.\n",
        encoding="utf-8",
    )
    src_pack = tmp_path / "sources.md"
    src_pack.write_text("# Official Utah Code Pack\n\n75B-1-301 through 75B-1-304 only.\n", encoding="utf-8")
    out_docx = tmp_path / "draft.docx"

    res = subprocess.run(
        [
            sys.executable,
            r"C:\dev\foundry-tools\docx-redline\tool.py",
            "--from-md",
            str(md_file),
            "--out",
            str(out_docx),
            "--sources",
            str(src_pack),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode != 0
    assert "token-level 1 ungrounded" in (res.stdout + res.stderr)
    assert "citation gate FAILED" in (res.stdout + res.stderr)


def test_deliverables_most_relevant_up_front_and_scoped_feedback_reconcile(tmp_path):
    """Deliverables formula surfaces the most relevant current deliverables up front, supersedes Initial draft
    when Refinement N exists, filters historical receipts and month-old featured_paths, and scopes feedback
    reconciliation so feedback on Lecture 5 never wipes out unrelated review items (LEM Lab Quiz, Lecture 7)."""
    camp = tmp_path / "Course"
    camp.mkdir()
    (camp / "ECGBERHT.md").write_text("# Course\n\n## North Star\nCourse materials\n", encoding="utf-8")
    (camp / "old_sept_spec.md").write_text("# Sept Spec\n", encoding="utf-8")
    (camp / "keep-or-sell-initial-draft.pdf").write_text("v0", encoding="utf-8")
    (camp / "keep-or-sell-refinement-2.pdf").write_text("v2", encoding="utf-8")
    (camp / "lem-lab-guide.pdf").write_text("quiz", encoding="utf-8")
    (camp / "lecture-7-refinement-1.pdf").write_text("lec7", encoding="utf-8")
    (camp / "hist-receipt.md").write_text("hist", encoding="utf-8")

    (camp / "roadmap.json").write_text(
        json.dumps(
            {
                "roadmap_projection": [
                    {
                        "id": "s1",
                        "name": "Course Deliverables",
                        "status": "waiting",
                        "waiting_on": "John review",
                        "navigation": {
                            "path": ["course"],
                            "pin": True,
                            "current": True,
                            "featured_paths": ["old_sept_spec.md"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (camp / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n| What | Where | Date | Step |\n| --- | --- | --- | --- |\n"
        "| START HERE - FOR REVIEW: Smeal LEM Lab Quiz Sign-Up Guide | `lem-lab-guide.pdf` | 2026-10-23 | s1 |\n"
        "| START HERE - FOR REVIEW: Lecture 7 — Refinement 1 | `lecture-7-refinement-1.pdf` | 2026-10-22 | s1 |\n"
        "| Keep or sell, Initial draft — PDF reading copy | `keep-or-sell-initial-draft.pdf` | 2026-09-29 | s1 |\n"
        "| Keep or sell, Refinement 2 — PDF reading copy | `keep-or-sell-refinement-2.pdf` | 2026-09-29 | s1 |\n"
        "| Existing July onboarding completion receipt — historical | `hist-receipt.md` | 2026-10-23 | s1 |\n"
        "| Earlier September Spec | `old_sept_spec.md` | 2026-09-18 | s1 |\n",
        encoding="utf-8",
    )

    d = steward_campaign.read_deliverables(str(camp))
    cur_paths = [it["path"] for it in d["items"] if it.get("is_current")]
    assert "lem-lab-guide.pdf" in cur_paths
    assert "lecture-7-refinement-1.pdf" in cur_paths
    assert "keep-or-sell-initial-draft.pdf" not in cur_paths
    assert "hist-receipt.md" not in cur_paths
    assert "old_sept_spec.md" not in cur_paths

    # Giving feedback specifically about Lecture 5 must NOT dismiss LEM Lab Quiz or Lecture 7!
    rec_lec5 = steward_campaign.reconcile_review_on_feedback(
        str(camp),
        "Can I get some feedback on lecture 5? Slide 8 needs a third panel and homework 3 needs to be updated.",
    )
    assert rec_lec5["ok"] is True
    assert rec_lec5["reconciled"] == 0
    d_after_lec5 = steward_campaign.read_deliverables(str(camp))
    cur_after_lec5 = [it["path"] for it in d_after_lec5["items"] if it.get("is_current")]
    assert "lem-lab-guide.pdf" in cur_after_lec5
    assert "lecture-7-refinement-1.pdf" in cur_after_lec5

    # Giving feedback specifically about Lecture 7 reconciles ONLY Lecture 7, keeping LEM Lab Quiz in review!
    rec_lec7 = steward_campaign.reconcile_review_on_feedback(
        str(camp),
        "Lecture 7 looks good, approve Lecture 7 and move on.",
    )
    assert rec_lec7["ok"] is True
    assert rec_lec7["reconciled"] == 1
    d_after_lec7 = steward_campaign.read_deliverables(str(camp))
    cur_after_lec7 = [it["path"] for it in d_after_lec7["items"] if it.get("is_current")]
    assert "lem-lab-guide.pdf" in cur_after_lec7
    assert "lecture-7-refinement-1.pdf" not in cur_after_lec7


