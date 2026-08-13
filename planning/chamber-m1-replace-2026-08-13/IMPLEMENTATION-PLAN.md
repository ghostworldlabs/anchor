# Replace the v0 chamber with M1 — Implementation Plan (Foreman-ready)
# Three waves. The deletion is the point; the parity proof is what makes it safe.

test-command: node scripts/run-all-tests.mjs

**North Star:** The M1 chamber is the surface on screen at steady state, carrying
every affordance v0 carried or a John-signed named loss — and **v0 is deleted from
the tree**, enforced by CI. Success is not "M1 renders"; M1 already renders. Success
is **M1 survives hydration and v0 no longer exists**.

**Acceptance oracle:** a steady-state DOM test — open the Seal, let hydration
complete, then assert the M1 slice is present and carries the M1 schema AND
`ecgSealDock` is absent. That test must go RED on today's tree in Wave 1 (proving it
detects the live defect) before any wave is allowed to turn it green.

**Anti-goals:** no new UI beyond the signed mockup; no engine-spine changes; no tile
retirement (that gate stays UNSIGNED); no change to E1 enforcement.

---

## Wave 1 — Parity inventory + the steady-state kill gate (must go RED)

**Intent:** Establish what v0 actually does and land the instrument that proves the
defect, before anything is moved or deleted. This is the wave that makes the other
two safe. Serves the North Star's oracle.

**Deliverables:** Chamber-affordance inventory as versioned machine-readable data
(`chamber/chamber-affordance-inventory.json`, schema_version + named owner file),
one row per affordance rendered by `_ecgRenderChamber` (7788–7899) **and** per
affordance that binds to its DOM elsewhere in the file — the say box
(`.ecg-saybox`, `ecgSayInput`, `_ecgSayLine`), the conversation column
(`.ecg-convo-col`), Refine, commission-propose, the goal row, the titlebar, the
run block, the footer stamp — each carrying: v0 source marker (grep-verifiable
symbol + line), the M1 drawn target (mockup element/class from §M1 or §overlays),
and a resolution of `equivalent` / `gap` / `proposed-loss`; **STEADY-STATE KILL
GATE** (`tests/test_chamber_steady_state_w1.py`): render the project window, run
the mount path to completion including hydration, then assert (a) `#ecgSealSlice`
present, (b) it carries the M1 schema marker, (c) **`#ecgSealDock` absent** — and
this wave lands it RED against the current tree with the failure named
`M1-SLICE-DROPPED-BY-V0-HYDRATE`, then marks it xfail-with-reason so the wave can
close green while the defect stands (the xfail is REMOVED in Wave 3 — a wave may
not both prove and cure a defect); a CI grep-guard that fails if
`_ecgSealDropSlice` gains any new call site; `chamber/CHAMBER-PARITY-GATE.md` — the
John gate carrying every `gap` and `proposed-loss` row for signature, prepared
UNSIGNED, with a fail-closed reader (`parity_state`) mirroring
`chamber_e1_bound.ratification_state`.

**done-when:** Every v0 affordance has an inventory row with a grep-resolvable
source marker and a named M1 target or gap; the steady-state test exists, is RED
against today's tree for the named reason, and is xfail-pinned to that reason; the
parity gate doc is prepared UNSIGNED and its reader fails closed.

- **Given** the current tree, **when** the steady-state test runs unpinned, **then** it FAILS with `M1-SLICE-DROPPED-BY-V0-HYDRATE` — a test that passes here is not testing the right thing and is a wave defect
- **Given** the inventory, **when** the CI symbol-check runs, **then** every row's v0 source marker grep-resolves in its owner file and every `equivalent` row's M1 target resolves in the pinned mockup
- **Given** an affordance in `_ecgRenderChamber` with no inventory row, **when** CI runs, **then** it fails by name — the inventory is complete by construction, not by inspection

**HALT — JOHN GATE (chamber parity).** Present the `gap` and `proposed-loss` rows as
prose, one decision at a time, recommendation before the question. Wave 2 may
re-home only against a SIGNED parity map; Wave 3 may delete only against one.

---

## Wave 2 — Re-home every affordance onto the M1 slice; v0 stops mounting

**Depends on:** Wave 1 — Parity inventory + the steady-state kill gate

**Intent:** Move interactivity onto M1's drawn structure inside the shadow root, and
stop dropping the slice. v0 remains in the tree but is no longer mounted, so M1 is
proven to stand alone before anything is deleted. Serves C12 (re-home, never
reimplement).

