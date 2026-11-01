'use strict';
// Offer the owned VM's RDP on host loopback so relay 3.0 can forward it.
const fs = require('node:fs');
const net = require('node:net');
const cp = require('node:child_process');
const {promisify} = require('node:util');
const exec = promisify(cp.execFile);
const plan = JSON.parse(fs.readFileSync('/opt/opendeploy/plan.json', 'utf8'));
if (plan.relay_version !== '3.0') throw Error('Only relay 3.0 is allowed');
const id = String(plan.vm.vmid);
async function target() {
  const c = await exec('qm', ['config', id], {timeout: 10000});
  const lines = Object.fromEntries(c.stdout.split('\n').filter(x => x.includes(': ')).map(x => [x.slice(0, x.indexOf(': ')), x.slice(x.indexOf(': ') + 2)]));
  if (lines.description !== 'OpenDeploy-' + plan.id || !lines.smbios1?.includes('uuid=' + plan.vm.uuid)) throw Error('VM ownership mismatch');
  const r = await exec('qm', ['guest', 'cmd', id, 'network-get-interfaces'], {timeout: 15000});
  const report = JSON.parse(r.stdout);
  const interfaces = Array.isArray(report) ? report : report.result;
  const ips = interfaces.flatMap(x => x['ip-addresses'] || []).filter(x => x['ip-address-type'] === 'ipv4').map(x => x['ip-address']);
  const ip = ips.find(x => net.isIPv4(x) && !x.startsWith('127.') && !x.startsWith('169.254.'));
  if (!ip) throw Error('Guest network unavailable');
  return ip;
}
const server = net.createServer(async client => {
  client.on('error', () => {});
  client.pause();
  try {
    const host = await target();
    if (client.destroyed) return;
    const remote = net.connect({host, port: 3389});
    remote.setTimeout(15000, () => remote.destroy());
    remote.on('connect', () => { remote.setTimeout(0); client.pipe(remote).pipe(client); client.resume(); });
    remote.on('error', () => client.destroy());
    remote.on('close', () => client.destroy());
    client.on('close', () => remote.destroy());
  } catch { client.destroy(); }
});
server.on('error', error => { console.error(error.message); process.exit(1); });
server.listen(13389, '127.0.0.1');
for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => server.close(() => process.exit(0)));
