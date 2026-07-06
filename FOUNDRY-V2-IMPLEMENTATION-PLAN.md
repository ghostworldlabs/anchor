# Skill Foundry v2 — Implementation Plan (Foreman-ready)

test-command: python -m pytest -q

> **Build root:** `C:/dev/Anchor` · **Gate:** `python -m pytest -q` (Anchor's suite; new waves add coverage).
> Node-side units (kernel parser, GUI) are exercised via pytest integration so the single gate covers them.
> **Design:** `DESCRIPTION.md`. **North Star:** `../NORTH-STAR.md`. Every wave is gated against the North Star
> (anti-drift) and preserves the invariant set in DESCRIPTION. Claude writes code; a 3-Gemini panel reviews
> each wave (5:1). **Single-source:** skills are CONSUMED from `Skill Foundry/skills/<skill>`, never forked.

## Wave 1 — Phase 0: de-risking spikes → decision records
**Deliverables:** four committed, North-Star-tagged DECISION RECORDS (no production code): (1) Anchor API
contract — a two-column map of native READ/EXECUTE endpoints + on-disk artifact contracts vs. the MUTATIVE
verbs the control plane must supply; (2) isolation-runtime choice (WASM/container/microVM/Deno-perms) with a
measured cost/latency envelope, reconciled with lazy activation — or an explicit "permissions advisory for v2"
downgrade; (3) test-provenance taxonomy (human / agent+cross-model-verified / agent+human-ratified /
frozen-benchmark-delta) with per-class trust ceilings; (4) process-telemetry depth + droppable side-channel
design. A pytest checks each record exists and carries the required fields.
**done-when:** `python -m pytest -q` passes a test asserting the four decision records exist, are
North-Star-tagged, and name (a) the isolation runtime + cost, (b) the accepted provenance classes, (c) the
mutative-verb inventory for Wave 9–10.

## Wave 2 — Phase 1: host-enforced journaling write-back seam
**Deliverables:** the write-back seam in `gandalf.py`'s finalize path (Anchor already holds inputs/verdict/
timing/outcome) that auto-appends a 7-field entry (provenance; operation/kind; model+billed-cost+cache-tokens;
inputs-ref; outputs-ref; verdict+timing; outcome/linkage) to `<skill_dir>/journal/`; heavy I/O to a droppable
side-channel; a grep/drift gate proving no honor-system capture path remains; PLAN.md §7 backfilled as a
system-level journal.
**done-when:** `python -m pytest -q` shows every gandalf run through Anchor auto-journals a schema-valid 7-field
entry with zero author action, the droppable side-channel keeps the skeleton entry small, and the drift gate
fails if a capture path bypasses the seam.

## Wave 3 — Phase 2a: generic manifest-driven skill_runner core
**Deliverables:** generalize Anchor's `gandalf.py` consumer ADAPTER (NOT the skill) into one module
parameterized by a per-skill manifest (`skill_dir`, `host_cmd`, `output_contract`, panel meta, journal spec,
tier, declared capabilities + runtime pre-flight probe, lazy activation trigger, `op_kind` = `run`|`mutate`);
declare-then-resolve dispatch built from manifests WITHOUT executing skill code; the `mutate` kind requires a
confirm token + declared write-scope. The Wave-2 journaling seam moves into this runner.
**done-when:** `python -m pytest -q` proves the runner builds its dispatch table from manifests without
importing skill code, lazy activation fires only on the declared trigger, and a `mutate` op without a valid
confirm token / outside its write-scope is refused.

## Wave 4 — Phase 2b: re-express gandalf on the runner + prove on jumper
**Deliverables:** gandalf re-expressed as a manifest on the generic runner with NO behavior change (byte-parity
on the graded output for a fixture project); jumper (composes gandalf — the hard case) wired via a manifest
registry entry; a 3rd skill wired in under a small line budget; all three auto-journal via the runner seam.
**done-when:** `python -m pytest -q` shows gandalf-on-runner output parity vs. the legacy adapter, jumper
running end-to-end via its manifest, and the 3rd skill wiring diff under the declared line budget — all three
auto-journaling, none importing skill code to be discovered.

## Wave 5 — Phase 3: fix the sleep kernel + on-disk parser
**Deliverables:** normalize/auto-tag the kernel's situation CLUSTER KEY (kill the exact-string bug that never
fires on organic prose); an on-disk `journal/*.md` → kernel parser + validator; PLAN.md §7 fed as a
system-level journal. Node `node --test` units for the kernel; a pytest integration test drives the kernel
over the genuine corpus via subprocess.
**done-when:** `python -m pytest -q` (subprocess-driving the kernel) shows organic prose entries CLUSTER, real
on-disk journals PARSE + validate, and the kernel runs end-to-end on the genuine (non-fixture) corpus that
Waves 2–4 now fill.

## Wave 6 — Phase 4: sleep session as a gated action (THE LOOP CLOSES)
**Deliverables:** a sleep session implemented as a Phase-2 `mutate` op — a plan-mode PROPOSAL artifact
(candidate lessons + diffs + North-Star/eval-gate plan) → a SEPARATE confirm-gated apply-on-branch behind the
test gate; a FROZEN rollback-able baseline; improvement units are re-executable artifacts with a regression
test (provenance per Wave 1 §3); prose lessons gated via frozen-benchmark before/after; the human is the
promotion authority.
**done-when:** `python -m pytest -q` demonstrates, on the genuine corpus, a sleep session proposing a
test-gated improvement, a simulated human confirm applying it on a branch behind the gate, the frozen baseline
enabling rollback, and the loop having turned over **≥1× on genuine (non-fixture) data** — the North Star's
central DONE clause.

