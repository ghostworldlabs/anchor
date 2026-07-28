import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { runCompression } from '../bin/compress.mjs';

describe('Context Compression Engine Unit Tests', () => {
  let tempDir;

  before(async () => {
    // Setup temporary directory structure for project fixtures
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-compress-test-'));
  });

  after(async () => {
    // Cleanup temporary directory structure
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  test('gracefully handles missing agent.md and agent_hist.md', async () => {
    const projDir = path.join(tempDir, 'empty-project');
    await fs.mkdir(projDir);

    const result = await runCompression(projDir);
    assert.strictEqual(result.agentCompressed, false);
    assert.strictEqual(result.historyAppended, false);
    assert.strictEqual(result.historySummarized, false);
  });

  test('successfully compresses agent.md and appends to agent_hist.md', async () => {
    const projDir = path.join(tempDir, 'project-1');
    await fs.mkdir(projDir);

    const agentPath = path.join(projDir, 'agent.md');
    const historyPath = path.join(projDir, 'agent_hist.md');

    // Create a mock bloated agent.md
    const lines = [];
    for (let i = 1; i <= 60; i++) {
      lines.push(`Line ${i}: Project task detail to be summarized.`);
    }
    await fs.writeFile(agentPath, lines.join('\n'));

    // Create initial agent_hist.md
    await fs.writeFile(historyPath, 'Initial history line 1\nInitial history line 2');

    const mockAgent = async (prompt, opts) => {
      if (opts.label === 'compress-agent') {
        return {
          executiveSummary: 'This is the new executive summary.\nUnder 50 lines.',
          historyToAppend: 'Archived task details.'
        };
      }
      return {};
    };

    const result = await runCompression(projDir, { agent: mockAgent });

    assert.strictEqual(result.agentCompressed, true);
    assert.strictEqual(result.historyAppended, true);
    assert.strictEqual(result.historySummarized, false);

    const agentContent = await fs.readFile(agentPath, 'utf8');
    assert.strictEqual(agentContent, 'This is the new executive summary.\nUnder 50 lines.');

    const historyContent = await fs.readFile(historyPath, 'utf8');
    assert.strictEqual(historyContent, 'Initial history line 1\nInitial history line 2\nArchived task details.');
  });

  test('enforces hard safety constraint of keeping agent.md under 50 lines', async () => {
    const projDir = path.join(tempDir, 'project-2');
    await fs.mkdir(projDir);

    const agentPath = path.join(projDir, 'agent.md');
    await fs.writeFile(agentPath, 'Bloated agent.md content');

    // Agent returns > 50 lines
    const mockAgent = async (prompt, opts) => {
      const longSummaryLines = [];
      for (let i = 1; i <= 60; i++) {
        longSummaryLines.push(`Summary Line ${i}`);
      }
      return {
        executiveSummary: longSummaryLines.join('\n'),
        historyToAppend: 'Some history'
      };
    };

    const result = await runCompression(projDir, { agent: mockAgent });
    assert.strictEqual(result.agentCompressed, true);
    assert.ok(result.newAgentLines < 50);

    const agentContent = await fs.readFile(agentPath, 'utf8');
    const lines = agentContent.split('\n');
    assert.strictEqual(lines.length, 49);
    assert.strictEqual(lines[0], 'Summary Line 1');
    assert.strictEqual(lines[48], 'Summary Line 49');
  });

  test('applies lossy summarization to agent_hist.md when it exceeds 500 lines', async () => {
    const projDir = path.join(tempDir, 'project-3');
    await fs.mkdir(projDir);

    const agentPath = path.join(projDir, 'agent.md');
    const historyPath = path.join(projDir, 'agent_hist.md');

    await fs.writeFile(agentPath, 'Bloated agent.md content');

    // Create a history file that already has 495 lines
    const initialHist = [];
    for (let i = 1; i <= 495; i++) {
      initialHist.push(`History entry ${i}`);
    }
    await fs.writeFile(historyPath, initialHist.join('\n'));

    // The agent will output 10 lines of history to append, pushing it to 505 lines (exceeding 500 lines)
    const mockAgent = async (prompt, opts) => {
      if (opts.label === 'compress-agent') {
        const histToAppend = [];
        for (let i = 1; i <= 10; i++) {
          histToAppend.push(`New history to append ${i}`);
        }
        return {
          executiveSummary: 'Short summary',
          historyToAppend: histToAppend.join('\n')
        };
      }
      if (opts.label === 'summarize-history') {
        return {
          summarizedHistory: 'Summarized history: milestone reached.'
        };
      }
      return {};
    };

    const result = await runCompression(projDir, { agent: mockAgent });
    assert.strictEqual(result.agentCompressed, true);
    assert.strictEqual(result.historyAppended, true);
    assert.strictEqual(result.historySummarized, true);

    const historyContent = await fs.readFile(historyPath, 'utf8');
    assert.strictEqual(historyContent, 'Summarized history: milestone reached.');
  });

  test('enforces hard safety constraint of keeping agent_hist.md under 500 lines', async () => {
    const projDir = path.join(tempDir, 'project-4');
    await fs.mkdir(projDir);

    const historyPath = path.join(projDir, 'agent_hist.md');

    // Create a history file that already has 550 lines
    const initialHist = [];
    for (let i = 1; i <= 550; i++) {
      initialHist.push(`History entry ${i}`);
    }
    await fs.writeFile(historyPath, initialHist.join('\n'));

    // Mock agent returns > 500 lines for summarization
    const mockAgent = async (prompt, opts) => {
      if (opts.label === 'summarize-history') {
        const longHist = [];
        for (let i = 1; i <= 600; i++) {
          longHist.push(`Summary History Line ${i}`);
        }
        return {
          summarizedHistory: longHist.join('\n')
        };
      }
      return {};
    };

    const result = await runCompression(projDir, { agent: mockAgent });
    assert.strictEqual(result.historySummarized, true);
    assert.ok(result.newHistoryLines < 500);

    const historyContent = await fs.readFile(historyPath, 'utf8');
    const lines = historyContent.split('\n');
    assert.strictEqual(lines.length, 499);
    assert.strictEqual(lines[0], 'Summary History Line 1');
    assert.strictEqual(lines[498], 'Summary History Line 499');
  });

  test('falls back safely if the agent call throws or returns invalid schema', async () => {
    const projDir = path.join(tempDir, 'project-5');
    await fs.mkdir(projDir);

    const agentPath = path.join(projDir, 'agent.md');
    await fs.writeFile(agentPath, 'Original Agent Content');

    const mockBadAgent = async (prompt, opts) => {
      throw new Error('LLM connection error');
    };

    const result = await runCompression(projDir, { agent: mockBadAgent });
    assert.strictEqual(result.agentCompressed, true); // It writes the fallback content
    assert.strictEqual(result.historyAppended, false);
    assert.strictEqual(result.historySummarized, false);

    const agentContent = await fs.readFile(agentPath, 'utf8');
    assert.strictEqual(agentContent, 'Original Agent Content');
  });
});
