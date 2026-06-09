#!/usr/bin/env python3
"""Anchor lane wiring — research / plan / build → skill + seed + output path.

Wave 6 of the R&D control surface. A *lane* is the frozen mapping (MASTER-PLAN
"Lanes & concurrency" + locked decision D1):

    research = researchPrime skill — runs to completion, NO gate; project-scoped
               output; non-mutating.
    plan     = crucible skill — doc-producing, project-scoped; gates in-session;
               non-mutating.
    build    = foreman skill — MUTATES the shared working tree; gates in-session.

Per D1 there is ONE uniform job primitive: a ``claude -p`` stream-json
subprocess running the relevant skill in the project cwd, owned by the Anchor
server. A lane therefore only contributes three things: (1) which skill, (2) a
prompt-seed template, and (3) the project-scoped output subdir. There is no
per-lane orchestration code — the runner (``job_runner``) is uniform and, in the
gate/tests, is indirected through ``ANCHOR_RUNNER_CMD`` → ``tests/fake_claude.py``
so live ``claude`` is NEVER invoked and no real billing occurs.

The keystone invariant (AC1): Anchor passes the **per-project output path**
``<folder>/.anchor/projects/<id>/<lane-subdir>/`` INTO the engine so engine-native
artifacts land in the project's namespace — **never the folder root**. Because
multiple projects may share a folder (D5), this is what keeps their efforts from
colliding. ``launch_lane`` resolves the project from ``rnd_registry``, computes
that path, scaffolds it, records a launch pointer-record there (so the effort is
demonstrably recorded under the project namespace on disk), builds the prompt
seed, and launches via ``job_runner.launch_guarded`` — which encodes the
concurrency policy (within-project same-lane serialized + cross-lane concurrent;
across-folder builds serialized by the folder-build lock).

Stdlib only. No third-party imports.
"""

import json
import time
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd
import job_runner as _jr

# ── Lane definitions (the frozen mapping) ───────────────────────────────────

#: The three R&D lanes that drive the trio. (``deliverables`` is a Wave-9 lane,
#: not part of the research→plan→build trio wired here.)
LANE_RESEARCH = "research"
LANE_PLAN = "plan"
LANE_BUILD = "build"

#: Skill identifiers invoked via the uniform ``claude -p`` primitive (D1).
SKILL_RESEARCH = "researchPrime"
SKILL_PLAN = "crucible"
SKILL_BUILD = "foreman"


class LaneDef:
    """A lane's frozen wiring: skill + output subdir + gate flag + seed template.

    ``output_subdir`` is the per-project store subdirectory the engine writes
    into (matches ``rnd_registry.LANE_DIRS`` naming: research/planning/build).
    ``gates`` is True for plan/build (they surface an in-session ``AskUserQuestion``
    gate handled by ``gate_adapter``) and False for research (runs to completion).
    ``mutates_tree`` is True only for build (foreman), which is why build is the
    folder-level-serialized lane.
    """

    __slots__ = ("lane", "skill", "output_subdir", "gates", "mutates_tree",
                 "seed_template")

    def __init__(self, lane, skill, output_subdir, gates, mutates_tree,
                 seed_template):
        self.lane = lane
        self.skill = skill
        self.output_subdir = output_subdir
        self.gates = gates
        self.mutates_tree = mutates_tree
        self.seed_template = seed_template


