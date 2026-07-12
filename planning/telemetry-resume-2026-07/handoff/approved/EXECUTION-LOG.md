# Anchor — Honest Telemetry + Warm Resume — Execution Log

Foreman records per-wave build outcomes below. 7 wave(s) planned.

## Waves

### Wave 1 — W1 Ground Truth — artifacts (cited by path; Foreman appends its GREEN/HALT verdict below)

All Wave-1 deliverables exist in the repo at these paths:

- **Pinned sidecar fixtures** (real observed shape, anonymized):
  `tests/fixtures/sidecar/canonical_3turn.jsonl`, `resumed_segment.jsonl`,
  `corrupted_zero_usage.jsonl`, `corrupted_malformed.jsonl`, `EXPECTED.json`,
  `README.md`. Load-bearing finding: **dedup by `message.id`** (87% of real sidecars
  carry verbatim-duplicated usage records; naive summing double-counts).
- **Sidecar spike findings + narration-floor cost arithmetic + orientation plan-mode
  verification**: `planning/telemetry-resume-2026-07/W1-GROUND-TRUTH.md`
  (§1 sidecar shape · §2 `permission_mode='plan'` ENFORCEABLE — primary fork branch holds ·
  §3 arithmetic: 33/33 real managed sessions summary-less, managed enrichment coverage 0%).
- **Wave-0 closed-world audit** (v4 rollup + v8 persist, additive-compatible vs superseded):
  `planning/telemetry-resume-2026-07/W1-CLOSED-WORLD-AUDIT.md`. `ANCHOR_SIDECAR_DIR` is
  unset in every test → new cost source OFF; only 2 shape-assertions flagged SUPERSEDED
  (`test_cli_v4::test_cli_rollup_shape_and_delegates`, `test_effort_rollup::test_zero_when_no_run_metrics`).
- **Registry-state fixture capture tool**: `tools/capture_registry_fixture.py`
  (anonymized; scrubs `crypt_token`/host paths/free text). **Captured fixture set**:
  `tests/fixtures/registry_state/sessions.json`, `efforts/proj-0000_build.json`,
  `MANIFEST.json`, `README.md` — includes the two MANDATORY classes: ≥1 **evicted-parked**
  session (`sess-0003`) + ≥1 **finished one-shot job** (`run-1783775099001`).
- **Playwright B2 reproduction suite** (reproduce + classify; no fixes): `tests/test_b2_repro_w1.py`
  — all three symptoms reproduced and classified as SEPARATE plan items: S1 (state-bug),
  S2 (state-bug), S3 (state-bug facet + attach-race facet needing the WS attach-ack change).
  Root-cause source: `planning/telemetry-resume-2026-07/intake/gap-closures-b2.md`.
- **North Star doc amendment** (single citation target; ALL locked contracts verbatim;
  Gemini-segment stub **status=RULED, letter=C**):
  `planning/telemetry-resume-2026-07/NORTH-STAR-AMENDMENT.md`.

_(Foreman appends a GREEN/HALT entry per wave below.)_

## Stage-1/2 gate — APPROVED (John, 2026-07-11)
- Master Plan APPROVED (Stage-1 gate). Implementation Plan APPROVED for build ("run foreman", Stage-2 gate).
- Tier: STANDARD (Opus 4.8 on Claude seats — John: "not heavy, let opus 4.8 do the claude work"); Gemini on review seats (5:1).
- Gemini-segment scope: RULED Option C (badge now + dated fast-follow spike, recorded here at deploy).
- Fix applied pre-handoff: test-command changed pytest -q to pytest -v (Foreman anti-forgery gate requires per-test events); well-formedness gate re-run PASS.
- Honest caveats carried from planning: Stage-2 shark rounds 2-5 were false-dry (>32KB prompt argv defect); Stage-2 judge ran same-model persona. Foreman's own per-wave adversarial Gemini reviewers are the compensating rigor.

## W1 amendment (2026-07-11) — non-skipping B2 repros (John: "rework repros to not skip")
- Launch #4 wave-1 EXECUTE completed OK ($11.74) and the full-suite GATE ran to completion (956s), but HALTed on Foreman's §5 test-integrity guard: the B2 repro tests were authored skip-gated (pytest.importorskip("playwright") + pytest.skip("inconclusive")), raising skip/xfail markers 126->138 with 7 actually skipped. The guard hard-refuses any skip rise absent a plan citation.
- Resolution (John-approved): W1's B2-repro deliverable + G/W/T + done-when amended to mandate NON-SKIPPING pure-Python repros that are GREEN in the standard gate (S1 blank-window = unit test of the stale-live-cache + silent-unknown-session-close decision logic; S2/S3 = rendered-HTML/source inspection). Any genuinely browser-only assertion is DEFERRED to W6 (fix + Playwright sign-off). No skip/xfail on the gate path.
- Prior infra fixes retained: Opus standard tier (execute/fix=claude-opus-4-8, review=gemini-3.1-pro), FOREMAN_GATE_TIMEOUT_MS=1500000, --call-timeout-min 90, detached Start-Process launch, gitignored logs.
