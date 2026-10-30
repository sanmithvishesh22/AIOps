'use strict';

// Entry point: `npm start` (or `node src/server.js`). Binds the Express app to the
// frozen loopback host from config.js — the host is a constant, not an argument and
// not an environment variable, so there is no unrestricted host override that could
// defeat Contract E's localhost-only v1 constraint.
const http = require('node:http');

const { createApp } = require('./app');
const { createBridgeReader } = require('./bridge');
const { HOST, PORT } = require('./config');

function startServer({ port = PORT, readResource = createBridgeReader() } = {}) {
  const app = createApp({ readResource });
  const server = http.createServer(app);
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, HOST, () => resolve(server));
  });
}

if (require.main === module) {
  startServer().then(
    () => {
      console.log(`aiops dashboard read-API on http://${HOST}:${PORT}/api/<resource>`);
      console.log('read-only, no auth, loopback only (Contract E) — press Ctrl+C to stop');
    },
    (err) => {
      console.error(`dashboard: failed to start (${(err && err.code) || 'unknown'})`);
      process.exitCode = 1;
    },
  );
}

module.exports = { startServer };
