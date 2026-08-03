# Share note — paste-ready message for collaborators (v1.1.3)

> Subject: Anchor v1.1.3 — fixed install, please give it a try
>
> Hi — thanks for your patience with the last drop; the install was genuinely
> broken (missing modules in the package) and your error reports are what got
> it fixed. v1.1.3 is a recovery release that has been through an automated
> "stranger install" test suite.
>
> **Pick one zip:**
> - `Anchor-plus-skills-v1.1.3.zip` — the full product: a local dashboard at
>   http://localhost:8777 (nothing leaves your machine) + 13 Claude Code
>   skills. Most of you want this one.
> - `Skills-only-v1.1.3.zip` — just the skills for Claude Code, no server.
>
> **Install (Windows):**
> 1. Right-click the zip → Properties → check "Unblock" → OK. Extract into
>    `C:\dev` (make the folder if needed). Keep this folder — your Anchor
>    data will live inside it.
> 2. Open a terminal in the extracted folder and run:  `.\onboard.cmd`
>    (it installs Python via winget if you don't have it, walks you through
>    a short dialogue, installs the skills, and sets up the dashboard).
> 3. Start it:  `python launch_anchor_dashboard.py`  (or the new desktop
>    icon). After any reboot, just run it again.
>
> **For the AI features** (in-dashboard terminals, research/plan/build
> sessions) you also need the Claude Code CLI + your subscription
> (`npm install -g @anthropic-ai/claude-code`), plus git and Node.js. The
> dashboard works without them — AI features just report unavailable.
> Nothing spends your Claude subscription without an explicit action by you.
>
> **If ANYTHING is broken or annoying** — this is the important part —
> please take 30 seconds in the package folder:
> ```
> python doctor.py
> python anchor.py journal "what hurt" --severity problem --body "what you did + any error text"
> python anchor.py friction-report
> ```
> and send me the friction-report output. That exact loop is how the last
> round of bugs got found and fixed.
>
> Full instructions are in `USER-ONBOARD.md` inside the zip. All rights
> reserved — please don't redistribute.

## Notes for John (not part of the message)

- Zips + SHA256SUMS live at `C:\dev\Anchor-ship\` — attach or share via
  Drive/OneDrive if over mail limits.
- This drop goes out BEFORE the Windows-Sandbox VM check (reboot pending,
  John traveling — accepted 2026-08-02). Evidence base: build sandbox 10/10,
  pull dry run 7/7, clean-profile run 8/8 — all against the final artifact.
  The genuinely-untested residue: a foreign Windows image and the
  winget/python.org bootstrap on a python-less box; both degrade with honest
  printed instructions if they fail.
- After the reboot: `python C:\dev\Anchor-ship\vm-sandbox\host_run.py`, then
  resolve friction `2026-08-02-05`.
