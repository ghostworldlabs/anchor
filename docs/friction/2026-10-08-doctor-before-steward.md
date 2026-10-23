# Anchor Health Report â€” 2026-10-08

Status: ISSUES FOUND
Run time: 205.2s (05:00:01)

## Executive summary
Needs attention: 1 of 34 checks failed — Steward cockpit surface. The dashboard banner stays red until the next clean run; start with the Issues section below.
3 non-blocking warning(s) — performance/timing notes only; they never redden the banner.
2 auto-fix(es) applied during the run.

## Checks
- âœ“ file system integrity  (ok)
- âœ“ code compiles  (anchor_gui.py + anchor.py)
- âœ“ pillar flags: named hybrid state  ('baseline' (frontend=embedded · auth=open · journal=off · supervisor=inline))
- âœ“ markdown parseability  (100 tasks, 0 projects, 5 inbox, 25 archived)
- âœ“ server boot  (32.5s)
- ! server boot speed  (slow but OK: ready after 32.5s (over 30s - likely machine load))
- ! home page render speed  (slow but OK: status=200, 3106 bytes, 10.9s (over 5s - likely machine load))
- âœ“ HTTP endpoints  (8/8 passed)
- âœ“ declared-route auth walk (W8)  (242 declared rows honor their auth policy (mode=open, token=minted))
- âœ“ synthetic task round-trip  (7 steps)
- âœ“ R&D v2 surface  (12 steps)
- âœ“ R&D v3 surface  (13 steps)
- âœ“ R&D v4 surface  (8 steps)
- âœ“ R&D v5 surface  (8 steps)
- âœ“ R&D v6 surface  (6 steps)
- âœ“ R&D v7 surface  (5 steps)
- âœ“ R&D v8 surface  (9 steps; link_ok=True not_pushed=True pushed=True bare_has=True branch=master commit_matches=True)
- âœ“ R&D v9 surface  (9 steps)
- âœ“ R&D v10 surface  (7 steps)
- âœ“ R&D v11 surface  (4 steps)
- âœ“ R&D v11.1 surface  (4 steps)
- âœ“ R&D v12 surface  (13 steps)
- âœ“ Gandalf surface  (5 steps)
- âœ— Steward cockpit surface  (engine never reached 2 turn_end events (events: ['delta', 'delta', 'delta', 'delta', 'delta', 'turn_end', 'status', 'status']))
- âœ“ telemetry capture+finalize walk (W7)  (4 steps)
- âœ“ sidecar drift tripwire (W7)  (8 recent sidecar(s) parse cleanly)
- âœ“ journal completeness gate (enforce)  (paired-passed=True unpaired-fired=True)
- ! journal perf budget (<15%)  (off=3831.0ms on=5013.3ms overhead=30.9% (budget 15%), journaled=yes)
- âœ“ journal parity gate (classify + recover)  (clean-after-workload=True classified-loss=True recovered-by-rebuild=True | parity[hc-parity-pid]: CLEAN — effective=0 bugs=0 journal-ahead=0 legacy-ahead=0 conflict=0 (tail_window=0, max_seq=4))
- âœ“ supervisor seam (inline restart survival)  (docs-ok=True inline=True same-job-running=True cursor-advanced=True cancelled=True unresolved-rebuild-rows=0)
- âœ“ supervisor live probes (external process)  (external=True bad-token-refused=True round-trip=True cursor-survived-restart=True probe-a(claude --version)-ok=True probe-b(breakaway-child-alive)=True)
- âœ“ north-star scorecard (C1–C7)  (5 met Â· 2 narrowed-by-amendment Â· 0 unmet; appendix-A: 52/52 ideas landed, M-9 documented amendment)
- âœ“ logging  (today's log 517 bytes)
- âœ“ Local filesystem write sanity  (write/read OK)

## Issues
- [Steward cockpit surface] engine never reached 2 turn_end events (events: ['delta', 'delta', 'delta', 'delta', 'delta', 'turn_end', 'status', 'status'])

## Warnings (non-blocking)
- [server boot speed] slow but OK: ready after 32.5s (over 30s - likely machine load)
- [home page render speed] slow but OK: status=200, 3106 bytes, 10.9s (over 5s - likely machine load)
- [journal perf budget (<15%)] off=3831.0ms on=5013.3ms overhead=30.9% (budget 15%), journaled=yes

## Auto-fixes applied
- test port 8778 busy; ran on free port 54998 instead
- unauth-rejection assertion: tokenless mutating POST correctly returned 401

## Recommended actions
(none)
