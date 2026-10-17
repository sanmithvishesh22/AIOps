// Clearly synthetic fixtures for mock mode (ticket D4-003 §5).
//
// These rows are hand-written to mirror the *shapes* the read-API returns —
// Contract A for the four inference views, the remediation_action columns for
// the queue — so the views are exercised against exactly the documented fields.
// They are NOT live data and must never be presented as such: the shell always
// shows the mock/live mode, and mock decisions are simulated in this browser.
//
// The rows below are in the read-API's documented order (ts descending, then the
// documented kind/service/value/meta tie-breaks; remediation rows by
// proposed_at descending, then action_id descending).

export const MOCK_BASE_TS = 1767050000; // 2025-12-29T23:13:20Z — fixed so fixtures are deterministic

const BASE = MOCK_BASE_TS;

function evidence(service, asOf, { withForecast = true, incidentId = 'inc-mock-a' } = {}) {
  return {
    service,
    as_of: asOf,
    anomaly: {
      ts: asOf - 5, module: 'detect', service, kind: 'anomaly_flag', value: 1,
      meta: { detector: 'iforest', threshold: 0.8 },
    },
    rca: {
      ts: asOf - 5, module: 'rca', service, kind: 'culprit_rank', value: 1,
      meta: { score: 0.66, incident_id: incidentId },
    },
    prediction: {
      ts: asOf - 5, module: 'predict', service, kind: 'breach_prob', value: 0.74,
      meta: { horizon_s: 120, threshold: 0.5 },
    },
    ...(withForecast ? {
      forecast: {
        ts: asOf - 5, module: 'forecast', service, kind: 'forecast_p95', value: 455,
        meta: { horizon_s: 120, model: 'prophet' },
      },
    } : {}),
  };
}

export const FIXTURES = Object.freeze({
  anomalies: [
    { ts: BASE - 120, module: 'detect', service: 'front-end', kind: 'anomaly_flag',
      value: 1, meta: { detector: 'iforest', threshold: 0.8 } },
    { ts: BASE - 150, module: 'detect', service: 'front-end', kind: 'anomaly_score',
      value: 0.93, meta: { detector: 'iforest', threshold: 0.8, features: ['p95_ms', 'error_rate'] } },
    { ts: BASE - 185, module: 'detect', service: 'carts', kind: 'anomaly_score_seq',
      value: 0.71, meta: { detector: 'lstm_ae', window_s: 900 } },
    { ts: BASE - 215, module: 'detect', service: 'orders', kind: 'anomaly_flag',
      value: 0, meta: { detector: 'iforest', threshold: 0.8 } },
    { ts: BASE - 300, module: 'detect', service: 'catalogue', kind: 'anomaly_score',
      value: 0.55, meta: { detector: 'iforest', features: ['cpu'] } },
  ],
  rca: [
    { ts: BASE - 120, module: 'rca', service: 'front-end', kind: 'culprit_rank',
      value: 1, meta: { score: 0.71, incident_id: 'inc-mock-a',
        graph_edges: [['front-end', 'orders'], ['front-end', 'carts']] } },
    { ts: BASE - 120, module: 'rca', service: 'orders', kind: 'culprit_rank',
      value: 2, meta: { score: 0.48, incident_id: 'inc-mock-a' } },
    { ts: BASE - 120, module: 'rca', service: 'carts', kind: 'culprit_rank',
      value: 3, meta: { score: 0.31, incident_id: 'inc-mock-a' } },
    { ts: BASE - 900, module: 'rca', service: 'catalogue', kind: 'culprit_rank',
      value: 1, meta: { score: 0.62, incident_id: 'inc-mock-b' } },
  ],
  predictions: [
    { ts: BASE - 60, module: 'predict', service: 'front-end', kind: 'breach_prob',
      value: 0.82, meta: { horizon_s: 120, threshold: 0.5 } },
    { ts: BASE - 75, module: 'predict', service: 'orders', kind: 'breach_prob',
      value: 0.34, meta: { horizon_s: 120, threshold: 0.5 } },
    { ts: BASE - 90, module: 'predict', service: 'front-end', kind: 'breach_duration_est',
      value: 95.5, meta: { horizon_s: 120 } },
    { ts: BASE - 180, module: 'predict', service: 'carts', kind: 'breach_prob',
      value: null, meta: { horizon_s: 120, threshold: 0.5,
        note: 'model returned a non-finite value; stored as null' } },
  ],
  forecasts: [
    { ts: BASE - 30, module: 'forecast', service: 'front-end', kind: 'forecast_p95',
      value: 462, meta: { horizon_s: 120, model: 'prophet' } },
    { ts: BASE - 30, module: 'forecast', service: 'front-end', kind: 'forecast_p95_snaive',
      value: 388, meta: { horizon_s: 120, model: 'seasonal_naive' } },
    { ts: BASE - 30, module: 'forecast', service: 'front-end', kind: 'forecast_p95_tree',
      value: 421.5, meta: { horizon_s: 120, model: 'gradient_boosting' } },
    { ts: BASE - 45, module: 'forecast', service: 'carts', kind: 'forecast_p95',
      value: 310.25, meta: { horizon_s: 120, model: 'prophet' } },
    { ts: BASE - 45, module: 'forecast', service: 'carts', kind: 'forecast_p95_snaive',
      value: null, meta: { horizon_s: 120 } },
  ],
  remediations: [
    { action_id: 7001, proposed_at: BASE - 150, service: 'front-end', action_type: 'scale',
      params: { replicas: 5 }, evidence: evidence('front-end', BASE - 150),
      status: 'proposed', decided_by: null, decided_at: null, applied_at: null,
      outcome: null, run_id: 7 },
    { action_id: 7002, proposed_at: BASE - 260, service: 'carts', action_type: 'restart',
      params: {}, evidence: evidence('carts', BASE - 260, { withForecast: false }),
      status: 'proposed', decided_by: null, decided_at: null, applied_at: null,
      outcome: null, run_id: null },
    { action_id: 7003, proposed_at: BASE - 600, service: 'orders', action_type: 'scale',
      params: { replicas: 4 }, evidence: evidence('orders', BASE - 600),
      status: 'approved', decided_by: 'demo-operator', decided_at: BASE - 540,
      applied_at: null, outcome: null, run_id: 7 },
    { action_id: 7004, proposed_at: BASE - 1000, service: 'payment', action_type: 'restart',
      params: {}, evidence: evidence('payment', BASE - 1000),
      status: 'rejected', decided_by: 'demo-operator', decided_at: BASE - 940,
      applied_at: null, outcome: null, run_id: null },
    { action_id: 7005, proposed_at: BASE - 2000, service: 'catalogue', action_type: 'scale',
      params: { replicas: 3 }, evidence: evidence('catalogue', BASE - 2000),
      status: 'applied', decided_by: 'demo-operator', decided_at: BASE - 1950,
      applied_at: BASE - 1930, outcome: null, run_id: 6 },
    { action_id: 7006, proposed_at: BASE - 3000, service: 'shipping', action_type: 'scale',
      params: { replicas: 6 }, evidence: evidence('shipping', BASE - 3000),
      status: 'failed', decided_by: 'demo-operator', decided_at: BASE - 2950,
      applied_at: null, outcome: 'timeout: replicas did not converge to 6 (desired=4, replicas=4)',
      run_id: null },
  ],
});
