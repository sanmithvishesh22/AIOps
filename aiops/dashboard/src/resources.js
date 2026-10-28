'use strict';

// Contract E (docs/CONTRACTS.md §E): exactly these six read resources, each a
// documented JSON array. The name is both the endpoint path segment and the
// bridge resource name, so the Express layer never translates a query and never
// builds SQL — the endpoint -> (module, kind) / table mapping lives in one place,
// aiops/dashboard/bridge.py, next to the store.recent() calls it feeds.
const RESOURCES = Object.freeze([
  'anomalies',
  'rca',
  'predictions',
  'forecasts',
  'remediations',
  'experiments',
]);

module.exports = { RESOURCES };
