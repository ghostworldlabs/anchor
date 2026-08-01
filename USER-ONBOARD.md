# Install guide — Shareable skills + Anchor (Package A / B)

**All rights reserved.** Not open source. Use by author permission only.

This is the short path for collaborators. Plain ASCII for mail and terminals.

---

## Super-simple path (Windows)

### 1. Open a terminal where you want everything installed

Recommended: `C:\dev` (create it if needed).

- File Explorer → that folder → address bar → type `cmd` or `powershell` and Enter  
- Or VS Code / Cursor → Open Folder → that directory → Terminal  

### 2. Get the package (git)

**Package B — Anchor + skills (full product, desktop icon):**

```text
git clone <YOUR-ANCHOR-OR-PACKAGE-B-URL> anchor-plus-skills
cd anchor-plus-skills
```

**Package A — skills only (no Anchor desktop service):**

```text
git clone <YOUR-PACKAGE-A-OR-SKILLS-URL> skills-only
cd skills-only
```

(If you were given a zip instead of git: unzip, then `cd` into the package root.)

### 3. Run onboard (one command)

From the package root (folder that contains `onboard.cmd` and `share_onboard.py`):

```text
.\onboard.cmd
```

Or:

```text
powershell -File .\onboard.ps1
```

**What this does for you:**

1. Checks for **Python 3.8+**. If missing, tries **winget** to install it (Windows). If that fails, it points you at python.org and asks you to re-run.
2. Starts the **interactive** install dialogue — same as `python -m share_onboard`.
3. Asks/confirm **where** to put things (home; often under your chosen `C:\dev` tree).
4. Installs **skills** and registers them for your agent hosts. For Claude the
   register tries a symlink, then a **directory junction** (works on stock
   Windows — no admin, no Developer Mode), then a **full copy** as last
   resort, and reports which one it used. Every mechanism leaves a folder
   Claude Code can actually load (check: `%USERPROFILE%\.claude\skills\<name>`
   contains a real `SKILL.md`).
5. Probes **Claude / Gemini(agy) / Grok** subscription CLIs (at least one coding seat should be present to stamp ready).
6. Optional **feedback** — **default is No**.
7. **Package B only:** installs the optional **pywinpty** terminal extra
   (Windows; real in-browser terminals — if the install fails, onboard tells
   you the manual command and everything else still works), scaffolds a fresh
   empty Anchor, mints your local access **token** (stored outside the
   package, default `%USERPROFILE%\.anchor\.anchor\onboard-token`), and
   places an **Anchor** icon on the desktop (with **anchor.ico**).

You do **not** need to pre-install Python by hand when winget works.  
You do **not** use silent/`--non-interactive` for a real ready install (that path never stamps ready).

You can also run the dialogue directly after Python is available:

```text
python -m share_onboard
```

### 4. After Package B succeeds — starting Anchor

There is **no Windows service** — Anchor runs as a background process you
start with the launcher:

```text
python launch_anchor_dashboard.py
```

- The desktop **Anchor Dashboard** icon runs the same launcher.
- The launcher: if Anchor is already running it leaves it alone; if it is
  down it **starts the local server** (wiring in your access token — mutating
  APIs and terminals then require it automatically); then it opens the
  dashboard in your **default browser** (favicon / **anchor.ico** branding).
  The token is handed to the page once and immediately stripped from the URL.
- **After a reboot, run the launcher (or click the icon) again** — nothing
  auto-starts on login in this release.
- Optional: right-click the taskbar icon → pin.

### 5. After skills are installed — `/onboard` in Claude (etc.)

Once skills are registered, your coding agent may expose **`/onboard`** as a **re-run / help** path.  
**Cold-start for a new machine is still `.\onboard.cmd`**, not slash-onboard (slash needs skills already present).

---

## Package A vs B (what ready means)

| | **A — skills only** | **B — Anchor + skills** |
|--|---------------------|-------------------------|
| Skills + host register (symlink/junction/copy, reported) | Yes | Yes |
| Seat probe (claude / agy / grok) | Yes | Yes |
| Anchor server + local dashboard (launcher-started; HTTP probe) | No | Yes |
| pywinpty terminal extra (Windows) | No | Yes |
| Access token minted + wired by the launcher | No | Yes |
| Desktop icon (launcher-targeting, anchor.ico) | No | Yes |

Zero coding seats → not-ready (non-zero exit). Skills still may be on disk.

---

## If something is broken (cheap checks first)

1. `python doctor.py` — deterministic install health: missing modules,
   pywinpty, engine CLIs, token, server reachability. **No AI calls, free.**
2. Look at the tail of `logs\errors.log` under your data dir (default
   `%USERPROFILE%\.anchor`).
3. Only then ask an AI agent — and point it at THIS package folder (which
   carries an agent-notes `CLAUDE.md`), **never** at a full author monorepo
   dump. Do not use researchPrime / Crucible / Foreman / Gandalf to debug an
   install: those are intentional multi-agent tools that fan out many paid
   model calls.

---

## Feedback (optional)

Onboard asks whether to share **sanitized** skill-friction reports. **Default is No.**  
If Yes: coarse metadata only — not your files, prompts, or project content.

---

## Rights

**All rights reserved.** Not MIT/Apache/GPL. Redistribution only by permission.