# Prompt-seed templates per lane. These are a reasonable, stated choice (the
# frozen plan leaves the exact seed text to the implementer; the testable
# invariant is the correct skill identifier + per-project output path). Each
# seed instructs the skill to write its effort into the project-scoped output
# directory — reinforcing that artifacts land in the project namespace, not the
# folder root — and states the gate posture (research runs to completion; plan/
# build answer their gate in-session).
_SEED_RESEARCH = (
    "Run the researchPrime skill for project {name!r} (folder {folder}). "
    "Write all research artifacts under the project-scoped output directory "
    "{output_dir}. This lane runs to completion with no interactive gate; do "
    "not mutate the working tree. "
    "If the folder {folder} already contains a project or codebase, treat this as "
    "a brownfield investigation: first inventory what already exists (source "
    "layout, dependencies, build/test setup, docs) and what has already been done "
    "(prior research, plans, partial builds, TODOs), then produce a research "
    "report that orients a brand-new owner — what the project is, its current "
    "state, what's done vs. outstanding, and the key risks/unknowns to resolve "
    "before further work."
)
_SEED_PLAN = (
    "Run the crucible planning skill for project {name!r} (folder {folder}). "
    "Write the plan documents under the project-scoped output directory "
    "{output_dir}. When you reach an AskUserQuestion gate, surface it; an answer "
    "will arrive in-session. Do not mutate the working tree. "
    "Treat this as a brownfield existing project: before planning, assess the "
    "current state of the folder {folder} and what has already been done across "
    "any prior research, planning, and build efforts (including artifacts already "
    "in {output_dir} and sibling lane directories). Then forge a vetted, "
    "gold-standard, Foreman-ready plan that takes the project from its current "
    "state to completion, so the user can hand it off and take over."
)
_SEED_BUILD = (
    "Run the foreman build skill for project {name!r} (folder {folder}). "
    "Record build status/checkpoints under the project-scoped output directory "
    "{output_dir}. You MAY mutate the shared working tree at {folder}; only one "
    "build runs per folder at a time. Answer any AskUserQuestion gate in-session. "
    "This is a brownfield build: continue from the existing plan and current "
    "project state rather than starting from scratch — read the latest plan in "
    "{output_dir} (and the project's research/planning lane outputs) and resume "
    "the remaining work toward completion."
)

#: The frozen lane registry. Keyed by the trio lane name.
LANES = {
    LANE_RESEARCH: LaneDef(
        LANE_RESEARCH, SKILL_RESEARCH, "research",
        gates=False, mutates_tree=False, seed_template=_SEED_RESEARCH,
    ),
    LANE_PLAN: LaneDef(
        LANE_PLAN, SKILL_PLAN, "planning",
        gates=True, mutates_tree=False, seed_template=_SEED_PLAN,
    ),
    LANE_BUILD: LaneDef(
        LANE_BUILD, SKILL_BUILD, "build",
        gates=True, mutates_tree=True, seed_template=_SEED_BUILD,
    ),
}

#: Name of the launch pointer-record written into the project-scoped output dir
#: at launch time, so the effort is demonstrably recorded under the project
#: namespace (AC1) and a reattaching client/Wave-7 history can find it.
LAUNCH_RECORD_NAME = "launch.pointer.json"


def get_lane(lane: str) -> LaneDef:
    """Return the :class:`LaneDef` for a lane name, or raise ``KeyError``."""
    return LANES[lane]


# ── Output-path resolution (project-scoped, never folder root) ──────────────

def lane_output_dir(folder_path, project_id: str, lane: str) -> Path:
    """Resolve ``<folder>/.anchor/projects/<id>/<lane-subdir>/`` (not created).

    Uses the project store dir from ``rnd_registry`` so it stays in lockstep
    with the scaffold. This is the path passed INTO the engine — guaranteeing
    artifacts land in the project namespace, NOT the folder root.
    """
    subdir = get_lane(lane).output_subdir
    return _rnd.project_store_dir(folder_path, project_id) / subdir


# ── Prompt seed ─────────────────────────────────────────────────────────────

def build_prompt_seed(lane: str, project: dict, output_dir) -> str:
    """Render the lane's prompt-seed template for a concrete project + output dir."""
    ld = get_lane(lane)
    return ld.seed_template.format(
        name=project.get("name", ""),
        folder=project.get("folder_path", ""),
        output_dir=str(output_dir),
    )


# ── Runner extra-args (skill + output path passed to the engine) ────────────

