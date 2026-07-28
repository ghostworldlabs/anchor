const test = require('node:test');
const assert = require('node:assert');
const { getContextExplanation, BulkApprovalGUI } = require('../src/bulk-approvals.js');

test('Wave 4: Bulk Swarm Approvals and Context Display', async (t) => {
    
    await t.test('human-readable violation explanation template generator', () => {
        const swarm = {
            id: 'swarm-1',
            name: 'Test Swarm',
            violatedRule: 'Strict AI Signature',
            processes: [{ id: 1 }, { id: 2 }]
        };
        const explanation = getContextExplanation(swarm);
        assert.strictEqual(explanation, 'Violation: Strict AI Signature. This swarm contains 2 rogue processes that have been flagged for neutralization.');
    });

    await t.test('Given A detected rogue AI swarm is displayed in the GUI, when The user clicks the "Show Context" toggle and then the "Kill" button on the parent row, then The inline accordion explains the explicit heuristic rule violated, and the Soft Freeze/Kill command is dispatched for the entire unified swarm', async () => {
        let dispatchedCommand = null;
        const mockIpcClient = {
            send: async (command, data) => {
                dispatchedCommand = { command, data };
                return { status: 'ok' };
            }
        };

        const gui = new BulkApprovalGUI(mockIpcClient);
        gui.setSwarms([
            { id: '1', name: 'Rogue Node', violatedRule: 'AGY detected', processes: [{ id: 101 }, { id: 102 }] },
            { id: '2', name: 'Rogue Python', violatedRule: 'Python Trio', processes: [{ id: 201 }] }
        ]);

        let html = gui.render();
        // Check Tree View elements
        assert.ok(html.includes('collapsible-tree-view'));
        assert.ok(html.includes('class="kill-button"'));
        assert.ok(html.includes('class="show-context-toggle"'));
        assert.ok(!html.includes('inline-accordion context-explanation'), 'Accordions should be closed initially');

        // When The user clicks the "Show Context" toggle
        gui.toggleContext('1');
        html = gui.render();
        
        // Then The inline accordion explains the explicit heuristic rule violated
        assert.ok(html.includes('inline-accordion context-explanation'), 'Accordion should be open');
        assert.ok(html.includes('Violation: AGY detected'), 'Explanation should be shown');

        // When user clicks Show Context on another, it auto-closes the first one
        gui.toggleContext('2');
        html = gui.render();
        assert.ok(!html.includes('Violation: AGY detected'), 'Swarm 1 accordion should be closed');
        assert.ok(html.includes('Violation: Python Trio'), 'Swarm 2 accordion should be open');

        // And when the "Kill" button on the parent row is clicked
        await gui.dispatchKill('1');

        // Then the Soft Freeze/Kill command is dispatched for the entire unified swarm
        assert.strictEqual(dispatchedCommand.command, 'kill_swarm');
        assert.deepStrictEqual(dispatchedCommand.data, { swarmId: '1' });
    });
});
