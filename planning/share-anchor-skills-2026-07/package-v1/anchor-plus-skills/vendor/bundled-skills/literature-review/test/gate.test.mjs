import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { runMixedInitiativeGate, constructCopilotPrompt } from '../src/gate.mjs';

describe('Wave 5: Mixed-Initiative Gates & On-Demand Copilot', () => {
  const mockCandidates = [
    { paperId: 'p1', title: 'Paper One', venue: 'NeurIPS', year: 2020, citationCount: 42 },
    { paperId: 'p2', title: 'Paper Two', venue: 'ICML', year: 2021, citationCount: 15 }
  ];
  const mockChunks = [
    'This is the first paragraph of the main paper text.',
    'This is the second paragraph describing throughput of 150 rps.'
  ];

  test('constructCopilotPrompt constructs prompt correctly', () => {
    const query = 'What is the throughput?';
    const prompt = constructCopilotPrompt(mockChunks, query);
    
    assert.ok(prompt.includes('You are the On-Demand Copilot'));
    assert.ok(prompt.includes(mockChunks[0]));
    assert.ok(prompt.includes(mockChunks[1]));
    assert.ok(prompt.includes(query));
  });

  test('resumes successfully when mock user sequence is approve', async () => {
    const logs = [];
    const result = await runMixedInitiativeGate(mockCandidates, mockChunks, {
      mockUser: 'approve',
      log: (msg) => logs.push(msg)
    });

    assert.equal(result.approved, true);
    assert.equal(result.queries.length, 0);
    assert.ok(logs.some(l => l.includes('Resuming execution')));
  });

  test('aborts with error when mock user sequence is reject', async () => {
    const logs = [];
    await assert.rejects(
      async () => {
        await runMixedInitiativeGate(mockCandidates, mockChunks, {
          mockUser: 'reject',
          log: (msg) => logs.push(msg)
        });
      },
      /Execution rejected by user/
    );
  });

  test('handles queries and then approves in mock user sequence', async () => {
    const logs = [];
    const agentCalls = [];
    
    const mockAgent = async (prompt, opts) => {
      agentCalls.push({ prompt, opts });
      return `Mocked answer for query: "${opts.query}"`;
    };

    const result = await runMixedInitiativeGate(mockCandidates, mockChunks, {
      mockUser: 'query: what is the throughput? | query: are there conflicts? | approve',
      agent: mockAgent,
      log: (msg) => logs.push(msg)
    });

    assert.equal(result.approved, true);
    assert.equal(result.queries.length, 2);
    
    assert.equal(result.queries[0].query, 'what is the throughput?');
    assert.equal(result.queries[0].response, 'Mocked answer for query: "what is the throughput?"');
    
    assert.equal(result.queries[1].query, 'are there conflicts?');
    assert.equal(result.queries[1].response, 'Mocked answer for query: "are there conflicts?"');

    assert.equal(agentCalls.length, 2);
    assert.equal(agentCalls[0].opts.label, 'copilot:query');
    assert.equal(agentCalls[0].opts.query, 'what is the throughput?');
  });

  test('handles shorthand q: prefix in mock user sequence', async () => {
    const logs = [];
    const agentCalls = [];
    
    const mockAgent = async (prompt, opts) => {
      agentCalls.push({ prompt, opts });
      return `Answer`;
    };

    const result = await runMixedInitiativeGate(mockCandidates, mockChunks, {
      mockUser: 'q: what is the latency? | approve',
      agent: mockAgent,
      log: (msg) => logs.push(msg)
    });

    assert.equal(result.approved, true);
    assert.equal(result.queries.length, 1);
    assert.equal(result.queries[0].query, 'what is the latency?');
  });
});
