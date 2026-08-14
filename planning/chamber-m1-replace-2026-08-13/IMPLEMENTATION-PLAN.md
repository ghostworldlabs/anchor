# Make M1 survive, wire talk, delete v0 — Implementation Plan (Foreman-ready)
# REVISION 3 (2026-08-13) — the scope John corrected.
#
# Revisions 1 and 2 were wrong twice: they treated the OLD chamber as the
# specification (a parity map that would have dragged v0's design into M1 one
# signature at a time), and they assumed M1 needed building. M1 IS BUILT AND
# WIRED. Verified in the live tree: the slice's shadow-root delegation already
# handles the × close, `data-open-session`, the STATUS overlay, the REFINE
# overlay (open/confirm/keep/discard), the deliverable href + action, and
# `_ecgSealStartPulsePoll` already drives the status table, live-status line and
# the deliverable box. W6-W11's work is all there.
#
# M1's drawn design is the SPECIFICATION. v0 is not a requirements document —
# John did not like how it worked, and it is the thing being removed.

test-command: node scripts/run-all-tests.mjs

**North Star:** The M1 chamber is what John sees, works the way it was drawn, and v0
is gone. Not "M1 renders" — it already renders. **M1 SURVIVES and v0 no longer exists.**

**What is actually broken (verified, not inferred):**
1. `ecgSealMountInline` paints M1, then hydrates v0 and calls `_ecgSealDropSlice()`,
   removing M1 from the document — on all three branches (chamber success,
   `mode === 'stand_up'`, and the error path, which mints a dock WITHOUT dropping so
   both surfaces can coexist).
2. The drawn say box — `<input placeholder="Talk to Jarvis…">` plus its "Say it"
   button — carries no `data-*` hook, so the slice's delegation cannot reach it.
   **This is the ONLY unwired affordance in M1.**
3. v0 is still in the tree.

**What needed no work at all:** empty/unbuilt projects. `seal_open` already returns a
drawn `AG-DEGRADED-RAIL` face (all 13 of John's unbuilt projects served exactly that
this morning), so v0's stand-up screen has no successor to build — it simply dies.

