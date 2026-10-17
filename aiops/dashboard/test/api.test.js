'use strict';

// Offline suite for the Contract-E routes. No database, no bridge process: the
// app is built with an injected readResource, exactly the seam src/server.js uses
// with the real bridge.
const assert = require('node:assert/strict');
const test = require('node:test');

const { MAX_SINCE_S, createApp, parseSince } = require('../src/app');
const { RESOURCES } = require('../src/resources');

const ROWS = [
  { ts: 1767050101.25, module: 'detect', service: 'orders', kind: 'anomaly_flag',
    value: 1, meta: { detector: 'iforest', threshold: 0.8 } },
  { ts: 1767050086.5, module: 'detect', service: 'carts', kind: 'anomaly_score',
    value: 0.42, meta: null },
];

async function withServer(readResource, fn) {
  const server = createApp({ readResource }).listen(0, '127.0.0.1');
  await new Promise((resolve) => server.once('listening', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    return await fn(base);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

// The failure paths deliberately log a line; capture it so the run stays quiet and
// the sanitization of the log line itself can be asserted.
async function captureErrors(fn) {
  const lines = [];
  const original = console.error;
  console.error = (...args) => { lines.push(args.join(' ')); };
  try {
    return { result: await fn(), lines };
  } finally {
    console.error = original;
  }
}

function bridgeError(kind, message) {
  const err = new Error(message || 'boom');
  err.name = 'BridgeError';
  err.kind = kind;
  return err;
}

test('the six Contract-E routes are registered and return JSON arrays', async () => {
  assert.deepEqual(RESOURCES, ['anomalies', 'rca', 'predictions', 'forecasts',
    'remediations', 'experiments']);
  const seen = [];
  await withServer(async (resource, since) => {
    seen.push([resource, since]);
    return ROWS;
  }, async (base) => {
    for (const resource of RESOURCES) {
      const response = await fetch(`${base}/api/${resource}`);
      assert.equal(response.status, 200, `/api/${resource} status`);
      assert.match(response.headers.get('content-type'), /application\/json/);
      const body = await response.json();
      assert.ok(Array.isArray(body), `/api/${resource} must be a JSON array`);
      assert.deepEqual(body, ROWS, `/api/${resource} passes the read rows through`);
    }
  });
  assert.deepEqual(seen.map(([resource]) => resource), [...RESOURCES],
    'each route reads exactly its own resource');
  assert.deepEqual(seen.map(([, since]) => since), RESOURCES.map(() => 0),
    'since defaults to 0 (no lower bound)');
});

test('an empty database result is an empty JSON array, never a placeholder', async () => {
  await withServer(async () => [], async (base) => {
    for (const resource of RESOURCES) {
      const response = await fetch(`${base}/api/${resource}`);
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), [], `/api/${resource} must answer []`);
    }
  });
});

test('JSON serialization handles the returned data types unchanged', async () => {
  // The shapes the bridge can return: BIGINT ids, float epochs, NaN-as-null values,
  // nested JSONB, booleans, empty objects, unicode: all must round-trip exactly.
  const rows = [
    { run_id: 9007199254740991, ts: 1767050101.125, service: 'front-end',
      value: null, meta: { horizon_s: 120, nested: { list: [1, 'two', null, 3.5] } } },
    { run_id: 7, ts: 0, service: 'carts-db', value: 0, meta: {}, note: 'naïve' },
    { run: {}, result: null },
  ];
  await withServer(async () => rows, async (base) => {
    for (const resource of RESOURCES) {
      const response = await fetch(`${base}/api/${resource}`);
      const text = await response.text();
      assert.deepEqual(JSON.parse(text), rows, 'values are not coerced or dropped');
      assert.match(text, /"ts":1767050101\.125/, 'floats stay numbers');
      assert.match(text, /9007199254740991/, 'large integers stay exact');
      assert.match(text, /"value":null/, 'null is preserved (not omitted)');
    }
  });
});

test('?since= is validated, bounded, and forwarded as a value', async () => {
  const seen = [];
  await withServer(async (resource, since) => {
    seen.push(since);
    return [];
  }, async (base) => {
    assert.equal((await fetch(`${base}/api/rca?since=1767050000`)).status, 200);
    assert.equal((await fetch(`${base}/api/rca?since=0`)).status, 200);
    assert.equal((await fetch(`${base}/api/rca?since=12.5`)).status, 200);
    assert.equal((await fetch(`${base}/api/rca?since=${MAX_SINCE_S}`)).status, 200);
    assert.equal((await fetch(`${base}/api/rca?since=${MAX_SINCE_S + 1}`)).status, 400);
    for (const bad of ['abc', '-1', '1e3', ' 12', '12%20', '1.2.3', `${MAX_SINCE_S + 1}`, ''])
      assert.equal((await fetch(`${base}/api/rca?since=${bad}`)).status, 400, `since=${bad}`);
    // A repeated parameter arrives as an array: refused, not silently picked apart.
    assert.equal((await fetch(`${base}/api/rca?since=1&since=2`)).status, 400);
  });
  assert.deepEqual(seen, [1767050000, 0, 12.5, MAX_SINCE_S], 'valid values reach the reader');
});

test('parseSince accepts only bounded non-negative numbers', () => {
  assert.equal(parseSince(undefined), 0);
  assert.equal(parseSince('0'), 0);
  assert.equal(parseSince('1767050101'), 1767050101);
  assert.equal(parseSince('12.5'), 12.5);
  assert.equal(parseSince(String(MAX_SINCE_S)), MAX_SINCE_S);
  for (const bad of ['a', '', '-1', '-0.5', '+1', '1e3', '0x10', 'NaN', 'Infinity',
    '.5', '5.', String(MAX_SINCE_S + 1), null, 42, ['1']]) {
    assert.throws(() => parseSince(bad), RangeError, `parseSince(${JSON.stringify(bad)})`);
  }
});

test('unknown paths and every write method answer 404 with a JSON body', async () => {
  await withServer(async () => ROWS, async (base) => {
    for (const path of ['/api', '/api/unknown', '/api/anomalies/1', '/', '/healthz']) {
      const response = await fetch(`${base}${path}`);
      assert.equal(response.status, 404, path);
      assert.deepEqual(await response.json(), { error: 'not_found' });
    }
    // No write route exists, on any of the six resources.
    for (const resource of RESOURCES) {
      for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
        const response = await fetch(`${base}/api/${resource}`, { method });
        assert.equal(response.status, 404, `${method} /api/${resource} must not be routed`);
      }
    }
  });
});

