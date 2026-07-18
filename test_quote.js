const { spawnSync } = require('child_process');
const py = spawnSync('python', ['-c', 'import sys; sys.path.insert(0, "."); import anchor_gui'], { shell: true });
console.log("status:", py.status);
console.log("stdout:", py.stdout?.toString());
console.log("stderr:", py.stderr?.toString());
