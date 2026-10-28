// Shared, deterministic fixtures for the UI tests. Only *.test.jsx files live in
// this directory (plus this .jsx helper): the Express package's `node --test`
// discovery recurses into `**/test/**/*.js`, and a plain .js helper here would
// be picked up and run by the backend suite.
import { readError } from '../src/api/errors.js';

export { FIXTURES, MOCK_BASE_TS } from '../src/mock/fixtures.js';

export function arrayReader(rows) {
  return async () => rows;
}

export function resourceReader(map) {
  return async (resource) => map[resource] ?? [];
}

export function pendingReader() {
  return () => new Promise(() => {});
}

export function failingReader(code) {
  return async () => { throw readError(code); };
}

export function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn(async () => body),
  };
}

// A failed response whose body must never be read by the UI: json() throws if
// called, which the sanitization tests assert against.
export function httpErrorResponse(status) {
  return {
    ok: false,
    status,
    json: vi.fn(async () => { throw new Error('an error body must never be read'); }),
  };
}

export function makeFetchStub(routes = {}) {
  const calls = [];
  const stub = async (url, options = {}) => {
    calls.push({ url, method: (options && options.method) || 'GET' });
    const route = routes[url];
    if (route === undefined) return jsonResponse([]);
    if (typeof route === 'function') return route(url, options);
    return jsonResponse(route);
  };
  stub.calls = calls;
  return stub;
}

export function liveRemediationRow(overrides = {}) {
  return {
    action_id: 9001,
    proposed_at: 1767050000,
    service: 'front-end',
    action_type: 'scale',
    params: { replicas: 4 },
    evidence: {
      service: 'front-end',
      as_of: 1767049990,
      anomaly: { ts: 1767049990, module: 'detect', service: 'front-end', kind: 'anomaly_flag', value: 1, meta: { detector: 'iforest' } },
      rca: { ts: 1767049990, module: 'rca', service: 'front-end', kind: 'culprit_rank', value: 1, meta: { score: 0.6 } },
      prediction: { ts: 1767049990, module: 'predict', service: 'front-end', kind: 'breach_prob', value: 0.7, meta: { horizon_s: 120, threshold: 0.5 } },
    },
    status: 'proposed',
    decided_by: null,
    decided_at: null,
    applied_at: null,
    outcome: null,
    run_id: 7,
    ...overrides,
  };
}
