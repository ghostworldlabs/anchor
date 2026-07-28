// W10 / P7 — SKILL.md ↔ server reason-code field map CI contract.
// Named gate: test_skill_server_reason_code_contract (HALT-worthy on drift).

const { test } = require('node:test');
const assert = require('node:assert');

const {
  FIELD_MAP_START,
  FIELD_MAP_END,
  buildCanonicalFieldMap,
  extractFieldMapFromSkillMarkdown,
  loadSkillFieldMap,
  assertSkillServerReasonCodeContract,
  testSkillServerReasonCodeContract,
  setDiff,
  DEFAULT_SKILL_MD,
} = require('../src/skill-contract.js');

const {
  CLASSIFIER_REASON_CODES,
  REASON_CATALOG_VERSION,
  getCatalogsPublicPayload,
} = require('../src/reason-catalog.js');

test('test_skill_server_reason_code_contract', () => {
  const r = testSkillServerReasonCodeContract();
  assert.strictEqual(r.ok, true, `HALT-worthy drift: ${(r.failures || []).join(' | ')}`);
  assert.strictEqual(r.haltWorthy, false);
  assert.ok(r.skill);
  assert.ok(r.canonical);
  assert.strictEqual(r.canonical.reasonCatalogVersion, REASON_CATALOG_VERSION);
  assert.strictEqual(
    r.skill.reasonCodes.length,
    CLASSIFIER_REASON_CODES.length,
  );
  assert.deepStrictEqual(
    [...r.skill.reasonCodes].sort(),
    [...CLASSIFIER_REASON_CODES].sort(),
  );

  // Server public payload stays locked to the same closed set
  const pub = getCatalogsPublicPayload();
  assert.strictEqual(pub.reasonCatalogVersion, REASON_CATALOG_VERSION);
  assert.strictEqual(pub.reasonCodes.length, CLASSIFIER_REASON_CODES.length);
});

test('skill field map load + extract from real SKILL.md', () => {
  const loaded = loadSkillFieldMap(DEFAULT_SKILL_MD);
  assert.strictEqual(loaded.ok, true, loaded.reason);
  assert.ok(loaded.map.reasonCodes.includes('OWNERSHIP_IPC_FAIL_CLOSED'));
  assert.ok(loaded.map.ownershipBadgeFields.includes('owned'));
  assert.ok(loaded.map.serverCatalogFields.includes('reasonCodes'));
  assert.ok(loaded.map.doctorIssueIds.includes('ZH_HEALTH_CHECK_ISSUES'));
});

test('Given SKILL map and server catalog diverge — contract fails closed', () => {
  const canonical = buildCanonicalFieldMap();
  const drifted = {
    ...canonical,
    reasonCodes: canonical.reasonCodes.filter((c) => c !== 'SHADOW_OBSERVE_ONLY'),
  };
  const r = assertSkillServerReasonCodeContract({ skillMap: drifted });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.haltWorthy, true);
  assert.ok(r.failures.some((f) => /only_in_server|SHADOW_OBSERVE_ONLY/i.test(f)));

  const invented = {
    ...canonical,
    reasonCodes: [...canonical.reasonCodes, 'TOTALLY_INVENTED_CODE'],
  };
  const r2 = assertSkillServerReasonCodeContract({ skillMap: invented });
  assert.strictEqual(r2.ok, false);
  assert.strictEqual(r2.haltWorthy, true);
  assert.ok(r2.failures.some((f) => /only_in_SKILL|TOTALLY_INVENTED/i.test(f)));
});

test('extractFieldMapFromSkillMarkdown requires markers', () => {
  const missing = extractFieldMapFromSkillMarkdown('# no map here');
  assert.strictEqual(missing.ok, false);
  assert.ok(String(missing.reason).includes('missing'));

  const ok = extractFieldMapFromSkillMarkdown(
    `${FIELD_MAP_START}\n\`\`\`json\n${JSON.stringify(buildCanonicalFieldMap())}\n\`\`\`\n${FIELD_MAP_END}`,
  );
  assert.strictEqual(ok.ok, true);
  assert.strictEqual(ok.map.contractVersion, 'w10-skill-server-v1');
});

test('setDiff order-independent', () => {
  const d = setDiff(['a', 'b'], ['b', 'a']);
  assert.strictEqual(d.equal, true);
  const d2 = setDiff(['a'], ['a', 'b']);
  assert.strictEqual(d2.equal, false);
  assert.deepStrictEqual(d2.onlyB, ['b']);
});
