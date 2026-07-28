const test = require('node:test');
const assert = require('node:assert');
const { ForensicsAnalyzer, ForensicsGUI } = require('../src/forensics.js');

test('Wave 5: Historical Forensics Analysis and UI', async (t) => {
    
    await t.test('Given Historical telemetry data exists in the encrypted database, when The forensic analysis thread runs its chunked retrospective query, then It identifies past resource-consuming swarms and displays them in the GUI without exceeding 5% CPU or 250MB RAM limits', async () => {
        
        // Mock daemon to provide historical telemetry data
        const mockDaemon = {
            getSuspicious: () => [
                { id: 1, name: 'node.exe', executablePath: 'C:\\Program Files\\nodejs\\node.exe', timestamp: '2026-07-15 10:15:00' },
                { id: 2, name: 'node.exe', executablePath: 'C:\\Program Files\\nodejs\\node.exe', timestamp: '2026-07-15 10:16:00' },
                { id: 3, name: 'node.exe', executablePath: 'C:\\Program Files\\nodejs\\node.exe', timestamp: '2026-07-15 10:17:00' },
                { id: 4, name: 'python.exe', executablePath: 'C:\\Python39\\python.exe', timestamp: '2026-07-15 10:20:00' }, // Only 1 instance, not a swarm
                { id: 5, name: 'node.exe', executablePath: 'C:\\Program Files\\nodejs\\node.exe', timestamp: '2026-07-15 12:45:00' }, // Different hour chunk
                { id: 6, name: 'node.exe', executablePath: 'C:\\Program Files\\nodejs\\node.exe', timestamp: '2026-07-15 12:46:00' }  // Swarm of 2
            ]
        };

        const analyzer = new ForensicsAnalyzer(mockDaemon);
        
        // Verify resource limits logic
        const withinLimits = analyzer.checkResourceLimits(4.5, 150); // 4.5% CPU, 150MB RAM
        assert.strictEqual(withinLimits, true, 'Should not exceed 5% CPU or 250MB RAM');

        const exceededCpu = analyzer.checkResourceLimits(6.0, 150);
        assert.strictEqual(exceededCpu, false, 'Should fail if CPU exceeds 5%');
        
        const exceededRam = analyzer.checkResourceLimits(4.0, 300);
        assert.strictEqual(exceededRam, false, 'Should fail if RAM exceeds 250MB');

        // When the forensic analysis thread runs its chunked retrospective query
        const pastZombies = analyzer.analyzeHistoricalData();

        // Then It identifies past resource-consuming swarms
        assert.strictEqual(pastZombies.length, 2, 'Should identify two distinct swarms based on 1-hour chunks');
        
        assert.strictEqual(pastZombies[0].name, 'node.exe');
        assert.strictEqual(pastZombies[0].processCount, 3);
        assert.strictEqual(pastZombies[0].chunkWindow, '2026-07-15 10');

        assert.strictEqual(pastZombies[1].name, 'node.exe');
        assert.strictEqual(pastZombies[1].processCount, 2);
        assert.strictEqual(pastZombies[1].chunkWindow, '2026-07-15 12');

        // And displays them in the GUI view
        const gui = new ForensicsGUI();
        gui.setZombies(pastZombies);
        const html = gui.render();

        assert.ok(html.includes('retrospective-analysis-view'), 'Should render the GUI container');
        assert.ok(html.includes('2026-07-15 10:00'), 'Should display the first chunk window');
        assert.ok(html.includes('2026-07-15 12:00'), 'Should display the second chunk window');
        assert.ok(html.includes('Processes: 3'), 'Should display correct process count for first swarm');
        assert.ok(html.includes('Processes: 2'), 'Should display correct process count for second swarm');
    });
});
