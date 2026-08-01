# v1.1.3 share-fix — handoff (2026-08-01)

Recovery release for the broken 1.1.x collaborator distribution
(`friction-intake-2026-07-30.md`). Built on branch `sharefix/v1.1.3`.
All work reviewed against the Fable adversarial review of the recovery plan;
six decisions locked by John (builder=distro.py · token enforced · skills
junction→copy · honest launcher (no service) · summaries opt-in on shared ·
automated sandbox + John's VM check).

## What changed (by commit)

1. **Packaging + gates + version** — `dist_manifest.txt` gains the 13 missing
   runtime modules (the 11 from the friction intake + `orientation.py` +
   `parity.py`, found by the new gate itself), the whole `share_*`/onboard
   cold-start surface, `VERSION`/`CHANGELOG.md`/`anchor.ico`. `distro.py` is
   the ONE blessed builder with a new fail-closed **import-closure gate**
   (static, sees lazy imports; optional list: `update_transaction`, `tools`)
   and emits a thin consumer `CLAUDE.md`. `_build_clean_ship.py` is now a
   thin wrapper that raises on any gate hit (it used to print-and-ship).
   Vendored skill bundles drop dev-only `test/` dirs (planted fixtures).
   The stale 61MB `planning/**/package-v1` trees are removed from git
   (history keeps them; last build archived locally under `_archive/`).
   `VERSION` = `pyproject.toml` = `1.1.3`.

2. **Onboard truth** — `onboard.register_service`'s dead `anchor.registrar`
   path and fake "foreground fallback port N" are gone.
   `share_onboard.spawn_anchor_server` GENUINELY starts the server (detached,
   token wired into env, `ANCHOR_PROACTIVE_SUMMARY=0` default on shared
   installs); `launch_anchor_dashboard.py` uses it and hands the token to the
   browser ONCE via the loopback URL (page stores it, mints the HttpOnly
   cookie via `/api/auth/login`, strips the URL). Onboard installs
   `pywinpty` on Windows Package B (probe-first; honest failure). Claude
   skill registration: symlink → REAL directory junction (stock Windows, no
   admin/DevMode) → marked full copy — never a pointer-marker dir; legacy
   pointer dirs heal on re-onboard. `anchor_gui.main()` honors an explicit
   `ANCHOR_PROACTIVE_SUMMARY=0`. `doctor.py` gains deterministic probes
   (missing modules / pywinpty / git / CLIs / token / server).
   `USER-ONBOARD.md`'s three false claims fixed.

3. **Acceptance tooling** — `tools/share_sandbox.py` (10-gate automated
   stranger sandbox; ALL GREEN 2026-08-01) + `tools/vm_check.ps1` (John's
   clean-box one-shot) + `tests/test_sharefix_v113.py` (22 unit gates).

## Sandbox result (2026-08-01, this machine)

10/10: build fail-closed (990 files) · completeness · version · cold boot
GET / 200 · tokenless POST 401 / tokened 200 · **New General session starts
(stub PTY)** · errors.log ZERO ModuleNotFoundError · onboard installs 13
skills all Claude-readable via junctions (junction mode forced — and note:
symlink creation FAILS in-process on this very machine, so the junction path
is what real collaborators will exercise) · doctor quiet-on-complete /
loud-on-hole.

## What YOU (John) still do before re-sharing

1. **Merge + tag** (after your review):
   ```
   git checkout master
   git merge --no-ff sharefix/v1.1.3
   git tag -a v1.1.3 -m "v1.1.3 share-fix"
   git push origin master v1.1.3
   ```
2. **Build the package**: `python planning/share-anchor-skills-2026-07/_build_clean_ship.py`
   (or `python distro.py -o <dir>` for B only). Any gate hit now FAILS the build.
3. **VM check** (clean Windows box / fresh user account, NO Developer Mode,
   NO admin): unzip package → `powershell -ExecutionPolicy Bypass -File
   .\tools\vm_check.ps1` → then walk `.\onboard.cmd` interactively once.
4. **Tell collaborators**: wipe the old install (delete the old package
   folder + `%USERPROFILE%\.claude\skills\*` entries that are marker-only
   dirs — or just re-run onboard, which heals them), unzip v1.1.3, run
   `.\onboard.cmd`, then `python launch_anchor_dashboard.py`.
5. **Your own machine is untouched**: the NSSM service env has no
   `ANCHOR_PROACTIVE_SUMMARY`, so summaries stay proactive; the launcher
   short-circuits when :8777 is already up. NOTE: next `nssm restart anchor`
   picks up the anchor_gui.py changes (token-bootstrap JS + summarizer flag
   honor) — both are no-ops for your config.

## Accepted residuals (documented, deliberate)

- `ANCHOR_AUTH_MODE` stays `open` on shared installs for THIS release: the
  minted token gates every mutating `/api/*` route + the terminal/WS/RCE
  surface, but read-only data-plane GETs stay open on loopback. Full
  enforcement (`enforce` + static frontend + cookie navigation) is the v1.2
  hardening track — flipping it now risks 401-ing the very installs this
  release fixes, and the DAG ties `enforce` to the static frontend pillar.
- No auto-start on login (launcher re-run after reboot). A schtasks logon
  task was scoped out (Decision 4).
- `zombie-hunter`/`tidy-idy` Python bridges ship; their Node skill servers
  resolve via `~/.claude/skills` or `ANCHOR_FOUNDRY_DIR` and degrade
  honestly when absent.
- The reaper daemon ships UNARMED by default (arming ladder + the
  `.anchor/reaper.disarmed` brake).

## Test evidence

- `tests/test_sharefix_v113.py` — 22 passed
- skills-root w0/w1 — 35 passed (junction-aware)
- share package A/B + onboard w5 — 49 passed
- distro/vendor/onboard/doctor/parity/launcher net (22 files) — 335 passed
  total after the two legit test updates (CLAUDE.md emission; junction-aware
  dual-copy cleanup). Pre-existing failure `test_no_module_imports_gemini_sdk`
  FIXED by the package-v1 removal (verified pre-existing via stash probe).
- Full suite NOT run wholesale (known flaky-under-load; regen traps) —
  targeted nets only, per repo convention.
