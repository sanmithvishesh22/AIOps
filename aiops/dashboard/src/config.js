'use strict';

// Dashboard-local runtime knobs. Note what is deliberately NOT here:
//
//   - No host setting. Contract E requires localhost-only access, so HOST is a
//     frozen constant: no environment variable or start option can widen the bind
//     to 0.0.0.0 or another interface.
//   - No database setting. This process never reads TIMESCALE_DSN and never holds
//     a connection string; the Python read bridge (aiops/dashboard/bridge.py) gets
//     the DSN from aiops/common/config.py, the Contract-G single source, so a DSN
//     cannot leak into Node logs, responses, or crash reports.
const HOST = '127.0.0.1';

// Local dev port. 8081 on purpose: the in-cluster dashboard path owns 8080 (kind
// NodePort 30080 -> localhost:8080, cluster/kind-config.yaml), so a local bind on
// 8080 would collide with a running cluster. Marked design choice: Contract E pins
// the routes, not the local port. DASHBOARD_PORT is dashboard-local and is NOT
// part of the frozen Contract-G environment set.
const DEFAULT_PORT = 8081;

const PORT_PATTERN = /^\d{1,5}$/;

function parsePort(raw) {
  if (raw === undefined || raw === '') return DEFAULT_PORT;
  if (!PORT_PATTERN.test(raw)) throw new RangeError('DASHBOARD_PORT must be a port number');
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new RangeError('DASHBOARD_PORT must be between 1 and 65535');
  }
  return port;
}

const PORT = parsePort(process.env.DASHBOARD_PORT);

module.exports = { HOST, PORT, DEFAULT_PORT, parsePort };
