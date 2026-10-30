import { useResource } from '../api/useResource.js';
import AsyncBody from '../components/AsyncBody.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Timestamp from '../components/Timestamp.jsx';
import { downloadCsv } from '../lib/csv.js';
import {
  UNAVAILABLE_METRIC,
  buildExperimentCsv,
  normalizeExperimentRecords,
  splitExperimentRecords,
} from '../lib/evaluation.js';
import {
  formatCount,
  formatDuration,
  formatProbability,
  formatScore,
  isFiniteNumber,
} from '../lib/format.js';

// Only fields the Contract-E response actually carries are shown as metrics.
// `result: null` is an absent scorecard, not a zero-filled one.
const SUPPORTED_METRICS = [
  { label: 'SLO breach duration (primary)', field: 'slo_breach_duration_s', valid: isFiniteNumber, source: 'experiment_result.slo_breach_duration_s' },
  { label: 'Breaching requests (primary)', field: 'breaching_requests', valid: isFiniteNumber, source: 'experiment_result.breaching_requests' },
  { label: 'Breaching request ratio', field: 'breaching_request_ratio', valid: isFiniteNumber, source: 'experiment_result.breaching_request_ratio' },
  { label: 'Pod-minutes (cost)', field: 'pod_minutes', valid: isFiniteNumber, source: 'experiment_result.pod_minutes' },
  { label: 'Scaling actions (churn)', field: 'scaling_actions', valid: isFiniteNumber, source: 'experiment_result.scaling_actions' },
  { label: 'Oscillations (churn)', field: 'oscillations', valid: isFiniteNumber, source: 'experiment_result.oscillations' },
  { label: 'MTTD', field: 'mttd_s', valid: isFiniteNumber, source: 'experiment_result.mttd_s' },
  { label: 'RCA top-1 correct', field: 'rca_top1_correct', valid: (value) => typeof value === 'boolean', source: 'experiment_result.rca_top1_correct' },
  { label: 'Remediation success', field: 'remediation_success', valid: (value) => typeof value === 'boolean', source: 'experiment_result.remediation_success' },
];

// These were required by the historical D3 methodology, but the D3-008
// evaluation output is not present in the tracked API/schema. They are listed
// so the gap is explicit; none is estimated in the browser.
const UNSUPPORTED_METRICS = [
  { label: 'PR-AUC', blocker: 'D3-008 labelled prediction scores and its aggregate PR-AUC output are not in the API data.' },
  { label: 'Precision at the ≥70% target', blocker: 'D3-008 precision/recall output is not in the API data.' },
  { label: 'Forecast error vs seasonal-naive', blocker: 'D3-008 aligned actual observations, the error definition, and its output are not in the API data.' },
  { label: 'Forecast error vs tree baseline', blocker: 'D3-008 aligned actual observations, the error definition, and its output are not in the API data.' },
  { label: '95% confidence intervals for primary outcomes', blocker: 'D3-008 paired-analysis output is not in the API data; no interval is computed in the browser.' },
  { label: 'Effect sizes for primary outcomes', blocker: 'D3-008 paired-analysis output is not in the API data; no effect size is computed in the browser.' },
];

function countWithValue(experiments, field, valid) {
  return experiments.reduce((count, experiment) => (
    experiment.result && valid(experiment.result[field]) ? count + 1 : count
  ), 0);
}

function MetricNumber({ value, formatter, note }) {
  if (!isFiniteNumber(value)) {
    return <span className="missing" title={note}>Unavailable</span>;
  }
  return <span>{formatter(value)}</span>;
}

function MetricBoolean({ value, note }) {
  if (typeof value !== 'boolean') {
    return <span className="missing" title={note}>Unavailable</span>;
  }
  return <span>{value ? 'Yes' : 'No'}</span>;
}

function runIdText(run) {
  return isFiniteNumber(run.run_id) ? `#${formatCount(run.run_id)}` : 'Run id unavailable';
}

function configurationCell(run) {
  const pair = typeof run.pair_id === 'string' && run.pair_id ? `pair ${run.pair_id}` : 'pair unavailable';
  const policy = typeof run.policy === 'string' && run.policy ? run.policy : 'policy unavailable';
  const regime = typeof run.workload_regime === 'string' && run.workload_regime
    ? run.workload_regime
    : 'regime unavailable';
  const fault = typeof run.fault_class === 'string' && run.fault_class
    ? run.fault_class
    : 'fault unavailable';
  const seed = isFiniteNumber(run.seed) ? `seed ${run.seed}` : 'seed unavailable';
  return (
    <span className="cell-stack">
      <span><strong>{policy}</strong></span>
      <span>{regime} · {fault}</span>
      <span className="cell-subtle">{pair} · {seed}</span>
    </span>
  );
}

function sloCell(run) {
  const slo = isFiniteNumber(run.slo_p95_ms) ? formatScore(run.slo_p95_ms, 0) + ' ms' : 'Unavailable';
  const horizon = isFiniteNumber(run.horizon_s) ? `${run.horizon_s}s` : 'Unavailable';
  return <span>{slo} / {horizon}</span>;
}

