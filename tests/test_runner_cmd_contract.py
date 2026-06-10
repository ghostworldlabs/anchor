"""Locks the PRODUCTION runner-command contract — the real-CLI argv shape.

Root-cause regression guard. The original code emitted ``--skill``,
``--output-dir``, ``--prompt-seed`` (NONE are real ``claude``/``gemini`` flags),
delivered the prompt as DEVNULL stdin (so it never arrived), and used a
read-only approval mode for the research lane (so the report could never be
written). The 209-test baseline only passed because every launch indirected
through ``ANCHOR_RUNNER_CMD`` → the mock, which tolerates unknown args — so the
real-CLI path was NEVER exercised.

These tests pin the argv that ``job_runner`` builds when ``ANCHOR_RUNNER_CMD`` is
UNSET (production), per backend and per lane:
- the right binary (claude / gemini),
- the natural-language prompt delivered correctly (argv for research; stdin for
  gated lanes — verified by the launch wiring),
- the project-scoped output dir passed via the REAL flag (--add-dir /
  --include-directories),
- a WRITE-capable permission/approval mode,
- and NONE of the dead flags (--skill / --output-dir / --prompt-seed).

NO live CLI is invoked: these inspect the constructed argv directly (no Popen).
"""
import importlib
import os

import pytest

DEAD_FLAGS = ("--skill", "--output-dir", "--prompt-seed")


@pytest.fixture
def jr(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # CRITICAL: unset the test indirection so the REAL-CLI argv builder runs.
    monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    return job_runner


SEED = "Run the researchPrime skill for project 'X'. Write under /out."
OUT = "/proj/.anchor/projects/abc/research"


# ── claude RESEARCH (non-gated) ───────────────────────────────────────────────

def test_claude_research_argv_is_valid_and_has_no_dead_flags(jr):
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated=False)
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--output-format" in argv and "stream-json" in argv
    # Live-CLI requirement: --print + stream-json REQUIRES --verbose.
    assert "--verbose" in argv
    # Output dir via the REAL flag, not --output-dir.
    assert "--add-dir" in argv
    assert OUT in argv
    # WRITE-capable permission mode (research must write its report).
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"
    # The natural-language seed IS the prompt, on argv (non-gated).
    assert SEED in argv
    # NONE of the dead flags survive.
    for dead in DEAD_FLAGS:
        assert dead not in argv
    # Research is non-gated → NO stdin input-format (prompt is on argv).
    assert "--input-format" not in argv


# ── claude PLAN (gated, non-mutating) ─────────────────────────────────────────

def test_claude_plan_argv_gated_stdin_acceptedits(jr):
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated="plan")
    assert argv[0] == "claude"
    # Gated → prompt arrives on stdin → --input-format stream-json present.
    assert "--input-format" in argv
    assert "--add-dir" in argv and OUT in argv
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"   # plan writes docs, non-mutating
    # Gated lanes must NOT carry the prompt on argv (it goes on stdin).
    assert SEED not in argv
    for dead in DEAD_FLAGS:
        assert dead not in argv


# ── claude BUILD (gated, mutating) ────────────────────────────────────────────

def test_claude_build_argv_gated_bypass_permissions(jr):
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated="build")
    assert argv[0] == "claude"
    assert "--input-format" in argv
    i = argv.index("--permission-mode")
    # build mutates the tree + may run Bash → bypassPermissions.
    assert argv[i + 1] == "bypassPermissions"
    assert SEED not in argv
    for dead in DEAD_FLAGS:
        assert dead not in argv


# ── gemini RESEARCH (research-only) ───────────────────────────────────────────

def test_gemini_research_argv_is_valid_and_has_no_dead_flags(jr):
    argv = jr.resolve_runner_cmd(backend="gemini", prompt=SEED,
                                 output_dir=OUT, gated=False)
    assert argv[0] == "gemini"
    assert "--skip-trust" in argv          # untrusted-folder write requirement
    assert "-p" in argv
    # The prompt is the VALUE of -p (appears immediately after it).
    assert argv[argv.index("-p") + 1] == SEED
    assert "--output-format" in argv and "stream-json" in argv
    # WRITE-capable approval mode (research writes its report).
    i = argv.index("--approval-mode")
    assert argv[i + 1] == "auto_edit"
    assert argv[i + 1] != "plan"           # 'plan' is read-only → would block
    # Output dir via the REAL flag (--include-directories, NOT --output-dir).
    assert "--include-directories" in argv
    assert OUT in argv
    for dead in DEAD_FLAGS:
        assert dead not in argv


# ── override path still wins + appends prompt the mock tolerates ──────────────

def test_override_wins_and_appends_prompt_as_trailing_arg(jr, monkeypatch):
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "python /tmp/fake_claude.py")
    argv = jr.resolve_runner_cmd(backend="claude", prompt=SEED,
                                 output_dir=OUT, gated="build",
                                 extra_args=["--lines", "2"])
    # The override base is used verbatim — NOT the real claude/gemini builder.
    assert argv[0] == "python"
    assert "/tmp/fake_claude.py" in argv
    assert "claude" != argv[0] and "gemini" != argv[0]
    # The prompt is appended as a trailing arg the mock ignores (parse_known).
    assert SEED in argv
    # Test flags come last.
    assert argv[-2:] == ["--lines", "2"]
    # Real flags are NOT injected on the override path.
    for dead in DEAD_FLAGS + ("--add-dir", "--include-directories",
                              "--permission-mode"):
        assert dead not in argv


def test_shape_only_resolution_unchanged_when_no_prompt(jr):
    # No prompt → shape-only base (the engine-selector contract).
    claude = jr.resolve_runner_cmd(backend="claude")
    assert claude[0] == "claude" and "-p" in claude
    gemini = jr.resolve_runner_cmd(backend="gemini")
    assert gemini[0] == "gemini" and "--skip-trust" in gemini
    assert "--approval-mode" in gemini
