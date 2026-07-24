# Install guide — Shareable skills + Anchor (Package A / B)

**All rights reserved.** This software is **not open source**. It is **not** licensed under MIT, Apache, GPL, BSD, or any other open-source license. Redistribution and use are by permission of the author only. There is no OSS license stamp in this package.

This page is the email-ready stranger install doc: clone or unzip, then run the guided cold-start. Plain ASCII preferred so it pastes cleanly into mail and terminals.

---

## 1. Cold start (sole bootstrap)

1. **Clone or unzip** this package onto the machine.
2. Open a terminal in the **package root** (the folder that contains `share_onboard.py`).
3. Run:

```text
python -m share_onboard
```

That is the **only** cold-start entry. Use `python -m share_onboard` (or the thin `onboard_cli` alias), **not** the `/onboard` skill — `/onboard` is for after skills are already installed.

**Do not** expect a ready install from silent or `--non-interactive` mode. That path is fail-closed: it never stamps ready. You must complete the interactive dialogue (or an equivalent fully-specified guided run).

### Hard dependency

- **Python 3.8+** on PATH. If Python is missing, onboard stops with fix links (python.org downloads). Other CLIs (Claude / agy / Grok) are detected and linked, not auto-installed.

---

## 2. Package A vs Package B

Onboard **auto-detects** A or B from the tree (or you can choose).

| | **Package A — skills only** | **Package B — Anchor + skills** |
|--|-----------------------------|----------------------------------|
| Skills under SKILLS_ROOT | Yes | Yes |
| Multi-host register (Claude pointer, Grok paths, Anchor env, …) | Yes | Yes |
| Governance AGENTS pointers | Yes | Yes |
| Seat probe (claude / agy / grok) | Yes | Yes |
| Anchor service | **Never** starts | Starts + **HTTP probe** of local dashboard |
| Desktop icon | No | Yes — shortcut with **anchor.ico**, URL = probed dashboard |
| Favicon / skill icons | N/A (no dashboard) | Favicon (`/favicon.ico` / `/anchor.ico`); portfolio skill icons with skills |

**Package A ready** means skills + governance + honest hosts_registered and at least one coding seat (zero seats → not-ready, non-zero exit). A never requires a live dashboard.

**Package B ready** is a **dual gate** (both required):

1. Local dashboard **HTTP probe OK**, and  
2. **Desktop shortcut exists** with universal **anchor.ico** (IconLocation contract via `create_shortcut` / same branding) **and** the shortcut URL equals the probed dashboard URL.

A bare `.url` without the Anchor icon is **not** B-complete. Service start failure, probe failure, or silent foreground-only fallback alone must **not** report B success — status is not-ready / B-incomplete with non-zero exit.

---

## 3. What the dialogue walks through

Locked order (what you will see):

1. **Home picker** — recommended `C:\dev` on Windows (overridable).
2. **Python detect** / PATH fix links — hard fail if Python is missing.
3. **Package A | B** auto-detect.
4. **Permissions list** — what will be written (skills, governance, and for B: scaffold / service / desktop).
5. **Install + host register** — product skill bytes once under SKILLS_ROOT; Claude is pointer-only (no second full tree).
6. **Governance** — AGENTS body + thin host pointers (Claude / Grok / …).
7. **Seat probe** — session-visibility for claude, agy, grok (not API-key fallback).
8. **Feedback consent** — default **No** (see below).
9. **Package B** — service start + desktop/icon dual gate (A skips; never starts service).
10. **Readiness stamp** + next steps.

---

## 4. Feedback step (step 8)

Onboard asks whether to share **sanitized skill-friction** reports. **Default is No.**

- **What may be shared (only if you opt in):** skill name + version, outcome class, structural failure codes, coarse size/duration bands, OS class, model-family seats, coded workaround categories, and a random de-identified install key (not your name).
- **What is never shared:** full local journals, session content, prompts, file contents, project purpose, emails, usernames, absolute host paths, secrets, or what you were working on.
- **Residual risk (stated honestly):** in a very small cohort, patterns across reports could theoretically re-identify an install. The key is random and rotatable.
- **Decline** leaves skills fully usable; **no install_key** is minted.
- Feedback is **not** a readiness gate — you can be ready with consent off.

---

## 5. Package B: service + icons (happy path)

When the tree is Package B, onboard also:

- Scaffolds Anchor data under the chosen home and starts the local service path.
- Probes the local dashboard (typically `http://localhost:8777`).
- Places a **desktop** shortcut branded with **anchor.ico** targeting that same URL.
- Ships brand assets so the dashboard **favicon** resolves and skill lists show portfolio icons (documented default fallback if a skill has no custom icon).

If the service or probe fails, treat the install as **not ready** for dashboard use even if skills registered. Re-run after fixing the service, or use Package A if you only need skills.

---

## 6. After a successful run

- **Package A:** open your coding CLI and try a portfolio skill (for example `/gandalf`).
- **Package B:** open the **Anchor Dashboard** desktop icon only after the dual gate passed (live dashboard + branded shortcut).
- Re-running onboard is intended to be **idempotent** (no dual Claude copy of product skills).

---

## 7. Rights reserved (not open source)

**All rights reserved.**

This distribution is **not open source** and carries **no open-source license stamp**. Do not add or assume MIT, Apache, GPL, or similar grants. Use and redistribution are by author permission only.

For operators: the support email-ready “what the user sees” for a later sandbox transcript gate is this dialogue (`python -m share_onboard`), not a silent installer log.
