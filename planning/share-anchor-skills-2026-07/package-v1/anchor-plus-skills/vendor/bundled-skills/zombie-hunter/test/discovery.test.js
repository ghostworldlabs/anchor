const test = require('node:test');
const assert = require('node:assert');
const cp = require('child_process');
const { ProcessDiscovery } = require('../src/discovery.js');

test('Process Discovery', async (t) => {
    const discovery = new ProcessDiscovery();

    await t.test('detects suspicious AI process and ignores Microsoft process', () => {
        const originalExecSync = cp.execSync;
        
        cp.execSync = (cmd) => {
            if (cmd.includes('ConvertTo-Csv')) {
                // Mock two processes: one AI process (trio), one Microsoft process (svchost)
                return `"ProcessId","Name","ExecutablePath","CommandLine"\n"1234","node.exe","C:\\Program Files\\nodejs\\node.exe","node.exe <path>"\n"5678","svchost.exe","C:\\Windows\\System32\\svchost.exe","svchost.exe -k netsvcs"`;
            }
            if (cmd.includes('Get-AuthenticodeSignature')) {
                if (cmd.includes('svchost.exe')) {
                    return 'O=Microsoft Corporation';
                }
                return 'O=SomeOtherCompany';
            }
            return '';
        };

        try {
            const suspicious = discovery.discover();
            assert.strictEqual(suspicious.length, 1, 'Should only flag one suspicious process');
            assert.strictEqual(suspicious[0].processId, '1234');
            assert.strictEqual(suspicious[0].name, 'node.exe');
            assert.ok(suspicious[0].commandLine.includes('trio'));
        } finally {
            cp.execSync = originalExecSync;
        }
    });

    await t.test('heuristic matching', () => {
        assert.strictEqual(discovery.isSuspicious('node run agy', 'node.exe'), true);
        assert.strictEqual(discovery.isSuspicious('python.exe claude_script.py', 'python.exe'), true);
        assert.strictEqual(discovery.isSuspicious('', 'ollama.exe'), true);
        assert.strictEqual(discovery.isSuspicious('chrome.exe', 'chrome.exe'), false);
    });

    await t.test('cryptographic allowlist check', () => {
        const originalExecSync = cp.execSync;
        cp.execSync = (cmd) => {
            if (cmd.includes('signed.exe')) return 'CN=Microsoft Windows, O=Microsoft Corporation, L=Redmond, S=Washington, C=US';
            if (cmd.includes('unsigned.exe')) return 'CN=Some Unsigned Entity';
            return '';
        };

        try {
            assert.strictEqual(discovery.checkMicrosoftSignature('signed.exe'), true, 'Should allowlist Microsoft signed binary');
            assert.strictEqual(discovery.checkMicrosoftSignature('unsigned.exe'), false, 'Should not allowlist unsigned or non-Microsoft binary');
        } finally {
            cp.execSync = originalExecSync;
        }
    });
});
