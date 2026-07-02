# Anchor durability waves (2026-07 review, Plan 1 Wave C)

Make Anchor's in-flight work honest across service restarts. Today a restart
kills every running job (Job Object kill-on-close), a gated session's pending
question becomes permanently unanswerable (its stdin pipe dies with the
process), and a gandalf run interrupted mid-flight leaves a perpetual
"running" row in its index. The dashboard's word "resumable" must reach the
process layer: interrupted jobs re-launchable in one call, gate answers
durable, no ghost rows.

North Star: after `nssm restart anchor` mid-work, nothing lies — every
interrupted unit is either honestly terminal or one-call resumable, and no UI
element spins forever.

Non-goals: live PTY reattach; transparent (no-op) resume of a killed process;
UI affordances (backend seams only — the dashboard wiring is a later wave);
any change to the trio engines.
