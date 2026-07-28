import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { scan } from '../bin/scanner.mjs';

describe('Scanner tests', () => {
  let tempDir;

  before(async () => {
    // Set up a mock skill workspace inside the OS temp directory
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-test-'));

    // Project 1: contains NORTH-STAR.md (and SKILL.md) -> NORTH-STAR.md priority wins
    const p1 = path.join(tempDir, 'project-1');
    await fs.mkdir(p1);
    await fs.writeFile(path.join(p1, 'NORTH-STAR.md'), 'North Star');
    await fs.writeFile(path.join(p1, 'SKILL.md'), 'Skill Description');

    // Project 2: contains INTENT.md (and SKILL.md) -> INTENT.md priority wins
    const p2 = path.join(tempDir, 'project-2');
    await fs.mkdir(p2);
    await fs.writeFile(path.join(p2, 'INTENT.md'), 'Intent');
    await fs.writeFile(path.join(p2, 'SKILL.md'), 'Skill Description');

    // Project 3: contains only SKILL.md -> SKILL.md priority wins
    const p3 = path.join(tempDir, 'project-3');
    await fs.mkdir(p3);
    await fs.writeFile(path.join(p3, 'SKILL.md'), 'Skill Description');

    // Project 4: nested inside subdirectories, should still be detected
    const p4 = path.join(tempDir, 'templates', 'skill-repo');
    await fs.mkdir(p4, { recursive: true });
    await fs.writeFile(path.join(p4, 'SKILL.md'), 'Template Skill');

    // Non-project folder: should be ignored because it lacks any North Star files
    const notProject = path.join(tempDir, 'not-a-project');
    await fs.mkdir(notProject);
    await fs.writeFile(path.join(notProject, 'README.md'), 'Readme file');

    // System directories starting with dot (e.g. .git): should be ignored entirely
    const gitFolder = path.join(tempDir, '.git');
    await fs.mkdir(gitFolder);
    await fs.writeFile(path.join(gitFolder, 'NORTH-STAR.md'), 'Git North Star');

    // Node dependency folder: should be ignored entirely
    const nodeModulesFolder = path.join(tempDir, 'node_modules');
    await fs.mkdir(nodeModulesFolder);
    await fs.writeFile(path.join(nodeModulesFolder, 'SKILL.md'), 'Fake Skill');
  });

  after(async () => {
    // Cleanup the temporary directory structure
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  test('successfully discovers active projects and selects correct North Star file based on priority', async () => {
    const results = await scan(tempDir);

    // Assert that we found exactly the 4 projects and ignored the others
    assert.strictEqual(results.length, 4);

    const p1 = results.find(p => p.path.endsWith('project-1'));
    assert.ok(p1);
    assert.strictEqual(p1.north_star_file, path.resolve(tempDir, 'project-1', 'NORTH-STAR.md'));

    const p2 = results.find(p => p.path.endsWith('project-2'));
    assert.ok(p2);
    assert.strictEqual(p2.north_star_file, path.resolve(tempDir, 'project-2', 'INTENT.md'));

    const p3 = results.find(p => p.path.endsWith('project-3'));
    assert.ok(p3);
    assert.strictEqual(p3.north_star_file, path.resolve(tempDir, 'project-3', 'SKILL.md'));

    const p4 = results.find(p => p.path.endsWith('skill-repo'));
    assert.ok(p4);
    assert.strictEqual(p4.north_star_file, path.resolve(tempDir, 'templates', 'skill-repo', 'SKILL.md'));

    // Assert that ignored directories were not detected
    const ignoredGit = results.find(p => p.path.includes('.git'));
    assert.strictEqual(ignoredGit, undefined);

    const ignoredNodeModules = results.find(p => p.path.includes('node_modules'));
    assert.strictEqual(ignoredNodeModules, undefined);

    const ignoredPlainFolder = results.find(p => p.path.endsWith('not-a-project'));
    assert.strictEqual(ignoredPlainFolder, undefined);
  });
});
