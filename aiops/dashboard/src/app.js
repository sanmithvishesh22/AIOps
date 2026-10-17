'use strict';

// The Contract-E read-API application: exactly six GET routes, nothing else.
// This module registers no write-capable route and no middleware that touches
// request or response bodies — the whole surface is the read side of Contract E
// (docs/CONTRACTS.md §E), deliberately unauthenticated and localhost-only for v1.
//
// Errors are sanitized here too: a failure answers a constant JSON body
// ({"error": ...}) and logs a fixed line naming the failure class only. No
// exception text, SQL, DSN, stack trace, or record content can reach a client or
// a log line.
const express = require('express');

const { RESOURCES } = require('./resources');

// Bounds the optional `since` parameter (unix seconds, 2100-01-01T00:00:00Z).
const MAX_SINCE_S = 4102444800;

// Marked design choice: Contract E pins the six routes and their array responses,
// not query parameters. `?since=<unix seconds>` is an optional inclusive lower
// bound (default 0 = the full retained history), validated here and forwarded to
// the bridge as a value — never as query text.
function parseSince(raw) {
  if (raw === undefined) return 0;
  if (typeof raw !== 'string' || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(raw)) {
    throw new RangeError('since must be a non-negative number of unix seconds');
  }
  const since = Number(raw);
  if (!Number.isFinite(since) || since < 0 || since > MAX_SINCE_S) {
    throw new RangeError('since is out of range');
  }
  return since;
}

function createApp({ readResource }) {
  if (typeof readResource !== 'function') {
    throw new TypeError('createApp needs a readResource(resource, since) function');
  }

  const app = express();
  app.disable('x-powered-by'); // do not advertise the stack in every response

  for (const resource of RESOURCES) {
    app.get(`/api/${resource}`, async (req, res) => {
      let since;
      try {
        since = parseSince(req.query.since);
      } catch (err) {
        res.status(400).json({ error: 'invalid_request' });
        return;
      }
      try {
        const rows = await readResource(resource, since);
        if (!Array.isArray(rows)) throw new Error('adapter returned a non-array');
        res.json(rows);
      } catch (err) {
        const invalid = Boolean(err) && err.kind === 'invalid_request';
        console.error(
          `dashboard: /api/${resource} read failed (${(err && err.kind) || 'unknown'})`,
        );
        res
          .status(invalid ? 400 : 503)
          .json({ error: invalid ? 'invalid_request' : 'read_failed' });
      }
    });
  }

  // Anything else — unknown path, or a write method on a read route — is a 404:
  // this application exposes no write surface at all, so there is nothing to
  // method-negotiate.
  app.use((req, res) => {
    res.status(404).json({ error: 'not_found' });
  });

  // Last-resort handler so an unexpected error is answered as sanitized JSON
  // instead of Express's default HTML that echoes the stack in development.
  // eslint-disable-next-line no-unused-vars
  app.use((err, req, res, next) => {
    console.error('dashboard: request failed (unhandled)');
    res.status(500).json({ error: 'internal_error' });
  });

  return app;
}

module.exports = { MAX_SINCE_S, createApp, parseSince };
