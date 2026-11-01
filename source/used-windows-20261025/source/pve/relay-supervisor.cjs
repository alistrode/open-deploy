'use strict';
// Run the pinned 3.0 far implementation. systemd restarts this supervisor on failure.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const state = process.env.RELAY_STATE_DIR;
if (!state) throw Error('Private relay state directory required');
const ready = path.join(state, 'opendeploy-ready.json');
function clear() { try { fs.unlinkSync(ready); } catch (e) { if (e.code !== 'ENOENT') throw e; } }
clear();
const child = cp.fork(path.join(__dirname, 'relay/SSH-Remote-Linux/src/start.cjs'), [], {
  stdio: ['ignore', 'inherit', 'inherit', 'ipc'],
  env: { ...process.env, RELAY_NO_PRINT: '1' }
});
child.on('message', message => {
  if (message.type === 'ready') {
    const tmp = ready + '.new';
    fs.writeFileSync(tmp, JSON.stringify({ protocol: message.protocol, fingerprint: message.fingerprint, at: Date.now() }), {mode: 0o600});
    fs.renameSync(tmp, ready);
  } else if (message.type === 'offline') clear();
});
child.on('error', () => { clear(); process.exit(1); });
child.on('exit', () => { clear(); process.exit(1); });
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
