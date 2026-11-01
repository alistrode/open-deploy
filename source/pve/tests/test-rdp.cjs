'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const net = require('node:net');
const {EventEmitter} = require('node:events');
const source = fs.readFileSync(require('node:path').join(__dirname, '../rdp-proxy.cjs'), 'utf8');
async function scenario(foreign, missing) {
  let accept;
  const connected = [];
  const client = new EventEmitter();
  client.destroyed = false;
  client.pause = () => {};
  client.resume = () => {};
  client.destroy = () => { client.destroyed = true; };
  client.pipe = remote => remote;
  const modules = {
    'node:fs': {readFileSync: () => JSON.stringify({relay_version:'3.0',id:'job-1',vm:{vmid:110,uuid:'uuid-1'}})},
    'node:util': {promisify: fn => fn},
    'node:child_process': {execFile: async (_, args) => args[0] === 'config'
      ? {stdout:'description: OpenDeploy-' + (foreign ? 'other' : 'job-1') + '\nsmbios1: uuid=uuid-1\n'}
      : {stdout:JSON.stringify([{'ip-addresses':missing ? [] : [{'ip-address-type':'ipv4','ip-address':'192.168.1.50'}]}])}},
    'node:net': {
      isIPv4:net.isIPv4,
      createServer: fn => {accept=fn;return {on(){return this;},listen(){},close(){}};},
      connect: options => {
        connected.push(options);
        const remote = new EventEmitter();
        remote.setTimeout = () => {};
        remote.pipe = () => client;
        queueMicrotask(() => remote.emit('connect'));
        return remote;
      }
    }
  };
  vm.runInNewContext(source, {require: name => modules[name], process:{on(){}}, console});
  await accept(client);
  return {connected,client};
}
test('owned VM RDP is routed to discovered guest address', async () => {
  const r=await scenario(false,false);
  assert.equal(r.connected.length,1);assert.equal(r.connected[0].host,'192.168.1.50');assert.equal(r.connected[0].port,3389);
});
test('foreign VM cannot receive a forwarded connection', async () => {
  const r=await scenario(true,false);assert.equal(r.connected.length,0);assert.equal(r.client.destroyed,true);
});
test('guest without an address fails without stale address fallback', async () => {
  const r=await scenario(false,true);assert.equal(r.connected.length,0);assert.equal(r.client.destroyed,true);
});