**Deliverables:** Every `equivalent` row from the SIGNED parity map re-homed onto its
M1 drawn element — bound inside the slice's shadow root (`shadowRoot.querySelector`,
retargeted events), never by re-authoring markup: the mockup markup is the pin and
must stay verbatim; say-box path re-homed whole (input, submit, the paced-PTY write
path, E1's turn-completion hook seam — E1 must remain engine-enforced and its suite
green); Refine / commission-propose / goal row / run block / footer stamp re-homed
per their rows; **`_ecgSealDropSlice()` removed from the hydrate path** and its
`_ecgSealStopPulsePoll` lifecycle re-pointed to slice close; `_ecgRenderChamber` no
longer invoked from `ecgSealMountInline` (call site removed; the function still
exists — deletion is Wave 3) with the error-path dock replaced by an M1-drawn
honest-failure state from §amendments (never a bare v0 fallback: a fallback to the
replaced surface is the defect recurring); the steady-state test UNPINNED for
assertions (a) and (b) — the slice survives and carries the M1 schema — with (c)
still xfail because v0 symbols remain until Wave 3; auth-ON + F6 red-to-green for
any re-homed mutator with its routes-inventory row.

**done-when:** Opening the Seal leaves the M1 slice on screen at steady state
carrying the say box and every signed-equivalent affordance; `_ecgSealDropSlice` has
no hydrate call site; `_ecgRenderChamber` has no caller; the E1 suite and the full
gate stay green.

- **Given** the Seal opened and hydration complete, **when** the DOM is inspected, **then** `#ecgSealSlice` is present and carries the M1 schema marker
- **Given** the say box inside the slice, **when** John types and submits, **then** the message travels the EXISTING paced-PTY write path and E1's turn-completion hook still blocks a close on an unanswered ratified question
- **Given** the chamber endpoint failing or returning no chamber, **when** the mount path runs, **then** the honest-failure state is an M1-drawn state — never `_ecgRenderChamber`
- **Given** the slice markup after re-homing, **when** the C9 DOM diff runs, **then** it still matches the pinned hash — re-homing binds behavior, it does not edit drawn markup

---

## Wave 3 — Delete v0. Replace means replace.

**Depends on:** Wave 2 — Re-home every affordance onto the M1 slice

**Intent:** Remove the replaced surface from the tree and make its return a CI
failure. This is the wave the whole plan exists for. Serves the new law.

**Deliverables:** `_ecgRenderChamber` DELETED, together with every symbol that
existed only to serve it — `.ecg-dock` / `.ecg-convo-col` / `.ecg-saybox` CSS in
`static/project-window.css` where not reused by M1, `_ecgSealDropSlice` itself, and
any v0-only helper the inventory marks as unreferenced after Wave 2; the
`/api/ecgberht/chamber` route retired or reduced to whatever M1 genuinely consumes,
with its routes-inventory row updated (deny-by-default: if M1 does not consume it,
it goes); the steady-state test FULLY unpinned — assertion (c) `#ecgSealDock` absent
now passes and the xfail marker is gone (a leftover xfail is a wave defect); **a CI
REPLACEMENT GUARD** (`tests/test_chamber_v0_is_gone_w3.py`): the v0 symbols
(`_ecgRenderChamber`, `ecgSealDock`, `ecgberht-seal-chamber-v0`) must not appear in
product source — failing BY NAME if any returns, so a future wave cannot
re-introduce the replaced surface; `chamber/chamber-affordance-inventory.json` rows
flipped to `retired` with the signature reference; `chamber/CHAMBER-PARITY-GATE.md`
recording John's signature and the deletion date; distro manifest updated for any
removed file.

**done-when:** `_ecgRenderChamber` and the v0 schema exist nowhere in product source,
the replacement guard fails by name if they return, the steady-state test passes
fully unpinned, and the full gate is green with the E1 suite intact.

- **Given** product source after this wave, **when** the replacement guard greps for the v0 symbols, **then** none are found and the guard passes; **when** any is re-introduced, **then** CI fails naming the symbol
- **Given** the steady-state test, **when** it runs with no xfail markers, **then** all three assertions pass
- **Given** the parity map, **when** the wave closes, **then** every row is `equivalent`-and-re-homed or a John-signed loss, and none is silently dropped

---

## Standing rules for all three waves

- **The deletion never precedes the proof.** Wave 3 may not run until Wave 1's parity
  map is SIGNED and Wave 2 has M1 standing alone.
- **A fallback to the replaced surface is the defect recurring.** No wave may keep v0
  alive "just in case" — that is precisely how this happened.
- **Re-home, never re-author.** The slice's markup is hash-pinned to the signed
  mockup. Behavior binds to drawn elements; drawn elements do not get rewritten.
- **A wave may not both prove and cure a defect** (the W12 lesson): Wave 1 lands the
  failing instrument, later waves turn it green.
- **agent-launch-failure and ok:false are loud halts** (foreman journal 0102), and
  this is a cross-repo-shaped surface — launch with `--call-timeout-min 45`.
- Hermetic tests, auth-ON tags, stdlib only, manifest in-wave, gate scope includes
  the distro/ship family.
