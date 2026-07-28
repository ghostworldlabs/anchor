// test/launch-briefing.test.mjs — Wave 7: the investigator briefing + launch spec.
//
// Two properties this suite pins, because they ARE the wave's done-when:
//
//   • THE CLEAN-MACHINE FAILURE (FM15) IS DESIGNED OUT. A launch on a profile
//     WITHOUT the dev environment's skill paths must still produce a readable
//     briefing that inlines the tidy-idy instructions — the session starts in the
//     project cwd, not on an unresolvable-skill dead end. This is the required CI
//     regression test.
//
//   • THE ENGINE IS A COMMAND-TEMPLATE FIELD, NOT A SECOND CODE PATH. The same
//     builder produces the Claude spec and the Gemini spec; only the engine and
//     its argv differ, and a third engine is config.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  renderBriefingMarkdown, writeBriefing, resolveTidyIdySkill, readSkillInstructions,
  skillSearchPaths, BRIEFING_FILENAME, SKILL_MD_SOURCE,
} from '../engine/launch/briefing.mjs';
import {
  buildInvestigatorLaunchSpec, resolveEngine, engineChoices, terminalCommand,
  ENGINE_TEMPLATES, DEFAULT_ENGINE,
} from '../engine/launch/investigator.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { envelopeWithEveryClass, cleanEnvelope, identityFor, RUN_ID } from './helpers/panel-fixture.mjs';

let root;
before(async () => { root = await makeTempRoot('tidy-idy-w7-briefing-'); });
after(async () => { await rmTempRoot(root); });

/** A resolver that models a CLEAN profile: the skill is not on this machine's path. */
const CLEAN_PROFILE = async () => ({ resolvable: false, path: null, searched: ['/nonexistent/.claude/skills/tidy-idy/SKILL.md'] });
/** A resolver that models a DEV profile: the skill is resolvable. */
const DEV_PROFILE = async () => ({ resolvable: true, path: '<path>', searched: [] });

describe('the briefing markdown', () => {
  const envelope = envelopeWithEveryClass(root);
  const identity = identityFor(root);

  test('is engine-agnostic and carries the project root, run summary, and findings with ABSOLUTE paths', () => {
    const md = renderBriefingMarkdown({ envelope, identity, runNumber: 7, skill: { resolvable: true } });
    assert.match(md, /investigation briefing/);
    assert.ok(md.includes(identity.path), 'the absolute project root is named');
    assert.ok(md.includes('/tmp/x/old/prototype.mjs'), 'a finding carries its absolute path');
    assert.match(md, /Suggested first questions/);
    // Verbatim judge evidence appears.
    assert.match(md, /superseded spike with no importers/i);
  });

  test('never leaks a secret — masked trigger text and rule name only', () => {
    const md = renderBriefingMarkdown({ envelope, identity, runNumber: 7, skill: { resolvable: true } });
    assert.match(md, /BLOCKED/);
    assert.ok(md.includes('AKIA****************'), 'the finding’s own masked text is what appears');
    assert.match(md, /aws-access-key-id/);
  });

  test('references the skill when resolvable and INLINES it when not', async () => {
    const withSkill = renderBriefingMarkdown({ envelope, identity, runNumber: 7, skill: { resolvable: true, path: '/x/SKILL.md' } });
    assert.match(withSkill, /skill is resolvable in this environment/);
    assert.ok(!withSkill.includes('<details>'), 'a resolvable skill is not inlined');

    const instructions = await readSkillInstructions();
    assert.ok(instructions && instructions.includes('Repository hygiene'), 'the shipping SKILL.md is the inline source');
    const inlined = renderBriefingMarkdown({ envelope, identity, runNumber: 7, skill: { resolvable: false }, skillInstructions: instructions });
    assert.match(inlined, /not resolvable/);
    assert.ok(inlined.includes('<details>'), 'an unresolvable skill is inlined under a details block');
    assert.ok(inlined.includes('Repository hygiene'), 'the actual instructions are inlined');
  });
});

describe('skill resolution', () => {
  test('resolves when a candidate path is a real file, and does not when none is', async () => {
    const present = await resolveTidyIdySkill({ searchPaths: [SKILL_MD_SOURCE] });
    assert.strictEqual(present.resolvable, true);
    assert.strictEqual(present.path, SKILL_MD_SOURCE);

    const absent = await resolveTidyIdySkill({ searchPaths: ['/no/such/tidy-idy/SKILL.md'] });
    assert.strictEqual(absent.resolvable, false);
    assert.strictEqual(absent.path, null);
  });

  test('search paths derive from the environment, not the cwd', () => {
    const paths = skillSearchPaths({ env: { HOME: '<path>' } });
    assert.ok(paths.some((p) => p.includes(path.join('.claude', 'skills', 'tidy-idy'))));
  });
});

