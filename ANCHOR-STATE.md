# ANCHOR — Current State (single source of truth)

> **What this file is:** the ONE always-current "where is Anchor right now / what's next"
> doc. It is git-tracked and auto-pushed (backup), so after any restart or new session this
> is the first place to look — no archaeology. **Keep it current:** update the top block at
> every meaningful checkpoint (a deploy, a finished effort, a decision) and commit. Detailed
> history lives in git log + the per-effort docs; this file stays short and current.

_Last updated: 2026-07-10._

## Deployment status
- **master HEAD:** `c3f37c7` (`bfe02df` code + this doc; pushed to origin `E:\anchor.git`).
- **DEPLOY CONFIRMED LIVE (2026-07-10):** `nssm anchor` Running, `GET /` → 200, `GET
  /api/routes` reports `migrated_count: 112` — the running service is post-merge code.
- **Auto-push:** ENABLED for the Anchor project (finishes push to `E:\anchor.git` automatically).

## What just shipped to master (2026-07-08 → 07-10)
1. Warm-resume + autosave for general sessions; terminal input-ordering fix (`534bae1`).
2. **Atomic-writes durability fix** — no registry/effort corruption on a mid-write crash (`96bca8a`).
3. **C2 route-strangler migration COMPLETE** — HTTP handlers lifted from the `anchor_gui.py`
   monolith into `route_table.py`: **112 / 134 migrated**, 22 sanctioned residual (whole-page
   renders, static assets, 3 socket specials, and the 6 data-plane-gated GETs that MUST stay
   legacy so the do_GET W8/W9 auth overlay still runs). 10 gate-green + Gemini-reviewed commits.

## Next actions (priority order)
1. ~~**Verify the deploy is live**~~ ✅ DONE 2026-07-10 — service Running, `GET /` 200,
   `/api/routes` migrated_count 112 (post-merge code confirmed serving).
2. **Harden agy / 5:1 in the skill** (John's ask, 2026-07-10): put a reusable `agy-review`
   entry point + a hard "never hand-roll agy / prompt small / agy-dispatch --readonly" rule
   INTO the `agy-dispatch` skill so 5:1 is automatic and host-independent (not model-memory).
3. **Phase-2 of durable saving** (this doc's own follow-up): wire `pre_restart_drain.py` into
   the restart path (warm-by-design restarts) + a Claude-Code Stop/SessionStart hook.
4. **Fix the clobbered `IMPLEMENTATION-PLAN.md`** — on-disk file is the zombie-hunter plan,
   not the rearch plan (filename collision); restore the real one from git. Bookkeeping only.
5. **C1 frontend extraction** — still BLOCKED on a plan-level decision (unsatisfiable exit
   gate; ~14k-line embedded JS blob). Separate effort; needs thinking, not grinding.

## Resume-after-restart facts
- Full dossier: the `anchor-deploy-resume-2026-07-10` memory (pinned in MEMORY.md).
- Service: NSSM `anchor` runs `python anchor_gui.py --no-browser`, binds `127.0.0.1:8777`.
- Migration loop (if resuming C-work): sub-agent extracts a batch → run the gate
  `pytest tests/test_rearch_2026_07.py -k "W7 or W8 or RouteAudit or Strangler or ImportShadow or OpenRoutes"`
  → `agy-dispatch --readonly` Gemini review → commit.
- Zombie-hunter (armed reaper) was built + merged in earlier sessions — already on master; the
  C2 sweep only moved its 5 web-control routes into the table.
