'use strict';

// The isolated database adapter (ticket D4-002 §5). The dashboard never opens a
// PostgreSQL connection and never holds a query string: this module spawns the
// Python read bridge, which reuses aiops.common.store.recent() for inference rows,
// reads the relational tables with parameterized explicit-column queries, and takes
// the DSN from aiops/common/config.py (Contract G single source).
//
// One HTTP request -> one short-lived process. The request travels as JSON on
// stdin, so no query text, DSN, or parameter is ever interpolated into a command
// line (no shell is involved at all). The child's diagnostics are drained and
// discarded; failures surface as sanitized codes, never as text from the database.
//
// Trade-off, stated honestly: a process per request costs ~100-300 ms and buys
// isolation plus zero duplicated data-access code. At this dashboard's local,
// single-user scale that is the right trade; if it ever becomes a hot path,
// revisit with a pooled client — which is a design change, not a silent one.
const { spawn } = require('node:child_process');
const path = require('node:path');

const { RESOURCES } = require('./resources');

const PYTHON = 'python'; // repo convention: `python -m aiops.<module>` from the repo root
const BRIDGE_MODULE = 'aiops.dashboard.bridge';
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..'); // src -> dashboard -> aiops -> root
const READ_TIMEOUT_MS = 15000;

class BridgeError extends Error {
  // `kind` is the only failure detail that travels with the error:
  // 'read_failed' | 'invalid_request' | 'timeout' | 'spawn_failed' | 'bad_response'
  // | 'unknown_resource'. Messages are fixed strings, never database text.
  constructor(kind) {
    super(`dashboard read bridge failed (${kind})`);
    this.name = 'BridgeError';
    this.kind = kind;
  }
}

function parseResponse(code, text) {
  let body = null;
  try {
    body = JSON.parse(text.trim());
  } catch (err) {
    body = null;
  }
  if (body !== null && typeof body === 'object') {
    if (body.ok === true && code === 0 && Array.isArray(body.rows)) {
      return { rows: body.rows };
    }
    if (body.ok === false && body.error === 'invalid_request') {
      return { error: new BridgeError('invalid_request') };
    }
    if (body.ok === false) return { error: new BridgeError('read_failed') };
  }
  return { error: new BridgeError('bad_response') };
}

function runBridge(spawnImpl, timeoutMs, request) {
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawnImpl(PYTHON, ['-m', BRIDGE_MODULE], {
        cwd: REPO_ROOT,
        env: process.env, // the child reads TIMESCALE_DSN itself, per Contract G
        shell: false,     // nothing is interpolated into a command line, ever
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (err) {
      reject(new BridgeError('spawn_failed'));
      return;
    }

    const chunks = [];
    let settled = false;
    const settle = (error, rows) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve(rows);
    };
    const timer = setTimeout(() => {
      child.kill();
      settle(new BridgeError('timeout'));
    }, timeoutMs);

    child.stdout.on('data', (chunk) => chunks.push(chunk));
    child.stderr.resume(); // drained and discarded: nothing from the DB reaches our logs
    child.stdin.on('error', () => {}); // the child may exit before the write lands
    child.on('error', () => settle(new BridgeError('spawn_failed')));
    child.on('close', (code) => {
      const { rows, error } = parseResponse(code, Buffer.concat(chunks).toString('utf8'));
      settle(error || null, rows);
    });
    child.stdin.end(JSON.stringify(request));
  });
}

function createBridgeReader({ spawnImpl = spawn, timeoutMs = READ_TIMEOUT_MS } = {}) {
  return function readResource(resource, since = 0) {
    if (!RESOURCES.includes(resource)) {
      // Unreachable from HTTP: the six routes are static. A programming error, so
      // it surfaces as a read failure, not as a client-facing 400.
      return Promise.reject(new BridgeError('unknown_resource'));
    }
    return runBridge(spawnImpl, timeoutMs, { resource, since });
  };
}

module.exports = { BridgeError, READ_TIMEOUT_MS, REPO_ROOT, createBridgeReader, parseResponse };
