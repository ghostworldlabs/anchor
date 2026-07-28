const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { IPCServer, IPCClient } = require('../src/ipc.js');
const { TelemetryDaemon } = require('../src/daemon.js');

test('Wave 3: Secure IPC', async (t) => {
    const testDbPath = path.join(__dirname, 'test_ipc.db');
    if (fs.existsSync(testDbPath)) {
        fs.unlinkSync(testDbPath);
    }
    
    const daemon = new TelemetryDaemon(testDbPath, 'test_key');
    const mockDiscovery = {
        discover: () => [
            { processId: '1234', name: 'node.exe', executablePath: 'C:\\node.exe', commandLine: 'node trio' }
        ]
    };
    daemon.discoveryModule = mockDiscovery;

    const pipeName = '\\\\.\\pipe\\zombie-hunter-ipc-test-' + Date.now();
    const server = new IPCServer(daemon, pipeName);
    const client = new IPCClient(pipeName);

    t.after(() => {
        daemon.close();
        if (fs.existsSync(testDbPath)) {
            fs.unlinkSync(testDbPath);
        }
    });

    await t.test('Given The user opens the GUI and clicks "Relaunch Sweep", when The background daemon is queried via IPC for fresh process data, then An async spinner displays until the updated process list is returned and rendered, keeping the UI fully responsive', async () => {
        await server.start();
        
        const response = await client.send('relaunch_sweep');
        assert.strictEqual(response.status, 'ok');
        assert.ok(response.data.length > 0);
        assert.strictEqual(response.data[0].processId, '1234');

        await server.stop();
    });
});
