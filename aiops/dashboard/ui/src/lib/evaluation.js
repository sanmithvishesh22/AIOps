// Evaluation/reporting helpers (ticket D4-006).
//
// The only experiment data available to the browser is the Contract-E
// `/api/experiments` record: `{ run, result: {...} | null }`. The result object
// carries the documented Contract-D fields. Nothing here derives a metric that
// is not present in that payload — in particular there is no PR-AUC, forecast
// error, confidence interval, or effect-size calculation.
import { toCsv } from './csv.js';
import { isFiniteNumber } from './format.js';

// Exact wording required by D4-006 for metrics whose upstream evaluation output
// does not exist in the tracked API/data.
export const UNAVAILABLE_METRIC = 'Unavailable — upstream evaluation output not present';

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// Preserve `result: null` as an explicit absence of a scorecard; never replace
// it with an empty result object or default metric values.
export function normalizeExperiment(record) {
  const run = record && isPlainObject(record.run) ? record.run : {};
  const result = record && isPlainObject(record.result) ? record.result : null;
  return {
    run,
    result,
    hasResult: result !== null,
    negative: run.is_negative_control === true,
  };
}

export function normalizeExperimentRecords(records) {
  return Array.isArray(records) ? records.map(normalizeExperiment) : [];
}

export function splitExperimentRecords(experiments) {
  const normal = [];
  const negative = [];
  for (const experiment of experiments) {
    (experiment.negative ? negative : normal).push(experiment);
  }
  return { normal, negative };
}

function utcIso(ts) {
  if (!isFiniteNumber(ts)) return null;
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return null;
  try {
    return date.toISOString();
  } catch {
    return null;
  }
}

// Scalars only. An unexpected nested value is an unavailable measurement, not a
// stringified object that could be mistaken for a number.
function scalar(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' || typeof value === 'boolean') return value;
  return null;
}

function extraJson(extra) {
  if (extra === null || extra === undefined) return null;
  try {
    return JSON.stringify(extra);
  } catch {
    return null;
  }
}

// One row per experiment run. The `cohort` column keeps negative controls
// visibly separate even if a caller exports both cohorts at once; the view's
// buttons export each cohort separately. Metric cells stay empty when the
// scorecard or the individual measurement is missing.
export const EXPERIMENT_CSV_HEADER = Object.freeze([
  'run_id',
  'started_at_utc',
  'ended_at_utc',
  'pair_id',
  'policy',
  'workload_regime',
  'fault_class',
  'cohort',
  'is_negative_control',
  'seed',
  'slo_p95_ms',
  'slo_error_rate',
  'horizon_s',
  'notes',
  'result_status',
  'slo_breach_duration_s',
  'breaching_requests',
  'breaching_request_ratio',
  'pod_minutes',
  'scaling_actions',
  'oscillations',
  'mttd_s',
  'rca_top1_correct',
  'remediation_success',
  'extra_json',
]);

function experimentCsvRow({ run, result, negative }) {
  return [
    scalar(run.run_id),
    utcIso(run.started_at),
    utcIso(run.ended_at),
    scalar(run.pair_id),
    scalar(run.policy),
    scalar(run.workload_regime),
    scalar(run.fault_class),
    negative ? 'negative_control' : 'normal_policy',
    typeof run.is_negative_control === 'boolean' ? run.is_negative_control : null,
    scalar(run.seed),
    scalar(run.slo_p95_ms),
    scalar(run.slo_error_rate),
    scalar(run.horizon_s),
    scalar(run.notes),
    result ? 'available' : 'unavailable',
    scalar(result && result.slo_breach_duration_s),
    scalar(result && result.breaching_requests),
    scalar(result && result.breaching_request_ratio),
    scalar(result && result.pod_minutes),
    scalar(result && result.scaling_actions),
    scalar(result && result.oscillations),
    scalar(result && result.mttd_s),
    scalar(result && result.rca_top1_correct),
    scalar(result && result.remediation_success),
    result ? extraJson(result.extra) : null,
  ];
}

export function buildExperimentCsv(records) {
  const experiments = normalizeExperimentRecords(records);
  return toCsv(EXPERIMENT_CSV_HEADER, experiments.map(experimentCsvRow));
}
