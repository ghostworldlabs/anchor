# Setup gear in John's actual Anchor interface — repair evidence (2026-10-06)

## Actual cause (established, not inferred)

John's window is the Anchor program: the app shell page `static/app.html`, whose title bar (`#bar`)
is the real upper-left corner of Anchor. The approved gear was delivered only into the **Cave page's
own rail head** (`high_seat_page._rail`, `#setup-gear` inside `.provider-rail-head`) — a page the shell
shows **inside a pane iframe below its title bar**. Before this repair, `static/app.html` contained **no
gear element at all**, so no cache state, reload or restart could have shown one in Anchor's upper-left
corner. This is a surface mismatch, not staleness: the prior live check drove a fresh Chromium at the
service root `/`, where the Cave page stands alone and its rail head *is* the page's upper-left (the
x8,y12 observation). That check never inspected the shell surface, which is where John looks.

Surfaces distinguished: Anchor's outer window/header = `static/app.html` `#bar` (gear was absent) ·
Cave's page header/rail = `high_seat_page` inside the pane frame (gear present and working) · the
Setup page itself = `/setup` (saved settings, unchanged).

## Repair (smallest compatible)

- `static/app.html` — a `#setup-gear` button is now the bar's FIRST element, shifting the Anchor mark
  right, per John's original requirement.
- `static/app.css` — upper-left placement in the bar (28px, amber, no-drag inherited from `#bar button`),
  hover/focus-visible states; desktop and narrow layouts share it.
- `static/app.js` — the gear opens the existing saved `/setup` page through the shell's own tile
  machinery (`api.open`); `/setup` and `/setup/install` are classified as Anchor pages, so repeated
  opens reuse ONE tile (no second conversation, no reload of a live Setup frame); the Setup page's
  "Return to Cave" (`anchor-setup-close` postMessage) now brings the Cave back to that pane. The Cave
  page's own gear is preserved untouched.

Nothing else changed: no model preferences, secret storage, native account behavior, campaign state,
skill scripts, service restarts or session kills.

## Checks

Gate: `python -m pytest -v tests/test_provider_setup_anchor_shell.py tests/test_provider_setup_browser.py`
(run by the orchestrator). The new shell tests drive the REAL production surface — the real server
(`anchor_gui.make_server`) serving the real `static/app.html`/`app.js`/`app.css` and the real `/setup`
page with normal HttpOnly-cookie login — and assert: gear visible on the SHELL document's bar at the
upper-left with the mark to its right (desktop 1440×1050 and narrow 390×844); keyboard open (focus +
Enter); the saved Setup page renders with its settings populated through normal browser auth; repeat
opens reuse one tile and one live frame (an in-page marker survives); Return-to-Cave restores the Cave
pane; a Cave composer draft survives the whole round trip; steady-state rendering with no overflow and
no script errors. Display-only guard: steward event soft-wake GETs (`/api/steward/events|status-ack`)
and EVERY POST besides the login are blocked and asserted silent, so the checks cannot resume another
effort or launch work. The existing provider browser regression (Cave gear, dialog, drafts, settings
retention) runs alongside unweakened.

## Actual-window evidence and remaining boundary

This execute seat runs file-edit-only (the orchestrator owns process execution and version control), so
no UI-Automation/screen capture of the currently open WebView2 window was taken from this seat. The
cause does not depend on that capture: the shell page his window renders had no gear element in its
markup, which no client-side state could overcome.

**Runner side effect (`foreman.config.json`):** the execute seat left the runner-written root
`foreman.config.json` byte-for-byte as the runner wrote it (no edits of its own). Restoring the original
checkout bytes (SHA256 `fc14e59db8f6c50fbd6ed3dd7b0d260da7a1d90293c551f5d2e8dd157bf8ddf4`) requires
reading the committed version, and this seat's terminal access was denied (read-only `git show` +
hash attempt refused by the harness; no on-disk backup exists and the prior job's worktree is gone).
The orchestrator, which owns version control, can restore it losslessly with
`git checkout -- foreman.config.json` (or exclude the file from the placement) before landing, so the
placement contains only the intended production/test/evidence changes.

**Activation requirement (stated, not claimed live):** `static/app.html`/`app.js`/`app.css` are served
from disk, so once this change lands in the live checkout the service needs NO restart — but John's
already-open Anchor window loaded the shell page at its start and keeps it for the window's lifetime.
The gear appears the next time that window loads the shell page (reopening the Anchor program, or a
reload John triggers once his drafts are safe). No forced reload, session kill or restart is performed
by this repair; until that reload, the running window intentionally still shows the old bar.
