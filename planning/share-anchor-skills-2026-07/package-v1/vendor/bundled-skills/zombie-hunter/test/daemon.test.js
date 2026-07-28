const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { TelemetryDaemon } = require('../src/daemon.js');

test('Wave 2: Local Telemetry Daemon and Encrypted SQLite', async (t) => {
    const testDbPath = path.join(__dirname, 'test_telemetry.db');
    if (fs.existsSync(testDbPath)) {
        fs.unlinkSync(testDbPath);
    }

    const daemon = new TelemetryDaemon(testDbPath, 'test_key');

    t.after(() => {
        daemon.close();
        if (fs.existsSync(testDbPath)) {
            fs.unlinkSync(testDbPath);
        }
    });

    await t.test('Given The daemon is active and a Node process exhibits suspicious network activity, when The discovery module reports the process to the daemon, then The daemon logs it to the encrypted SQLite database as a "suspicious tier" entry without bloating standard telemetry', () => {
        
        // Given
        const mockProcessData = {
            processId: '9999',
            name: 'node.exe',
            executablePath: 'C:\\Program Files\\nodejs\\node.exe',
            commandLine: 'node.exe suspicious_miner.js --network-active'
        };

        // When
        daemon.logSuspicious(mockProcessData);

        // Then - verify it's stored and decrypted properly
        const suspiciousRecords = daemon.getSuspicious();
        assert.strictEqual(suspiciousRecords.length, 1, 'Should log one suspicious entry');
        
        const record = suspiciousRecords[0];
        assert.strictEqual(record.processId, '9999');
        assert.strictEqual(record.name, 'node.exe');
        assert.strictEqual(record.executablePath, 'C:\\Program Files\\nodejs\\node.exe');
        assert.strictEqual(record.commandLine, 'node.exe suspicious_miner.js --network-active');
        assert.ok(record.timestamp, 'Timestamp should be recorded');
        
        // Verify it is encrypted at rest
        const rawDb = new (require('node:sqlite').DatabaseSync)(testDbPath);
        const rawStmt = rawDb.prepare(`SELECT * FROM suspicious_processes WHERE id = ?`);
        const rawRow = rawStmt.get(record.id);
        rawDb.close();
        
        assert.notStrictEqual(rawRow.processId, '9999', 'processId should be encrypted at rest');
        assert.notStrictEqual(rawRow.name, 'node.exe', 'name should be encrypted at rest');
        assert.ok(rawRow.processId.includes(':'), 'Encrypted format should include IV and AuthTag');
    });

    await t.test('Sanitization and retention policies', () => {
        // Insert a record normally
        daemon.logSuspicious({
            processId: '1111',
            name: 'test.exe',
            executablePath: 'C:\\test.exe',
            commandLine: 'test.exe'
        });

        // Manually update the timestamp to 10 days ago to test retention
        const rawDb = new (require('node:sqlite').DatabaseSync)(testDbPath);
        rawDb.exec(`UPDATE suspicious_processes SET timestamp = datetime('now', '-10 days') WHERE processId != '9999'`);
        rawDb.close();

        // Run cleanup
        daemon.cleanOldRecords(7);

        const remaining = daemon.getSuspicious();
        assert.strictEqual(remaining.length, 1, 'Older records should be deleted, recent ones kept');
        assert.strictEqual(remaining[0].processId, '9999', 'Only the recent record should remain');
    });
});