describe('the investigator launch spec — the clean-profile CI regression (FM15)', () => {
  test('on a profile WITHOUT the dev skill paths, the session starts in the project cwd with a readable, INLINED briefing', async () => {
    const runDir = path.join(root, 'run-clean');
    await fs.mkdir(runDir, { recursive: true });

    const spec = await buildInvestigatorLaunchSpec({
      rootPath: root,
      runDir,
      envelope: envelopeWithEveryClass(root),
      identity: identityFor(root),
      runNumber: 7,
      skillResolver: CLEAN_PROFILE,
    });

    // cwd = project root — not a dev box path, not the tool's own dir.
    assert.strictEqual(spec.cwd, path.resolve(root));
    assert.strictEqual(spec.skill.resolvable, false);
    assert.strictEqual(spec.skill.inlined, true);

    // The briefing the agent opens is readable and self-contained.
    const briefing = await fs.readFile(spec.briefingPath, 'utf8');
    assert.ok(briefing.length > 0);
    assert.match(briefing, /not resolvable/);
    assert.ok(briefing.includes('Repository hygiene'), 'the tidy-idy instructions are inlined into the briefing');
    assert.ok(spec.briefingPath.endsWith(BRIEFING_FILENAME));
  });

  test('on a dev profile the briefing points at the skill rather than inlining it', async () => {
    const runDir = path.join(root, 'run-dev');
    await fs.mkdir(runDir, { recursive: true });
    const spec = await buildInvestigatorLaunchSpec({
      rootPath: root, runDir, envelope: cleanEnvelope(root), identity: identityFor(root), runNumber: 8, skillResolver: DEV_PROFILE,
    });
    assert.strictEqual(spec.skill.resolvable, true);
    assert.strictEqual(spec.skill.inlined, false);
    const briefing = await fs.readFile(spec.briefingPath, 'utf8');
    assert.match(briefing, /skill is resolvable in this environment/);
  });
});

describe('the engine toggle — one code path, config for a third engine', () => {
  const base = () => ({
    rootPath: root,
    runDir: root,
    envelope: cleanEnvelope(root, { runId: RUN_ID }),
    identity: identityFor(root),
    runNumber: 5,
    skillResolver: DEV_PROFILE,
  });

  test('defaults to Claude', async () => {
    const spec = await buildInvestigatorLaunchSpec(base());
    assert.strictEqual(spec.engine, DEFAULT_ENGINE);
    assert.strictEqual(spec.engine, 'claude');
    assert.strictEqual(spec.command[0], 'claude');
    // The briefing PATH is the opening prompt's subject.
    assert.ok(spec.openingPrompt.includes(spec.briefingPath));
    assert.strictEqual(spec.command[spec.command.length - 1], spec.openingPrompt);
  });

  test('the Gemini toggle launches from the Gemini template for the SAME project and run — no second code path', async () => {
    const claude = await buildInvestigatorLaunchSpec({ ...base(), engine: 'claude' });
    const gemini = await buildInvestigatorLaunchSpec({ ...base(), engine: 'gemini' });
    assert.strictEqual(gemini.engine, 'gemini');
    assert.strictEqual(gemini.command[0], 'gemini');
    // Same project, same report — only the engine differs.
    assert.strictEqual(gemini.project.path, claude.project.path);
    assert.strictEqual(gemini.runId, claude.runId);
    assert.strictEqual(gemini.runNumber, claude.runNumber);
    assert.strictEqual(gemini.kind, claude.kind);
    assert.strictEqual(gemini.cwd, claude.cwd);
  });

  test('engines are config: claude|gemini|grok recognised; unknown falls back honestly', async () => {
    const viaConfig = resolveEngine({ config: { investigator: { engine: 'gemini' } } });
    assert.strictEqual(viaConfig.resolved, 'gemini');
    const viaGrok = resolveEngine({ engine: 'grok' });
    assert.strictEqual(viaGrok.resolved, 'grok');
    assert.strictEqual(viaGrok.recognised, true);
    assert.ok(ENGINE_TEMPLATES.grok.argv.includes('grok'));
    const unknown = resolveEngine({ engine: 'gpt-9' });
    assert.strictEqual(unknown.resolved, DEFAULT_ENGINE);
    assert.strictEqual(unknown.recognised, false, 'the fallback is reported, never a silent lie');
    assert.strictEqual(unknown.requested, 'gpt-9');
  });

  test('engineChoices agrees with the executable templates (no id/label drift)', () => {
    const choices = engineChoices({ defaultEngine: 'claude' });
    assert.deepStrictEqual(choices.map((c) => c.id).sort(), Object.keys(ENGINE_TEMPLATES).sort());
    for (const c of choices) assert.strictEqual(c.label, ENGINE_TEMPLATES[c.id].label);
    assert.ok(choices.find((c) => c.id === 'claude').default);
  });

  test('the terminal wrapper opens a new console on win32 and runs the CLI directly elsewhere', () => {
    const spec = { command: ['claude', 'prompt'], cwd: root, engine: 'claude' };
    const win = terminalCommand(spec, 'win32');
    assert.strictEqual(win.command, 'cmd');
    assert.deepStrictEqual(win.args.slice(0, 3), ['/c', 'start', 'tidy-idy investigator']);
    const nix = terminalCommand(spec, 'linux');
    assert.strictEqual(nix.command, 'claude');
    assert.deepStrictEqual(nix.args, ['prompt']);
  });
});

describe('writeBriefing', () => {
  test('writes the briefing into the run dir and reports whether it inlined the skill', async () => {
    const runDir = path.join(root, 'run-write');
    await fs.mkdir(runDir, { recursive: true });
    const res = await writeBriefing({
      runDir, envelope: cleanEnvelope(root), identity: identityFor(root), runNumber: 3, skill: { resolvable: false },
    });
    assert.strictEqual(res.inlined, true);
    assert.ok(res.path.endsWith(BRIEFING_FILENAME));
    const text = await fs.readFile(res.path, 'utf8');
    assert.match(text, /investigation briefing/);
  });
});
