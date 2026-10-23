# 2026-10-22 — Doctor 300-Step Compaction Fix & Wave 21 Anvil/Poincaré/Librarian KB Completion

## 1. Root Cause of the 300-Step Doctor Investigation & Context Compaction
- **Symptom:** Doctor session `358f6418-41dc-4e97-a978-343f3849ac99` ran for ~30 minutes (300 LLM steps) and triggered context compaction when resolving a transient health report.
- **Root Cause (`doctor_plain.py`):**
  1. `_UNREACHABLE` regex in `doctor_plain.py` matched `unreachable`, `timed out`, and `connection refused`, but missed Python's `TimeoutError` (`[the running service: GET /] answered TimeoutError`), classifying a transient HTTP probe timeout as `KIND_OTHER`.
  2. `decide()` checked `if all(r["kind"] == KIND_SELF_TEST_UNREACHABLE for r in rows): return "rerun"` and `if all((r.get("recipe") or {}).get("fix") == "rerun" for r in rows): return "rerun"` as two disjoint all-or-nothing conditions. Whenever a transient `KIND_SELF_TEST_UNREACHABLE` row co-occurred with a playbook `"rerun"` recipe row (`supervisor-seam-5am-load`), neither `all(...)` branch matched, causing `decide()` to fall through to `"session"` and spawn a full interactive LLM session.
- **Permanent Fix (`doctor_plain.py`):**
  1. Added `timeouterror` to `_UNREACHABLE`.
  2. Unified `decide()` with per-row `_row_can_rerun(r)` (`r["kind"] == KIND_SELF_TEST_UNREACHABLE or (r.get("recipe") or {}).get("fix") == "rerun"`) so any combination of unreachable probes and playbook rerun recipes resolves deterministically in `<5 seconds` via `rerun` + `tools/doctor_fix.py --auto`.

## 2. Wave 21 (`wave21-skill-foundry-mapping`) & 3-Stage KB Study
- Programmatically analyzed and mapped all 19 Foundry skills (`ANVIL-MAP.json`, `library.json`, `process-map.json`, `knowledge-map.json`) with 3-Level Progressive Abstraction, Pure Functional Core / Imperative Shell remapping proposals, and interactive step-through walkthroughs (`/foundry/anvil?skill=<id>`).
- Expanded all 19 Poincaré disk maps to include Reusable Material, Programmatic Tools, Peer Skills, and Knowledge Sources/Repositories, backed by `librarian_kb.py` (`SQLite + WAL + FTS5 + Mixed-Curvature Product Manifold` $\mathcal{L}^2_1 \times \mathbb{S}^1_1 \times \mathbb{E}^8$).
