// No server, shell subprocess, credentials or external requests.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const sandbox={URL,window:{location:{href:'https://anchor.example/steward/v1'},STEWARD_TOKEN:'synthetic-test-token'}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(new URL('../steward_cockpit/static/md.js',import.meta.url),'utf8'),sandbox);
const f=sandbox.mdReportHref;
assert.equal(f('http://['),'http://[');
for(const input of ['/artifact/p?path=a%20b.pdf','http://127.0.0.1:8777/artifact/p?path=a%20b.pdf','https://anchor.example/artifact/p?path=a%20b.pdf']){
 const u=new URL(f(input),'https://anchor.example');
 assert.equal(u.origin,'https://anchor.example');assert.equal(u.searchParams.get('path'),'a b.pdf');
 assert.equal(u.searchParams.get('token'),'synthetic-test-token');
}
assert.equal(new URL(f('/artifact/p?path=a%26b%23c.pdf&token=stale#page=2'),'https://anchor.example').hash,'#page=2');
for(const url of ['https://paper.example/paper.pdf','https://external.example/artifact/p?path=x','http://127.0.0.1.evil.example:8777/artifact/p?path=x','http://127.0.0.1:8888/artifact/p?path=x','http://user@127.0.0.1:8777/artifact/p?path=x'])assert.equal(f(url),url);
sandbox.window.STEWARD_TOKEN='';
assert.equal(f('/artifact/p?path=x&token=stale'),'/artifact/p?path=x');
console.log('Report href normalization and credential-boundary cases passed.');
