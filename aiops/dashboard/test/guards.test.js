'use strict';

// Contract-E source and manifest guards, asserted on the files themselves. These
// are the checks that keep the "no parallel database client" and "read-only,
// localhost-only" properties true as the dashboard grows.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { HOST, DEFAULT_PORT, parsePort } = require('../src/config');
const { RESOURCES } = require('../src/resources');

const DASHBOARD_DIR = path.resolve(__dirname, '..');
const SRC_DIR = path.join(DASHBOARD_DIR, 'src');

// Comments are documentation, not behaviour: strip line comments before scanning
// so a comment may name a thing the code must not use (e.g. the DSN variable).
function code(text) {
  return text
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n');
}

const SOURCES = fs.readdirSync(SRC_DIR)
  .filter((name) => name.endsWith('.js'))
  .map((name) => ({
    name,
    text: fs.readFileSync(path.join(SRC_DIR, name), 'utf8'),
  }))
  .map((source) => ({ ...source, code: code(source.text) }));

const MANIFEST = JSON.parse(fs.readFileSync(path.join(DASHBOARD_DIR, 'package.json'), 'utf8'));

test('the manifest depends on Express only — no PostgreSQL driver in Node', () => {
  assert.deepEqual(Object.keys(MANIFEST.dependencies), ['express']);
  assert.equal(MANIFEST.devDependencies, undefined, 'the Node tests use node:test');
  const manifestText = JSON.stringify(MANIFEST);
  for (const forbidden of ['"pg"', 'postgres', 'pg-pool']) {
    assert.ok(!manifestText.includes(forbidden), `manifest must not carry ${forbidden}`);
  }
  assert.match(MANIFEST.scripts.test, /^node --test/, 'the offline suite is `npm test`');
  assert.match(MANIFEST.scripts.start, /node src\/server\.js/);
});

test('no SQL lives in the JavaScript layer', () => {
  // The only SQL in the dashboard is in the Python bridge, next to store.recent().
  // If a query ever appears here, the dashboard has grown a second database client.
  const sqlWords = /\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|JOIN|WHERE|VALUES)\b/;
  for (const { name, code: source } of SOURCES) {
    assert.ok(!sqlWords.test(source), `${name} must not contain SQL`);
  }
});

test('the Node process never handles the DSN', () => {
  for (const { name, code: source } of SOURCES) {
    for (const forbidden of ['TIMESCALE_DSN', 'postgresql://', 'postgres://', 'password',
      'connectionString']) {
      assert.ok(!source.includes(forbidden), `${name} must not mention ${forbidden} in code`);
    }
  }
});

test('no write-capable route is registered', () => {
  const writeRegistrations = /\.(post|put|patch|delete|all)\s*\(/;
  for (const { name, code: source } of SOURCES) {
    assert.ok(!writeRegistrations.test(source), `${name} must register no write route`);
  }
  const app = SOURCES.find(({ name }) => name === 'app.js');
  assert.ok(app, 'app.js exists');
  const getRoutes = app.code.match(/app\.get\(/g) || [];
  assert.equal(getRoutes.length, 1, 'the six routes come from one registration loop');
  assert.ok(app.code.includes('for (const resource of RESOURCES)'),
    'the loop iterates the frozen Contract-E list');
});

test('the resource list is exactly the six Contract-E endpoints, frozen', () => {
  assert.deepEqual(RESOURCES, ['anomalies', 'rca', 'predictions', 'forecasts',
    'remediations', 'experiments']);
  assert.ok(Object.isFrozen(RESOURCES));
});

test('the listener host is a loopback constant with no override path', () => {
  assert.equal(HOST, '127.0.0.1');
  for (const wildcard of ['0.0.0.0', '::', 'localhost']) {
    assert.notEqual(HOST, wildcard, `HOST must not be ${wildcard}`);
  }
  const config = SOURCES.find(({ name }) => name === 'config.js');
  assert.ok(config.text.includes("const HOST = '127.0.0.1'"),
    'HOST is a literal, not an environment read');
  assert.ok(!/process\.env\.HOST/.test(config.text), 'no host environment override');
});

test('the port is a bounded, validated dashboard-local setting', () => {
  assert.equal(DEFAULT_PORT, 8081, '8080 belongs to the in-cluster NodePort path');
  assert.equal(parsePort(undefined), 8081);
  assert.equal(parsePort(''), 8081);
  assert.equal(parsePort('9000'), 9000);
  for (const bad of ['0', '65536', 'abc', '80 80', '-1', '1e3', '80;rm', null]) {
    assert.throws(() => parsePort(bad), RangeError, `parsePort(${JSON.stringify(bad)})`);
  }
});
