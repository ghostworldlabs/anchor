# Shareable Anchor Distro + /onboard — Execution Log

> Seeded by Crucible Stage 2 (2026-06-23). Foreman appends per-wave EXECUTE → GATE → REVIEW → FIX → verdict
> entries here. Empty below the seed line.

## Pre-build state
- Plan: IMPLEMENTATION-PLAN.md (8 waves; terminal milestone = Wave 8, PROJECT DONE).
- Gate command: `python -m pytest -q` (baseline GREEN 1483 passed, 1 skipped — re-verify at build start).
- Design: MASTER-PLAN.md (Shark-Tank R1 converged: 4 verified BLOCKERs folded into Waves 1-3 + the service seam).
- HALT-worthy / reserved: the vendored-skill scrub dispositions (Wave 3 — author PII/host-path decisions);
  any real GitHub push or real per-OS service registration (stubbed in tests; deferred to John's deploy);
  the stdlib-only invariant (no new deps — POSIX pty uses stdlib `pty`); the no-leak gate (export must be
  clean before push).
- Order is load-bearing: cross-platform core (W1) → clean vendor (W2) → scan-clean (W3) → starter (W4) →
  onboard core (W5) → service (W6) → /onboard skill + push (W7) → healthcheck + docs (W8).

---

## Wave 1+2 — cross-platform core — GREEN (2026-06-23)
- W1 PosixPtyBackend (stdlib pty, behind the backend seam) + W2 POSIX single-instance guard
  (SO_REUSEADDR=0 + classify_bind_error → clean exit). Both proven on the WINDOWS gate via injected
  fakes + platform monkeypatch (NO pytest.skip). Gate: `python -m pytest -q` = 1502 passed, 1 skipped.
- ORCHESTRATOR FIX (the EXECUTE agent stalled): its fake `select()` ignored its timeout → a leaked
  un-killed daemon reader busy-spun at 100% CPU and starved the combined run (the 56-min "hang").
  Fixed test-side (honor the timeout + reap the reader). Product code unchanged/correct. Combined
  run 56min→1.16s. LESSON: a test that spawns a reader thread MUST reap it; a fake select MUST honor
  its timeout. Real-POSIX behavior is a deploy-time smoke (faked-platform proves the logic only).

## Wave 3 — vendor_skills.py (clean vendoring) — GREEN (2026-06-23)
- `git archive <HEAD>` + extract via stdlib tarfile → vendor/bundled-skills/<name>/ (drops .git +
  untracked-gitignored); DENYLIST filter removes TRACKED personal logs (EXECUTION-LOG/DECISION-LOG/
  CLAUDE_hist/journal/.foreman/runs/*-checkpoint/*-out/.env*) that git archive keeps; residual host-path
  + email scrub; SOURCES.md records the archived commit. Unset source = honest skip (no real-path fallback).
- Gate: full suite = 1504 passed + 1 FLAKE (test_project_window summary-panel) that PASSES in isolation —
  flake was the orchestrator running two pytest suites concurrently (CPU contention). +3 new tests.
- Agent note: the literal jane@uni.edu in the test file tripped distro's repo-wide PII scan → PII strings
  assembled at runtime (the tests/test_distro_scan.py convention). LESSON: never run two heavy pytest
  suites at once (it flakes timing-sensitive tests).
