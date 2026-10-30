'use strict';

// Offline suite for the process-boundary adapter. A fake spawn stands in for
// child_process.spawn, so no Python interpreter and no database are needed — the
// tests assert the wire contract (argv, no shell, JSON on stdin/stdout) and the
// sanitization of every failure mode.
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

const { REPO_ROOT, createBridgeReader } = require('../src/bridge');

function fakeSpawn(behaviour = {}) {
  const calls = [];
  const spawnImpl = (command, args, options) => {
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.stderr.resume = () => { child.stderrDrained = true; };
    child.stdin = new EventEmitter();
    child.stdin.end = (data) => { child.stdinData = data; };
    child.kill = () => { child.killed = true; };
    calls.push({ command, args, options, child });
    setImmediate(() => {
      if (behaviour.onSpawn) { behaviour.onSpawn(child); return; }
      if (behaviour.stdout) child.stdout.emit('data', Buffer.from(behaviour.stdout));
      if (behaviour.stderr) child.stderr.emit('data', Buffer.from(behaviour.stderr));
      if (!behaviour.neverCloses) child.emit('close', behaviour.code ?? 0);
    });
    return child;
  };
  spawnImpl.calls = calls;
  return spawnImpl;
}

test('one request maps to one bridge process, JSON on stdin, no shell', async () => {
  const spawnImpl = fakeSpawn({ stdout: '{"ok": true, "rows": [{"ts": 1}]}' });
  const readResource = createBridgeReader({ spawnImpl });
  const rows = await readResource('anomalies', 1767050000.5);
  assert.deepEqual(rows, [{ ts: 1 }]);
  assert.equal(spawnImpl.calls.length, 1, 'exactly one process per read');
  const [call] = spawnImpl.calls;
  assert.equal(call.command, 'python', 'repo convention: python -m aiops.<module>');
  assert.deepEqual(call.args, ['-m', 'aiops.dashboard.bridge'], 'argv, never a shell string');
  assert.equal(call.options.shell, false, 'no shell is involved');
  assert.equal(call.options.cwd, REPO_ROOT, 'run from the repo root so `aiops` imports');
  assert.equal(call.child.stdinData, '{"resource":"anomalies","since":1767050000.5}',
    'the request travels as JSON');
  assert.equal(call.child.stderrDrained, true, 'child diagnostics are drained and dropped');
});

test('the bridge answer is required to be a well-formed ok/rows object', async () => {
  const cases = [
    ['{"ok": true, "rows": []}', 0, 'empty rows are a valid answer'],
    ['{"ok": true, "rows": [{"a": 1}]}', 0, 'rows pass through'],
  ];
  for (const [stdout, code, label] of cases) {
    const reader = createBridgeReader({ spawnImpl: fakeSpawn({ stdout, code }) });
    assert.deepEqual(await reader('rca', 0), JSON.parse(stdout).rows, label);
  }
  const failing = [
    ['not json at all', 0, 'bad_response'],
    ['', 0, 'bad_response'],
    ['{"ok": true, "rows": {}}', 0, 'bad_response'],
    ['{"ok": true, "rows": []}', 1, 'bad_response'],
    ['{"ok": false}', 1, 'read_failed'],
    ['{"ok": false, "error": "surprise"}', 1, 'read_failed'],
  ];
  for (const [stdout, code, kind] of failing) {
    const reader = createBridgeReader({ spawnImpl: fakeSpawn({ stdout, code }) });
    await assert.rejects(reader('rca', 0), (err) => err.kind === kind,
      `stdout=${JSON.stringify(stdout)} code=${code} should be ${kind}`);
  }
});

test('bridge failure codes map to sanitized kinds, never to database text', async () => {
  const secret = 'postgresql://aiops:aiops@timescaledb:5432/aiops';
  const stdout = '{"ok": false, "error": "read_failed"}';
  const reader = createBridgeReader({
    spawnImpl: fakeSpawn({ stdout, code: 1, stderr: `Traceback: could not connect to ${secret}` }),
  });
  await assert.rejects(reader('experiments', 0), (err) => {
    assert.equal(err.kind, 'read_failed');
    assert.equal(err.message, 'dashboard read bridge failed (read_failed)');
    assert.ok(!err.message.includes(secret) && !err.message.includes('Traceback'),
      'no database text is relayed');
    return true;
  });
  const invalid = createBridgeReader({
    spawnImpl: fakeSpawn({ stdout: '{"ok": false, "error": "invalid_request"}', code: 1 }),
  });
  await assert.rejects(invalid('rca', 0), (err) => err.kind === 'invalid_request');
});

test('a hung bridge is killed and reported as a timeout', async () => {
  const spawnImpl = fakeSpawn({ neverCloses: true });
  const reader = createBridgeReader({ spawnImpl, timeoutMs: 20 });
  await assert.rejects(reader('forecasts', 0), (err) => err.kind === 'timeout');
  assert.equal(spawnImpl.calls[0].child.killed, true, 'the child is killed, not leaked');
});

test('spawn failures are sanitized, whether thrown or emitted', async () => {
  const throwing = () => { throw new Error('spawn python ENOENT at C:\\secrets'); };
  await assert.rejects(createBridgeReader({ spawnImpl: throwing })('rca', 0),
    (err) => err.kind === 'spawn_failed' && !err.message.includes('secrets'));

  const spawnImpl = fakeSpawn({ onSpawn: (child) => child.emit('error', new Error('ENOENT')) });
  await assert.rejects(createBridgeReader({ spawnImpl })('rca', 0),
    (err) => err.kind === 'spawn_failed');
});

test('only the six Contract-E resources can be read', async () => {
  const spawnImpl = fakeSpawn({ stdout: '{"ok": true, "rows": []}' });
  const reader = createBridgeReader({ spawnImpl });
  for (const resource of ['alerts', 'txns', '', 'ANOMALIES', 'anomalies;drop', '../rca']) {
    await assert.rejects(reader(resource, 0), (err) => err.kind === 'unknown_resource', resource);
  }
  assert.equal(spawnImpl.calls.length, 0, 'nothing is spawned for an unknown resource');
});
