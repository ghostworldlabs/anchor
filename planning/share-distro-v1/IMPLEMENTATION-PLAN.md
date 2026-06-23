# Shareable Anchor Distro + `/onboard` — Implementation Plan (Foreman-ready)

> test-command: `python -m pytest -q` · branch `share-distro` off master (baseline GREEN 1483 + 1 skip).
> Design: the Shark-converged `MASTER-PLAN.md`. Conventions (carry every wave): Python **stdlib only** (lone
> lazy `pywinpty` in `pty_manager.py`; the new POSIX pty backend uses the stdlib `pty` module). Hermetic tests
> — temp `HOME`/skills-dir/data-dir, stubbed `ANCHOR_SERVICE_CMD` + `ANCHOR_GH_CMD` (`tests/stub_gh.py` + a
> LOCAL BARE remote), `port=0`; NEVER bind `:8777` / touch the real home / real service / real network /
> real GitHub. Playwright DEV-ONLY (`pytest.importorskip`). Every wave holds or grows the test count. NO
> push to a real GitHub / NO real service registration until John signs off. Order is load-bearing
> (vendor-clean → scan-clean → onboard → service → push) per the Shark Tank.

## Wave 1 — cross-platform core: POSIX single-instance guard + stdlib POSIX PTY backend + Windows-ism audit
**Goal:** the Anchor core (server, terminals) runs on macOS/Linux with the same safety guarantees as Windows.
**Changes:**
- `pty_manager.py`: add `PosixPtyBackend` using the stdlib `pty`/`os`/`select`/`fcntl`/`termios` modules
  (start/write/read_since/resize/kill — same contract as the stub/pywinpty backends); `_select_backend`
  auto-picks POSIX on non-Windows when `ANCHOR_PTY_BACKEND` is unset; `stub` still forced in tests.
- `paths.py`/`anchor_gui.py`: a **POSIX single-instance guard** — a pidfile lock (or `SO_REUSEADDR=0` +
  `EADDRINUSE`→clean-exit, reusing `classify_bind_error`) so a second instance on `:8777` can't squat
  (parity with the Windows `SO_EXCLUSIVEADDRUSE` guard).
- Audit + genericize shipped UI/comments: no hardcoded `nssm`/`gwl-server`/author-host in any string the
  collaborator sees (replace with generic "restart the Anchor service" + an OS-resolved hint).
**Done-when (`pytest -q` ≥ baseline; new tests):**
- The POSIX pty backend round-trips (echo) under a forced non-Windows path / a faked platform (the test
  imports + drives `PosixPtyBackend` where `pty` is available; skips cleanly on Windows).
- Two server instances on the same port: the second exits cleanly (guard), proven cross-platform (the
  EADDRINUSE/pidfile path) — not just on Windows.
- A grep test: shipped HTML/UI strings contain no `nssm`/`gwl-server`/`C:\\Users\\john`/`C:\\dev`.

## Wave 2 — `vendor_skills.py`: clean vendoring via `git archive`
**Goal:** vendor the 4 skills into `vendor/bundled-skills/` with NO `.git`, gitignored junk, or dirty state.
**Changes:**
- `vendor_skills.py` (stdlib): for each source (`ANCHOR_TRIO_DIR` / `ANCHOR_GANDALF_DIR`, overridable for
  tests) resolve HEAD commit → `git archive <commit> <subdir>` → extract into
  `vendor/bundled-skills/<name>/` (this auto-drops `.git/`, all `.gitignore`'d files, and uncommitted dirty
  state). Write `vendor/bundled-skills/SOURCES.md` with each name + source + archived commit sha.
- A residual host-path/PII **scrub pass** over the extracted tree (genericize `C:\dev\…`/`/Users/<u>`/
  `/home/<u>` → `<path>`; drop or scrub test fixtures carrying example emails).
**Done-when:**
- Given a temp git source repo with a committed file + a gitignored `runs/x.log` + a dirty uncommitted file,
  When `vendor_skills.vendor_all(dest)`, Then `vendor/bundled-skills/<name>/` contains the committed file,
  NO `.git/`, NO gitignored file, NO dirty file; `SOURCES.md` records the archived commit.
- The scrub pass removes a seeded `C:\dev\foreman-targets\…` host path and a seeded `a@b.edu` fixture email.