function ExperimentTable({ experiments, caption }) {
  const missingNote = (experiment) => (
    experiment.hasResult
      ? 'No value in this scorecard (null or non-numeric)'
      : 'No scorecard for this run (result: null)'
  );

  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Started</th>
            <th scope="col">Configuration</th>
            <th scope="col">SLO p95 / horizon</th>
            <th scope="col">Cohort</th>
            <th scope="col">Scorecard</th>
            <th scope="col">SLO breach duration</th>
            <th scope="col">Breaching requests</th>
            <th scope="col">Breach ratio</th>
            <th scope="col">MTTD</th>
            <th scope="col">Pod-minutes</th>
            <th scope="col">Scaling actions</th>
            <th scope="col">Oscillations</th>
            <th scope="col">RCA top-1</th>
            <th scope="col">Remediation success</th>
          </tr>
        </thead>
        <tbody>
          {experiments.map((experiment, index) => {
            const { run, result, hasResult, negative } = experiment;
            const note = missingNote(experiment);
            return (
              <tr key={`${run.run_id}-${index}`}>
                <td className="service-cell">{runIdText(run)}</td>
                <td><Timestamp ts={run.started_at} /></td>
                <td>{configurationCell(run)}</td>
                <td>{sloCell(run)}</td>
                <td>
                  <StatusBadge tone={negative ? 'pending' : 'neutral'}>
                    {negative ? 'Negative control' : 'Normal policy'}
                  </StatusBadge>
                </td>
                <td>
                  <StatusBadge tone={hasResult ? 'info' : 'pending'}>
                    {hasResult ? 'Scorecard available' : 'No scorecard (result: null)'}
                  </StatusBadge>
                </td>
                <td>
                  <MetricNumber
                    value={result && result.slo_breach_duration_s}
                    formatter={formatDuration}
                    note={note}
                  />
                </td>
                <td>
                  <MetricNumber
                    value={result && result.breaching_requests}
                    formatter={formatCount}
                    note={note}
                  />
                </td>
                <td>
                  <MetricNumber
                    value={result && result.breaching_request_ratio}
                    formatter={formatProbability}
                    note={note}
                  />
                </td>
                <td>
                  <MetricNumber
                    value={result && result.mttd_s}
                    formatter={formatDuration}
                    note={note}
                  />
                </td>
                <td>
                  <MetricNumber
                    value={result && result.pod_minutes}
                    formatter={(value) => formatScore(value, 2)}
                    note={note}
                  />
                </td>
                <td>
                  <MetricNumber
                    value={result && result.scaling_actions}
                    formatter={formatCount}
                    note={note}
                  />
                </td>
                <td>
                  <MetricNumber
                    value={result && result.oscillations}
                    formatter={formatCount}
                    note={note}
                  />
                </td>
                <td>
                  <MetricBoolean value={result && result.rca_top1_correct} note={note} />
                </td>
                <td>
                  <MetricBoolean value={result && result.remediation_success} note={note} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExportButton({ experiments, filename, children }) {
  return (
    <button
      type="button"
      className="button"
      onClick={() => downloadCsv(filename, buildExperimentCsv(experiments))}
    >
      {children}
    </button>
  );
}

function Summary({ experiments, normal, negative }) {
  const withScorecard = experiments.filter((experiment) => experiment.hasResult).length;
  const withoutScorecard = experiments.length - withScorecard;
  const negativeWithScorecard = negative.filter((experiment) => experiment.hasResult).length;
  return (
    <div className="summary-grid" role="group" aria-label="Experiment sample counts">
      <div className="summary-card">
        <span className="summary-label">Experiment runs returned</span>
        <span className="summary-value">{experiments.length}</span>
        <span className="summary-detail">{normal.length} normal-policy</span>
      </div>
      <div className="summary-card">
        <span className="summary-label">Runs with a scorecard</span>
        <span className="summary-value">{withScorecard}</span>
        <span className="summary-detail">Measured values only where present</span>
      </div>
      <div className="summary-card">
        <span className="summary-label">Runs with result: null</span>
        <span className="summary-value">{withoutScorecard}</span>
        <span className="summary-detail">Preserved, not zero-filled</span>
      </div>
      <div className="summary-card">
        <span className="summary-label">Negative-control runs</span>
        <span className="summary-value">{negative.length}</span>
        <span className="summary-detail">{negativeWithScorecard} with a scorecard</span>
      </div>
    </div>
  );
}

function MetricCoverage({ normal, negative }) {
  return (
    <section aria-labelledby="coverage-heading">
      <header className="view-header">
        <h3 id="coverage-heading">Metric coverage and provenance</h3>
        <p>
          Counts below are the number of returned runs with a usable value for each field,
          split into normal-policy and negative-control runs. A count of zero means the
          measurement is unavailable in this data — it is not a zero metric. Unsupported
          metrics are not estimated in the browser.
        </p>
      </header>
      <div className="table-scroll">
        <table>
          <caption className="sr-only">
            Evaluation metrics, whether the API provides them, and their provenance
          </caption>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Availability in this data</th>
              <th scope="col">Provenance / missing contract requirement</th>
            </tr>
          </thead>
          <tbody>
            {SUPPORTED_METRICS.map((metric) => {
              const normalCount = countWithValue(normal, metric.field, metric.valid);
              const negativeCount = countWithValue(negative, metric.field, metric.valid);
              const count = normalCount + negativeCount;
              return (
                <tr key={metric.field}>
                  <td>{metric.label}</td>
                  <td>
                    {count > 0
                      ? (
                        <span>
                          {count} run{count === 1 ? '' : 's'} with a value{' '}
                          <span className="cell-subtle">
                            ({normalCount} normal-policy, {negativeCount} negative-control)
                          </span>
                        </span>
                      )
                      : <span className="missing">Unavailable — no value in the returned runs</span>}
                  </td>
                  <td><code>{metric.source}</code></td>
                </tr>
              );
            })}
            {UNSUPPORTED_METRICS.map((metric) => (
              <tr key={metric.label}>
                <td>{metric.label}</td>
                <td><span className="unavailable-label">{UNAVAILABLE_METRIC}</span></td>
                <td>{metric.blocker}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Report({ records }) {
  const experiments = normalizeExperimentRecords(records);
  const { normal, negative } = splitExperimentRecords(experiments);

  return (
    <>
      <Summary experiments={experiments} normal={normal} negative={negative} />

      <p className="semantic-note">
        This view lists per-run instrument measurements from <code>result</code>. It does not
        compute paired policy comparisons, confidence intervals, effect sizes, PR-AUC, or
        forecast error; those require D3-008 evaluation output that is not present in the
        Contract-E response. <code>result.extra</code> is returned by the API but its keys and
        units are undocumented, so it is not interpreted here (the CSV carries it raw as{' '}
        <code>extra_json</code>).
      </p>

      <MetricCoverage normal={normal} negative={negative} />

      <section aria-labelledby="normal-policy-heading">
        <div className="section-heading-row">
          <header className="view-header">
            <h3 id="normal-policy-heading">Normal-policy runs</h3>
            <p>
              Runs whose <code>is_negative_control</code> flag is false. Negative-control runs
              are excluded from this table and summarized separately below.
            </p>
          </header>
          {normal.length > 0 && (
            <ExportButton
              experiments={normal}
              filename="evaluation-normal-policy.csv"
            >
              Export normal-policy runs (CSV)
            </ExportButton>
          )}
        </div>
        {normal.length > 0 ? (
          <ExperimentTable
            experiments={normal}
            caption="Normal-policy experiment runs (negative controls excluded)"
          />
        ) : (
          <p className="state-hint">No normal-policy runs were returned. That is a valid result, not an error.</p>
        )}
      </section>

      <section aria-labelledby="negative-controls-heading" className="negative-section">
        <div className="section-heading-row">
          <header className="view-header">
            <h3 id="negative-controls-heading">Negative controls — reported separately</h3>
            <p>
              Runs where scaling cannot help. They are never mixed into the normal-policy table
              or comparisons; a null or no-improvement result here is the correct result, not a
              failure to hide.
            </p>
          </header>
          {negative.length > 0 && (
            <ExportButton
              experiments={negative}
              filename="evaluation-negative-controls.csv"
            >
              Export negative-control runs (CSV)
            </ExportButton>
          )}
        </div>
        {negative.length > 0 ? (
          <ExperimentTable
            experiments={negative}
            caption="Negative-control experiment runs (reported separately)"
          />
        ) : (
          <p className="state-hint">No negative-control runs were returned.</p>
        )}
      </section>

      <p className="export-note">
        CSV exports keep every displayed run, including runs with <code>result: null</code>;
        missing measurements are empty fields, not zeros. The cohort column also identifies
        negative controls if a file is combined with other data.
      </p>
    </>
  );
}

export default function EvaluationReporting({ read }) {
  const state = useResource(read, 'experiments');
  return (
    <section aria-labelledby="evaluations-heading">
      <header className="view-header">
        <h2 id="evaluations-heading">Evaluation &amp; reporting</h2>
        <p>
          Experiment run metadata and measured scorecards from <code>GET /api/experiments</code>.
          Run metadata and results stay distinct: a run without a scorecard is preserved with{' '}
          <code>result: null</code> rather than being dropped or zero-filled.
        </p>
      </header>
      <p className="semantic-label">Instrument metrics, not reliability proof.</p>
      <p className="semantic-note">
        These are measured instrument readings from experiment runs, not evidence that the
        platform is reliable. Missing measurements are shown as unavailable, never as zero,
        and no metric is inferred from unrelated fields.
      </p>
      <AsyncBody
        state={state}
        loadingLabel="Loading experiment runs…"
        errorTitle="Could not load the evaluation view"
        emptyTitle="No experiment runs"
        emptyDetail="GET /api/experiments answered successfully with an empty array — no experiment run has been recorded or retained. That is a valid result, not an error."
      >
        {(rows) => <Report records={rows} />}
      </AsyncBody>
    </section>
  );
}
