# Aegis — Operational Lessons & Field Ledger (`LESSONS.md`)

1. **2026-10-20 — Naming Collision Avoided (`Sentinel` → `Aegis`):**
   - Anchor already operates a runtime process-health monitor called `sentinel`. Naming the defensive code-security scanner & auto-remediation skill **`Aegis`** keeps process-liveness monitoring and OWASP/CWE static security remediation completely distinct across CLI tools, Cockpit tabs, and Foundry maps.
2. **2026-10-22 — Explicit Contained-Boundary Sign-Off Prevents Alert Fatigue:**
   - Not every `subprocess.Popen` or `md5` call is an exploitable vulnerability (for example, Windows Job Object sandbox runners or non-cryptographic UI cache keys). Storing human-reviewed sign-offs with explicit rationale in `.aegis/signed-off.json` lets `Aegis` separate active vulnerabilities from audited architectural boundaries without weakening the AST scanner.
3. **2026-10-27 — Foundry North Star & Map Completeness:**
   - Every first-class Foundry skill requires a locked `NORTH-STAR.md`, a structured `HUMAN.md` with `**One sentence:**` and `## How it works`, a multi-section `SKILL.md` (`name: Aegis`), and synchronized `library.json`, `process-map.json`, `knowledge-map.json`, and `ANVIL-MAP.json` bundles so operators and agents can inspect the full progressive abstraction map.
