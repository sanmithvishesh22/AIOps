'use strict';

// Contract E requires localhost-only access in v1. These tests pin the bind
// behaviour: the configured listener answers on loopback and is NOT reachable on a
// non-loopback interface of this machine, and no option can widen the bind.
//
// Honest limit: this proves the application's own listener. It cannot prove
// anything about a reverse proxy, SSH tunnel, port-forward, or a cluster NodePort
// in front of it — those are separate surfaces (see README.md).
const assert = require('node:assert/strict');
const os = require('node:os');
const test = require('node:test');

const { HOST } = require('../src/config');
const { startServer } = require('../src/server');

function nonLoopbackIPv4() {
  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const address of addresses || []) {
      if (address.family === 'IPv4' && !address.internal) return address.address;
    }
  }
  return null;
}

test('the configured listener binds the loopback interface', async () => {
  const server = await startServer({ port: 0, readResource: async () => [] });
  try {
    assert.equal(server.address().address, '127.0.0.1');
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/anomalies`);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), []);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('a host option cannot widen the listener off loopback', async () => {
  // startServer deliberately accepts no host: an attempt to pass one is ignored.
  const server = await startServer({
    port: 0,
    host: '0.0.0.0',
    readResource: async () => [],
  });
  try {
    assert.equal(server.address().address, '127.0.0.1',
      'the frozen loopback host wins over any option');
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('requests through a non-loopback interface are not served', async (t) => {
  const ip = nonLoopbackIPv4();
  if (!ip) {
    t.skip('this machine has no non-loopback IPv4 interface to probe');
    return;
  }
  const server = await startServer({ port: 0, readResource: async () => [] });
  const port = server.address().port;
  try {
    // The listener is up and answering on loopback...
    assert.equal((await fetch(`http://127.0.0.1:${port}/api/rca`)).status, 200);
    // ...and refuses the same port on the machine's non-loopback address.
    await assert.rejects(
      fetch(`http://${ip}:${port}/api/rca`, { signal: AbortSignal.timeout(3000) }),
      (err) => {
        const cause = err.cause ? `${err.cause.code || err.cause.message}` : err.message;
        return !/200|404/.test(cause);
      },
      `http://${ip}:${port} must not be served by a loopback-only listener`,
    );
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test('HOST is loopback by construction', () => {
  assert.ok(['127.0.0.1', '::1'].includes(HOST), `HOST=${HOST} must be loopback`);
  assert.notEqual(HOST, '0.0.0.0');
  assert.notEqual(HOST, '::');
});