test('a database read failure is a sanitized 503', async () => {
  const secret = 'postgresql://aiops:aiops@timescaledb.aiops:5432/aiops';
  const { result, lines } = await captureErrors(() => withServer(async () => {
    throw bridgeError('read_failed', `could not connect to ${secret} while running SELECT 1`);
  }, async (base) => {
    const response = await fetch(`${base}/api/predictions`);
    return { status: response.status, text: await response.text() };
  }));
  assert.equal(result.status, 503);
  assert.deepEqual(JSON.parse(result.text), { error: 'read_failed' });
  for (const leak of ['aiops:aiops', 'postgresql', 'timescaledb', 'SELECT', 'could not connect',
    'at ', 'stack', 'Error']) {
    assert.ok(!result.text.includes(leak), `response must not contain ${JSON.stringify(leak)}`);
  }
  assert.deepEqual(lines, ['dashboard: /api/predictions read failed (read_failed)'],
    'the log line carries a fixed message and the failure class only');
});

test('a failure with no classified kind is still a sanitized 503', async () => {
  const { result, lines } = await captureErrors(() => withServer(async () => {
    throw new Error('mysql: connection refused at /etc/shadow');
  }, async (base) => {
    const response = await fetch(`${base}/api/experiments`);
    return { status: response.status, text: await response.text() };
  }));
  assert.equal(result.status, 503);
  assert.deepEqual(JSON.parse(result.text), { error: 'read_failed' });
  assert.ok(!result.text.includes('mysql') && !result.text.includes('/etc/shadow'));
  assert.deepEqual(lines, ['dashboard: /api/experiments read failed (unknown)']);
});

test('the bridge invalid_request code maps to 400, not 503', async () => {
  const { result } = await captureErrors(() => withServer(async () => {
    throw bridgeError('invalid_request');
  }, async (base) => {
    const response = await fetch(`${base}/api/remediations`);
    return { status: response.status, text: await response.text() };
  }));
  assert.equal(result.status, 400);
  assert.deepEqual(JSON.parse(result.text), { error: 'invalid_request' });
});

test('an adapter that returns a non-array is a sanitized 503', async () => {
  const { result } = await captureErrors(() => withServer(async () => ({ rows: ROWS }),
    async (base) => {
      const response = await fetch(`${base}/api/anomalies`);
      return { status: response.status, text: await response.text() };
    }));
  assert.equal(result.status, 503);
  assert.deepEqual(JSON.parse(result.text), { error: 'read_failed' });
});

test('the app advertises no stack and needs a reader function', async () => {
  await withServer(async () => [], async (base) => {
    const response = await fetch(`${base}/api/anomalies`);
    assert.equal(response.headers.get('x-powered-by'), null,
      'x-powered-by must be disabled');
  });
  assert.throws(() => createApp({}), TypeError);
  assert.throws(() => createApp({ readResource: 'nope' }), TypeError);
});
