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

#: Engine backends. Claude is the default and available on ALL lanes. Gemini is
#: a portable read-only engine available ONLY for the research lane —
#: researchPrime is portable, but Crucible (plan) and Foreman (build) are Claude
#: Code engines Gemini can't run.
BACKEND_CLAUDE = _jr.BACKEND_CLAUDE
BACKEND_GEMINI = _jr.BACKEND_GEMINI
DEFAULT_BACKEND = _jr.DEFAULT_BACKEND

#: The set of (lane, backend) pairs that are allowed. Everything else with a
#: non-claude backend is refused. Claude works on all lanes; gemini only on
#: research.
GEMINI_LANES = frozenset((LANE_RESEARCH,))


class EngineNotAllowedError(ValueError):
    """Raised when an engine backend is not permitted for the requested lane.

    Gemini is offered ONLY for the research lane; plan/build run on Claude
    (Crucible/Foreman are Claude Code engines Gemini can't run). Carries the
    offending ``lane`` and ``backend`` for a clean structured refusal.
    """

    def __init__(self, lane, backend, message=None):
        self.lane = lane
        self.backend = backend
        super().__init__(
            message
            or "Gemini is only available for the Research lane; "
               "Plan/Build run on Claude."
        )


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


# ── Lane → runner gating shape ──────────────────────────────────────────────

def lane_gated_flag(lane: str):
    """Map a lane to the ``gated`` value the runner expects.

    The runner uses ``gated`` to pick the stdin mode + (for claude) the
    permission mode: falsy for the non-gated RESEARCH lane (prompt on argv,
    ``stdin=DEVNULL``); the lane NAME (``"plan"`` / ``"build"``) for a gated lane
    so the runner can pick ``acceptEdits`` (plan: writes docs, non-mutating) vs.
    ``bypassPermissions`` (build: mutates the tree + may run Bash) and open a
    kept-open stdin PIPE for the in-session gate answer.
    """
    ld = get_lane(lane)
    return ld.lane if ld.gates else False


# ── Launch a lane ───────────────────────────────────────────────────────────

def _write_launch_record(output_dir: Path, project_id: str, lane: str,
                         job_id: str, skill: str, prompt_seed: str,
                         backend: str = DEFAULT_BACKEND) -> Path:
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
            "backend": backend,
            "prompt_seed": prompt_seed,
            "output_dir": str(output_dir),
            "launched_at": time.time(),
        }
        p = output_dir / LAUNCH_RECORD_NAME
        p.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return p


def check_engine_allowed(lane: str, backend: str) -> None:
    """Enforce the engine policy: Gemini is research-only; Claude runs anywhere.

    Raises :class:`EngineNotAllowedError` if ``backend == "gemini"`` and ``lane``
    is not the research lane. Claude (the default) is always allowed.
    """
    if backend == BACKEND_GEMINI and lane not in GEMINI_LANES:
        raise EngineNotAllowedError(lane, backend)


def launch_lane(project_id: str, lane: str, env=None, job_id: str = None,
                extra_args=None, backend=DEFAULT_BACKEND) -> dict:
    """Launch a trio lane for a registered project under the frozen policy.

    Steps:
    1. Resolve the project from ``rnd_registry`` (raises ``KeyError`` if unknown).
    2. Enforce the engine policy: Claude (default) runs on all lanes; Gemini is
       allowed ONLY on the research lane (``EngineNotAllowedError`` otherwise).
    3. Compute the project-scoped output path
       ``<folder>/.anchor/projects/<id>/<lane-subdir>/`` and scaffold it.
    4. Build the prompt seed + runner extra-args (skill id + output path +
       seed) — i.e. pass the project-scoped output path INTO the engine.
    5. Launch via ``job_runner.launch_guarded`` (threading ``backend`` through to
       the runner), which enforces: within-project same-lane serialized +
       cross-lane concurrent, and the folder-level build lock for the build lane.
    6. Record a launch pointer-record inside the project-scoped output dir so the
       effort is demonstrably under the project namespace (never the folder root).

    ``backend`` ∈ {"claude","gemini"} (default "claude") selects the engine. The
    chosen engine is recorded on both the job record and the launch
    pointer-record so the UI/history can show which engine ran an effort.

    Gating: research has no gate (runs to completion); plan/build gate
    in-session — handled by ``gate_adapter`` once the stream surfaces the
    ``AskUserQuestion`` frame (no extra wiring needed here beyond marking the
    lane as gating, which the seed reflects).

    Returns the augmented job record (includes ``skill``, ``output_dir``,
    ``project_id``, ``folder_path``, ``gates``, ``backend``). Raises
    ``EngineNotAllowedError`` if the engine policy refuses the launch, or
    ``job_runner.LaneBusyError`` if the concurrency policy refuses it.
    """
    backend = backend or DEFAULT_BACKEND
    ld = get_lane(lane)
    # Engine policy: Gemini only on research; Claude anywhere. Checked before any
    # subprocess is spawned so a refused launch leaves no side effects.
    check_engine_allowed(lane, backend)
    project = _rnd.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    folder_path = project.get("folder_path", "")

    output_dir = lane_output_dir(folder_path, project_id, lane)
    # Scaffold the per-project store (idempotent) so the lane dir exists.
    _rnd.scaffold_project_store(folder_path, project_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_seed = build_prompt_seed(lane, project, output_dir)
    gated = lane_gated_flag(lane)
    # The prompt seed (natural-language "Run the X skill ...") is now delivered
    # as the ACTUAL prompt — on argv for research, on a stream-json stdin turn
    # for the gated lanes — NOT stuffed into the dead --skill/--output-dir/
    # --prompt-seed flags (those are not real CLI flags; that was the bug). The
    # project-scoped output dir is passed via the real --add-dir (claude) /
    # --include-directories (gemini) flag so artifacts land in the project
    # namespace. ``extra_args`` stays a passthrough for test flags (--lines etc.)
    # that the mock runner consumes; in production it is normally empty.
    rec = _jr.launch_guarded(
        lane, project_id=project_id, folder_path=folder_path,
        cwd=folder_path or None, extra_args=extra_args, env=env,
        job_id=job_id, backend=backend, prompt=prompt_seed,
        output_dir=output_dir, gated=gated,
    )
    jid = rec["job_id"]

    # Record the effort under the project namespace (on-disk proof for AC1),
    # stamping the chosen engine so history shows which engine ran the effort.
    _write_launch_record(output_dir, project_id, lane, jid, ld.skill,
                         prompt_seed, backend)

    # Augment + persist the record with lane wiring metadata for the UI / Wave 7.
    rec = _jr._update_record(
        jid,
        skill=ld.skill,
        output_dir=str(output_dir),
        gates=ld.gates,
        mutates_tree=ld.mutates_tree,
        backend=backend,
    )
    return rec