**Not in scope, by John's ruling:** preserving v0 affordances. Anything v0 does that
M1 does not draw is GONE — the 600ms `_ecgConverse` on open (which is the D2 clunk
the campaign existed to kill, and violates M1's zero-model-call-until-you-speak law),
the old goal-bar buttons, the seat pill, Escape-to-close, `_ecgRenderBlockedTurn`'s v0
chrome. No parity map, no signature-per-affordance.

**Deferred, not dropped:** the drawn say box is a one-line `<input>`; John's old one
grew as he typed (built after dictation hid his words). Swapping `input`→`textarea`
breaks the C9 signature and needs a mockup amendment. Ruling: **wire the drawn input
now; amend only if the dictation problem recurs in use.**

---

## Wave 1 — Stop the delete, wire talk

**Intent:** Make M1 the surface that remains, and give it the one affordance it is
missing. After this wave John opens the Seal and sees the chamber that was designed
for him, and can talk to it.

**Deliverables:** `_ecgSealDropSlice()` removed from **all three** call sites — the
chamber-success path, the `mode === 'stand_up'` branch, and the error path; `ecgSealMountInline`
no longer mounts `_ecgRenderChamber`, `_ecgRenderStandUp`, or the error-path dock (the
painted slice stays up and already carries an honest drawn face for the unbuilt and
degraded cases) — the functions remain in the tree; deletion is Wave 2. **Say box
wired:** `data-say-input` / `data-say-send` emitted server-side onto the drawn input and
button (`chamber_open._render_convo`) — ATTRIBUTES ONLY, because the C9 signature is
`(tag, sorted-classes)`, so the hash pin holds and no amendment is needed — and handled in
the slice's existing shadow-root delegation (click on send, Enter on the input) posting to
the EXISTING `/api/ecgberht/converse`; the reply paints into the drawn `.msgs` using
**mockup classes** (`.msg.steward`, `.msg.john`), never `.ecg-msg` — page CSS does not
cross the shadow boundary, so v0's painter classes would render invisible inside the
slice. **E1 stays enforced AND becomes visible:** `/api/ecgberht/converse` already carries
the server-side turn-completion hook, so enforcement is unchanged; the refusal must paint
in the slice with the signed `AG-BLOCKED-TURN` shape (`.msg.steward.blocked`) and the wave
asserts it is VISIBLE — an engine-green E1 whose refusal never appears is a FAILURE of this
wave, not a pass. **The survival test** (`tests/test_chamber_m1_survives_w1.py`, Playwright,
**REQUIRED — no `pytest.importorskip`**): open the Seal, wait for BOTH `seal_open` and
`/api/ecgberht/chamber` to settle, pierce `slice.shadowRoot`, assert the M1 skeleton is
still in the document. It may **NOT** `route.abort()` the chamber route —
`tests/test_chamber_first_paint_w6.py` aborts `**/api/ecgberht/chamber?*`, and that abort
is how this defect stayed green for twelve waves; a CI rule fails any chamber paint test
that aborts a successor-hydrate route. C9 must still pass unchanged (the pin holds).
AUTH-ON header on every new `tests/test_chamber_*.py`.

**done-when:** Opening the Seal leaves M1 on screen after hydration on every branch; the
say box sends and the reply paints in mockup classes; the E1 refusal is asserted visible;
the survival test passes and the abort-ban rule is active; C9 and the full gate are green.

- **Given** the Seal opened and hydration complete, **when** the DOM is inspected, **then** the M1 skeleton is still present inside `slice.shadowRoot` — on the chamber-success, stand-up and error branches alike
- **Given** John types in the drawn say box and sends, **when** the turn runs, **then** it posts to `/api/ecgberht/converse` and the reply paints into `.msgs` with `.msg.steward`
- **Given** a turn that E1 blocks, **when** the refusal paints, **then** it carries `.msg.steward.blocked` and is VISIBLE in the slice — engine-green alone does not satisfy this row
- **Given** the slice markup, **when** C9 diffs it, **then** it still matches the pinned hash — `data-*` hooks do not change a `(tag, classes)` signature

---

## Wave 2 — Delete v0, in both trees

**Depends on:** Wave 1 — Stop the delete, wire talk

**Intent:** Remove the replaced surface and make its return a named CI failure. This is
the wave the original campaign never wrote.

**Deliverables:** `_ecgRenderChamber`, `_ecgRenderStandUp`, `_ecgSealDropSlice`, the
error-path dock and the v0-only CSS (`.ecg-dock` / `.ecg-convo-col` / `.ecg-saybox` /
`.ecg-goalbar` / `.ecg-rail` / `.ecg-footer` where M1 does not reuse them) DELETED, along
with the v0-only helpers left unreferenced by Wave 1 (`_ecgRefreshRail` if it has no
caller, `_ECG_OPENED_DRIVE`, `_ecgGrowingInput`, the v0 message painters). **The Ecgberht
sibling rewritten IN THIS WAVE** — `test/w11-seal-chamber.test.mjs` pins
`function _ecgRenderChamber`, the chamber route, `chamber.footer_stamp` and the v0 CSS
classes, and `test/w14-standup-canaries.test.mjs` pins `_ecgRenderStandUp`;
`scripts/run-all-tests.mjs` runs that lane, so deleting without rewriting these reds this
plan's own gate. **Replacement guard** (`tests/test_chamber_v0_is_gone_w2.py`) greps
**BOTH trees** — the JS symbols in Anchor product source AND
`SEAL_CHAMBER_SCHEMA_ID = 'ecgberht-seal-chamber-v0'` in
`C:\dev\Ecgberht\engine\seal-chamber.mjs` — failing BY NAME and BY TREE on any return.
The guard is NOT load-bearing on its own: a future `getElementById('ecgSealSlice').remove()`
or `host.innerHTML = ''` evades a name grep, so **Wave 1's survival test is the real
recurrence instrument** and must stay required and non-skipping. `/api/ecgberht/chamber`
is **KEPT as a data API** — `speak` / `converse` / `commission_*` compile against that
view-model; only the v0 RENDERER dies, not the engine VM — with its routes-inventory row
updated. `tests/test_steward_goal_authon_2026_07_30.py` waits on `#ecgStandUpGoal` /
`#ecgGoalBar` / `#ecgConvo` / `#ecgSayInput` and is not in the deselect list: retarget it
onto the slice or record it on the TEST-DEBT-REGISTER and deselect — as a done-when, not
an afterthought. Distro manifest updated for any removed file.

**done-when:** v0 exists in neither tree; the guard passes and fails by name on any
return; the survival test still passes; the Ecgberht lane is green on rewritten pins; the
full gate is green with E1 intact.

- **Given** product source in both repos, **when** the guard runs, **then** no v0 symbol or schema id is found; **when** any is re-introduced, **then** CI fails naming the symbol and the tree
- **Given** a future change that removes the slice by any means, **when** the gate runs, **then** the survival test fails — the survival test, not the name grep, is what makes the law hold
- **Given** the chamber route after this wave, **when** `speak` / `converse` / `commission_*` run, **then** they still resolve — only the renderer was deleted

---

## After Wave 2 — the human-eyes gate (not a Foreman wave)

**John opens the steward and confirms it changed.** Not a test result — his eyes. Every
automated gate on this surface has been green while it was broken: twelve waves, a signed
mockup, a hash-pinned DOM diff and a cross-family adversarial review with zero objections,
all green while the surface was being deleted on every open. The only instrument that ever
caught it was John looking. The campaign is not done until he has.

## Standing rules

- **Replace means replace.** No wave keeps v0 alive as a fallback; a fallback to the
  replaced surface is this defect recurring.
- **M1's drawn design is the spec.** v0 affordances are not entitled to survive.
- **Re-home, never re-author.** Behavior binds to drawn elements via `data-*`; drawn
  markup is hash-pinned and does not get rewritten.
- **Engine-green is not proof of a drawn surface.** Any criterion with a visual half needs
  an assertion that the pixels exist.
- **ok:false / timeout-killed / a wave that wrote nothing are LOUD halts** (foreman 0102).
  Launch `run-live.mjs` directly with `--call-timeout-min 45` — this is cross-repo.
- Hermetic tests, AUTH-ON tags, stdlib only, manifest in-wave, gate scope includes
  distro/ship.