## Wave 3 — `distro.py` scan coverage + the clean-scan gate
**Goal:** `build_distro` over the staged bundle is CLEAN (no false-fail, no leak), with host-paths caught.
**Changes:**
- `distro.py`: `_is_vendored` (or the scan-skip logic) treats `vendor/bundled-skills/**` as vendored (skip the
  stdlib-import scan + the generic high-entropy detector, like `vendor/`); ADD a **build-host-path** PII
  detector (`C:\<...>\dev\…`, `/Users/<u>/`, `/home/<u>/`, the author's known host names) so leaking host
  paths FAIL the scan; `dist_manifest.txt` allow-lists `vendor/bundled-skills/**`, `onboard.py`,
  `vendor_skills.py`, the `/onboard` skill, and the starter templates.
- `build_distro` ends with a **clean-scan GATE**: a non-clean scan aborts before any git-init/push.
**Done-when:**
- `build_distro` over a fixture repo with a staged `vendor/bundled-skills/` tree returns CLEAN (no
  `PersonalDataError`, no `third-party-import`, no false high-entropy fail on a git SHA).
- A seeded leaking host path (`C:\dev\secret\…`) in a NON-vendored staged file FAILS the scan (the new
  detector); the same path inside `vendor/bundled-skills/` after scrub does NOT appear.

## Wave 4 — starter Anchor templates (no data)
**Goal:** ship empty, headers-only Anchor markdown the collaborator starts fresh from.
**Changes:** `starter/` templates for `DASHBOARD.md`/`INBOX.md`/`PROJECTS.md`/`domains/{academic,commercial,
family,writing}.md`/`SAVED_FOR_LATER.md`/`CANCELLED.md`/`WEEKLY_REVIEW.md` — headers only, zero entries;
allow-listed in the manifest.
**Done-when:** every starter file parses with the existing markdown parsers and contains ZERO task/project/
inbox entries; `build_distro` stages them; a no-PII scan over them is clean.

## Wave 5 — `onboard.py`: skills-install + scaffold + token (hermetic; no service yet)
**Goal:** the installer's safe, idempotent core — install skills, scaffold Anchor, mint the token.
**Changes:** `onboard.py` (stdlib): detect OS + prereqs (report, never hard-fail an optional miss); install
the 4 vendored skills to the skills dir (`ANCHOR_SKILLS_HOME`, default `~/.claude/skills`) by COPY (symlink
opt-in) — **refuse-don't-clobber** when a target already points elsewhere; scaffold the starter Anchor into
the data dir only-if-absent; GENERATE a random `ANCHOR_TOKEN` to an out-of-tree/`.gitignore`'d file (never the
repo). Idempotent + resumable.
**Done-when (hermetic — temp `ANCHOR_SKILLS_HOME` + temp data dir; never the real home):**
- A fresh run installs 4 skills + scaffolds the starter files + writes a token file OUTSIDE the repo tree.
- A second run is a no-op (idempotent); an existing differently-sourced `~/.claude/skills/foreman` is
  refused-not-clobbered (the author-symlink-protection case).
- After onboard, `build_distro` over the repo is STILL clean (the token never lands in a staged file).

## Wave 6 — per-OS service registrar + foreground fallback
**Goal:** `/onboard` registers + starts the background service per-OS, with a guaranteed foreground fallback.
**Changes:** an `ANCHOR_SERVICE_CMD` seam + per-OS registrars (NSSM Windows · launchd user-agent macOS ·
systemd-user Linux) that capture PATH (`claude`/`node`) + the token env, write unit files `chmod 600`; a
`nohup`/background **foreground fallback** when no registrar/elevation; rollback on a half-failed registration.
`onboard.py` calls it, then health-checks `:8777`.
**Done-when (hermetic — `ANCHOR_SERVICE_CMD` stubbed; no real service):**
- With the stub registrar, onboard "registers" + the stub records the correct per-OS invocation + the token
  is NOT world-readable in the captured unit (mode asserted); a forced registrar-failure falls back to the
  foreground launch (the run still ends with a reachable dashboard on an OS-assigned port ≠ 8777).
- Rollback: an injected mid-registration failure leaves no partial service record.

## Wave 7 — the `/onboard` repo-local skill + manifest + GitHub push
**Goal:** `/onboard` is invocable on a fresh clone; the clean repo ships to a private GitHub repo.
**Changes:** a repo-local `/onboard` `SKILL.md` (runs `python onboard.py`); finalize `dist_manifest.txt`;
a `build_distro` → `git init` + initial commit + `gh repo create --private` (via `ANCHOR_GH_CMD`) + push,
**gated on a clean scan**, with the documented no-`gh` manual path.
**Done-when (hermetic — `ANCHOR_GH_CMD` → `tests/stub_gh.py`, a LOCAL BARE `file://` remote; NO real network):**
- `build_distro` emits a self-contained tree (core + `vendor/bundled-skills/` + `onboard.py` + the `/onboard`
  skill + starter templates), passes the clean-scan gate, `git init`s + pushes to the LOCAL BARE remote.
- The `/onboard` skill doc resolves + names `python onboard.py`; absent `gh` → the manual-path message, no crash.
- A grep over the EXPORTED tree: zero author data / host paths / `.git` of the vendored skills / token.

## Wave 8 — `check_onboard_surface` healthcheck + CLI mirror + docs (PROJECT DONE)
**Goal:** a hermetic self-test of the whole surface + the collaborator-facing docs.
**Changes:** `anchor_healthcheck.check_onboard_surface` (fully stubbed: temp HOME/skills/data, stubbed
service + gh, never `:8777`) walking vendor → build_distro-clean → onboard install/scaffold/token →
service-stub/fallback → export-is-clean; registered in `main()`. `anchor.py` read-only mirror
(`distro vendor-status` / `distro check`). README (collaborator: clone → `/onboard` or `python onboard.py`),
CLAUDE.md "Shareable distro" section, `distro.py` import scan stays clean (the new modules stdlib-only).
**Done-when:** `pytest -q` green ≥ baseline incl. `check_onboard_surface`; the README's bring-up path is
accurate; distro scan green; docs updated.