def build_extra_args(lane: str, output_dir, prompt_seed: str) -> list:
    """Assemble the argv tail handed to the uniform runner.

    Carries the lane's **skill identifier**, the **project-scoped output path**,
    and the **prompt seed** — the three things a lane contributes on top of the
    uniform ``claude -p`` primitive. (The mock runner tolerates these via
    ``parse_known_args``; a real ``claude`` invocation consumes the skill flag +
    the stream-json prompt. The testable invariant is that the correct skill id
    and per-project output path are present.)
    """
    ld = get_lane(lane)
    return [
        "--skill", ld.skill,
        "--output-dir", str(output_dir),
        "--prompt-seed", prompt_seed,
    ]


# ── Launch a lane ───────────────────────────────────────────────────────────

def _write_launch_record(output_dir: Path, project_id: str, lane: str,
                         job_id: str, skill: str, prompt_seed: str) -> Path:
    """Persist a small launch pointer-record into the project-scoped output dir.

    This is what makes "the effort is recorded under .anchor/projects/<id>/<lane>/"
    observable on disk (AC1): the record lands in the project namespace, never
    the folder root. It is a lightweight JSON pointer-record (the heavy engine
    artifacts are written by the engine itself into the same dir under a real
    ``claude``; under the mock runner this stub stands in for that on-disk
    presence). Written under ``paths.WRITE_LOCK``.
    """
    with _paths.WRITE_LOCK:
        output_dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "job_id": job_id,
            "project_id": project_id,
            "lane": lane,
            "skill": skill,
            "prompt_seed": prompt_seed,
            "output_dir": str(output_dir),
            "launched_at": time.time(),
        }
        p = output_dir / LAUNCH_RECORD_NAME
        p.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return p


def launch_lane(project_id: str, lane: str, env=None, job_id: str = None,
                extra_args=None) -> dict:
    """Launch a trio lane for a registered project under the frozen policy.

    Steps:
    1. Resolve the project from ``rnd_registry`` (raises ``KeyError`` if unknown).
    2. Compute the project-scoped output path
       ``<folder>/.anchor/projects/<id>/<lane-subdir>/`` and scaffold it.
    3. Build the prompt seed + runner extra-args (skill id + output path +
       seed) — i.e. pass the project-scoped output path INTO the engine.
    4. Launch via ``job_runner.launch_guarded``, which enforces:
       within-project same-lane serialized + cross-lane concurrent, and the
       folder-level build lock for the build lane.
    5. Record a launch pointer-record inside the project-scoped output dir so the
       effort is demonstrably under the project namespace (never the folder root).

    Gating: research has no gate (runs to completion); plan/build gate
    in-session — handled by ``gate_adapter`` once the stream surfaces the
    ``AskUserQuestion`` frame (no extra wiring needed here beyond marking the
    lane as gating, which the seed reflects).

    Returns the augmented job record (includes ``skill``, ``output_dir``,
    ``project_id``, ``folder_path``, ``gates``). Raises
    ``job_runner.LaneBusyError`` if the concurrency policy refuses the launch.
    """
    ld = get_lane(lane)
    project = _rnd.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    folder_path = project.get("folder_path", "")

    output_dir = lane_output_dir(folder_path, project_id, lane)
    # Scaffold the per-project store (idempotent) so the lane dir exists.
    _rnd.scaffold_project_store(folder_path, project_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_seed = build_prompt_seed(lane, project, output_dir)
    launch_args = build_extra_args(lane, output_dir, prompt_seed)
    if extra_args:
        launch_args = launch_args + list(extra_args)

    rec = _jr.launch_guarded(
        lane, project_id=project_id, folder_path=folder_path,
        cwd=folder_path or None, extra_args=launch_args, env=env,
        job_id=job_id,
    )
    jid = rec["job_id"]

    # Record the effort under the project namespace (on-disk proof for AC1).
    _write_launch_record(output_dir, project_id, lane, jid, ld.skill,
                         prompt_seed)

    # Augment + persist the record with lane wiring metadata for the UI / Wave 7.
    rec = _jr._update_record(
        jid,
        skill=ld.skill,
        output_dir=str(output_dir),
        gates=ld.gates,
        mutates_tree=ld.mutates_tree,
    )
    return rec