## Wave 7 — Phase 5a: map.json v2 schema + resolved-graph lockfile
**Deliverables:** `map.json` v2 with machine-readable typed edges (compose/import/augment) keyed by a stable
ref, closed-enum status (PyPI Development-Status ladder), tier + semver; manifest ranges plus a SEPARATE
resolved-graph lockfile (Cargo.lock analogue); a JSON Schema + validator.
**done-when:** `python -m pytest -q` validates a good map.json v2 against the schema, the resolved-graph
lockfile pins the transitive closure, and an untyped/overloaded edge or an out-of-enum status fails validation.

## Wave 8 — Phase 5b: three drift gates + consumption path + supply-chain signing
**Deliverables:** three automated drift gates — schema-in-CI, regenerate + `git diff --exit-code`,
target-existence at ingest (every declared edge resolves to a real skill); put map.json v2 ON THE CONSUMPTION
PATH (the real consumer reads it so a wrong/empty edge breaks a build); couple signing/checksums to the
lockfile (supply-chain integrity).
**done-when:** `python -m pytest -q` shows a wrong/empty edge breaking a build loudly, all three drift gates
green on a consistent graph and red on a stale/forged one, and a tampered lockfile failing the checksum gate.

## Wave 9 — Phase 6a: control-plane ops (scaffold + gen_manifest)
**Deliverables:** `foundry.scaffold_skill` (creates a new skill on disk from a template — SKILL.md, manifest,
journal dir, per-skill North-Star stub — registers it in map.json v2, commits on a branch; idempotent, refuses
to overwrite) and `foundry.gen_manifest` (derives/updates a skill's runner manifest, validated against the
Wave-3 schema), both as manifest-registered `mutate` ops dispatched through job_runner (auto-journaled +
confirm-gated). No new server/DB/store.
**done-when:** `python -m pytest -q` shows each op running HEADLESSLY via job_runner (no GUI), scaffolding a
demo skill end-to-end into a runnable + journaled + map-registered skill, and the scaffold op refusing to
overwrite an existing skill dir.

## Wave 10 — Phase 6b: edit_north_star op + auto-load registration
**Deliverables:** `foundry.edit_north_star` — the ONLY sanctioned per-skill North-Star mutation path
(proposal-diff → explicit human confirm token → apply as a branch commit with the prior version retained); a
grep/drift gate catching any out-of-band North-Star write; the auto-load registration op set that makes every
foundry skill clickable inside Anchor, driven from map.json v2.
**done-when:** `python -m pytest -q` shows a North-Star edit round-tripping proposal → confirm → branch commit
with history preserved, the drift gate FAILING on a direct out-of-band North-Star write, and auto-load
registration making a scaffolded skill appear in Anchor's clickable set from map.json alone.

## Wave 11 — Phase 7a: Foundry GUI read surface (stateless client)
**Deliverables:** the Foundry GUI as a stateless client over Anchor's real job_runner/session/artifact (Wave-1
§1 contract): run/monitor skills, see changes, browse the library + knowledge graph. Launched from an Anchor
button. Every displayed value traces to an engine-written artifact; NO parallel run/progress store.
**done-when:** `python -m pytest -q` (driving the GUI's data layer) shows every rendered value resolving to a
real engine artifact, an integration test asserting a monitor view reads job_runner state (not a mirror), and
the anti-theater check failing if a parallel store is introduced.

## Wave 12 — Phase 7b: Foundry GUI write surface + full user-journey
**Deliverables:** the GUI's mutative actions wired to Phase-6/Phase-4 ops — create a skill
(→ `foundry.scaffold_skill`), edit a per-skill North Star (→ `foundry.edit_north_star`), run+review the sleep
loop (→ Wave-6 op); all foundry skills auto-loaded into Anchor as clickable; every GUI mutation is an op
invocation, never a GUI-side file write.
**done-when:** `python -m pytest -q` drives the full North-Star user-journey (create → run/monitor → edit North
Star → run+review a test-gated sleep improvement) end-to-end over REAL machinery, asserts each GUI mutation
lands as a journaled job_runner op, and passes the 2nd-surface honesty test (every verb already runs headless,
so a second surface needs zero engine-logic change).

## Wave 13 — Phase 8: safety before scale
**Deliverables:** arm the reaper to ≥FREEZE after re-checking the 2026-07-05 fail-deadly finding; a per-host
concurrent-skill-run budget enforced IN the generic runner before default-on fan-out; zombie-hunter kept a
native built-in (not forced into the skill-action manifest).
**done-when:** `python -m pytest -q` shows the reaper armed to FREEZE within its safety envelope (never
kill-on-uncertainty), the concurrency budget refusing an over-budget fan-out, and the fail-deadly path retired
or explicitly bounded by a test.

## Wave 14 — North-Star acceptance proof (end-to-end DONE)
**Deliverables:** an end-to-end acceptance test proving the whole North-Star DONE clause from the GUI on
genuine data — create a skill, run/monitor it + see changes, browse library + graph, edit its North Star, and
click "Run sleep session" → review → approve a test-gated improvement that has turned over ≥1× on genuine
data — plus every foundry skill auto-available/clickable in Anchor. No regressions across the full suite.
**done-when:** `python -m pytest -q` is fully green including the end-to-end acceptance test that exercises the
complete North-Star DONE journey over real machinery, and the invariant/drift gates from all prior waves stay
green.
