// Wave 1 (F0) — the shared TOOL-LANE gate helper.
//
// THE BUILD-GATE ISOLATION CONTRACT (DESCRIPTION-INC2 §v2.1/§v2.2): the FAST unit tier — the Foreman
// `node --test test/` gate — must run GREEN with NO live ollama and must never hang. All
// tool-touching tests (ollama/lean/z3 + their canary re-runs) are env-gated into a SEPARATE SERIAL
// lane, switched on by the CANONICAL env var RAMANUJAN_TOOL_TESTS=1 (pinned identically here and in
// tools.manifest.json — no per-test divergence). The persistent ollama server + warm-up live ONLY in
// that lane.
//
// Usage:
//   import { TOOL_LANE, toolLaneSkip } from './tool-lane.mjs';
//   describe('F0 tool lane', { skip: toolLaneSkip() }, () => { before(start); after(stop); ... });
//
// When skipped, node:test does NOT run the suite's before/after hooks, so no server is started and
// the fast gate cannot hang on a tool.

/** THE canonical tool-lane gate env var (matches tools.manifest.json `tool_lane_env`). */
export const TOOL_LANE_ENV = 'RAMANUJAN_TOOL_TESTS';

/** True iff the serial tool lane is enabled (RAMANUJAN_TOOL_TESTS=1). */
export const TOOL_LANE = process.env[TOOL_LANE_ENV] === '1';

/** A node:test `skip` value: false when the lane is on; an explanatory string when off. */
export function toolLaneSkip() {
  return TOOL_LANE ? false : `tool lane disabled (set ${TOOL_LANE_ENV}=1 to run the serial lane against the real tools)`;
}
