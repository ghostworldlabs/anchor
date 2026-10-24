# Anchor Onboarding Walkthrough, Merrill Feedback & Cave UI Plan — Pre-Reboot Archive
**Archived:** 2026-10-24T17:09-06:00  
**Latest Commits:**
- `C:\dev\Anchor` (`origin/master` -> `E:\anchor.git`): `21c5083`
- `https://github.com/johncliechty/ghostworldlabs-anchor.git` (`main`): `56d8f66`
- `https://github.com/johncliechty/anchor-plus-skills.git` (`main`): `cd8aff6`

---

## 1. Current Objective & Active Walkthrough Plan
We are walking through and hardening the **End-to-End First-Run Install & 7-Step Guided Onboarding Flow** on John's Windows 11 work desktop using an isolated test package (`Anchor-Test-Onboard.zip`) while keeping John's live `Anchor.exe` (connected via Tailscale to Puter on `:8777`) 100% untouched.

### Completed & Shipped Before Reboot
1. **Isolated Work-Desktop Test Package (`Anchor-Test-Onboard.zip` & `Anchor.zip`):**
   - Served via 1-click header buttons (`🧪 Desktop Onboard-Test.exe` and `📦 Anchor.exe`) in Cave of Wonders (`/high-seat`), `/onboard-wizard`, and `/website` (`/static/downloads/Anchor-Test-Onboard.zip?download=1` and `/static/downloads/Anchor.zip?download=1`).
   - Built by [`build_or_resolve_exe_zip_package`](../onboard_wizard.py) and [`build_exe.ps1`](../shell/build_exe.ps1).
   - Contains `Anchor/anchor-test-mode.json` (auto-detected by [`_apply_bundled_test_mode`](../shell/connect.py) in `shell/connect.py` and `shell/anchor_shell.py`), `Launch-Anchor-Onboard-Test.cmd`, and `Reset-And-Clean-Test-Onboard.cmd`.
   - Runs in an isolated window (`Anchor (test onboard-walkthrough)`), isolated AppData (`%LOCALAPPDATA%\anchor-shell-test-onboard-walkthrough`), isolated port (`8787`), and isolated install directory (`C:\dev\Anchor-Onboard-Test`).

2. **Live Progress Bar + Elapsed Timer + ETA on Mother Ship Pull (`shell/connect.py` & `shell/anchor_shell.py`):**
   - Added a 4-stage live progress bar (`Step 1/4` through `Step 4/4`), elapsed `M:SS` timer, and expected duration (`Typically 15–35s on first run, <5s if cached`) when pulling the Mother Ship and 19 Foundry Skills.

3. **Fixed `http://127.0.0.1:8787/onboard-wizard` `HTTP 404` Error:**
   - Root cause: `ghostworldlabs-anchor.git` on GitHub previously lacked `onboard_wizard.py` and the `/onboard-wizard` route in `anchor_gui.py`.
   - Fixed in two ways:
     1. Pushed the updated `onboard_wizard.py`, `anchor_gui.py`, and UI modules directly to `ghostworldlabs-anchor.git` (`56d8f66`) and `anchor-plus-skills.git` (`cd8aff6`).
     2. Bundled `Anchor/anchor-core-overlay.zip` inside `Anchor-Test-Onboard.zip` (and `Anchor.zip`) and wired `_apply_bundled_core_overlay()` + `route_reachable(LOCAL, "/onboard-wizard")` in `shell/connect.py` so the local server is guaranteed to have `/onboard-wizard` before the window navigates.
     3. Added `_local_login_cookie()` to `GET /onboard-wizard` in `anchor_gui.py` so the local WebView2 session is automatically authenticated.

4. **Cave of Wonders AI Cockpit Tile Dots (`static/high-seat-page.css` & `static/high-seat-page.js`):**
   - Updated [`syncCompactActs`](../static/high-seat-page.js) with [`measureNaturalTextWidth`](../static/high-seat-page.js) so tile action buttons (`▾ On deck` / `▴ Active`, `✓ Done`, `cockpit ↗`) collapse early into an **`8px` blue dot**, **`8px` green dot**, and plain **`↗` arrow** as soon as the cockpit name comes within **`96px` of the buttons** (or whenever the tile is `< 520px` wide) — well before any project name gets cramped or truncated.
   - Hovering over the blue dot, green dot, or `↗` arrow expands that control inline back into its full button pill.

5. **All Merrill Feedback Fixes & 7-Step Guided Onboarding Wizard (`onboard_wizard.py`):**
   - **Step 1:** User Identity (`display_name`), Collaboration Pseudonym (`Samwise Gamgee` / aliases `Samwise Gamgi`), and consistent Steward Persona (`Aladdin`, `Jarvis`, `Ecgberht`) across Cave of Wonders and AI Cockpits.
   - **Step 2:** Mothership Topology (Main Mothership vs. Connect to existing Mothership over Tailscale) + automated Tailscale check/install.
   - **Step 3:** AI Services Menu (Claude, Gemini, Grok, ChatGPT) with Subscription CLI vs. API Key selector, CLI updater, and **Frontier vs. One Tier Down (`sonnet` / `opus` instead of credit-gated `fable`)** model selector + live verification probe.
   - **Step 4:** Goals & Missions (Star Chart Steward) OR jump straight to Projects; plain-English explanation of Mission / Goals / Initiatives and candidate proposals for Active vs. On Deck.
   - **Step 5:** Smart Directory Scan (Gandalf scanner + orphaned `.anchor/projects/<id>` re-adoption + exclusion checkboxes + virtual project groupings + 1-click Starter AI Cockpit scaffolding).
   - **Step 6:** Calendar & Email integration (`comms_connector.py`).
   - **Step 7:** Readiness Receipt & Launchpad into Cave of Wonders and AI Cockpits.

---

## 2. How to Resume After Reboot

1. **On Puter:**
   - The `anchor` Windows service (`:8777`) starts automatically on boot (or run `python C:\dev\Anchor\launch_anchor_dashboard.py` if needed).
   - Both download packages remain on disk at:
     - `C:\dev\Anchor\static\downloads\Anchor-Test-Onboard.zip`
     - `C:\dev\Anchor\static\downloads\Anchor.zip`

2. **On Your Work Desktop (Continuing the Onboarding Walkthrough):**
   - Download the latest `Anchor-Test-Onboard.zip` via the **`🧪 Desktop Onboard-Test.exe`** button in the top-right header of Cave of Wonders (or `http://<puter-tailscale-ip>:8777/static/downloads/Anchor-Test-Onboard.zip?download=1`), unzip it, and run **`Launch-Anchor-Onboard-Test.cmd`**.
   - Click **"This computer is my mother ship"** -> watch the new **4-stage progress bar & timer** -> walk through **Steps 1 to 7** of `/onboard-wizard` and share any next round of feedback as you go!
