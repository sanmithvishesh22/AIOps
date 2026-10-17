import { useResource } from '../api/useResource.js';
import AsyncBody from '../components/AsyncBody.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Timestamp from '../components/Timestamp.jsx';
import Value from '../components/Value.jsx';
import { describeValue, formatScore, isFiniteNumber } from '../lib/format.js';

// Contract-A rows from the predict module: breach_prob and breach_duration_est.
const KIND_LABELS = {
  breach_prob: 'Breach probability',
  breach_duration_est: 'Estimated breach duration',
};

// The comparison chip is shown only when a probability AND a threshold are
// present as numbers. Nothing is defaulted: a missing threshold is stated as
// missing, never assumed.
function thresholdCell(row) {
  const threshold = row.meta && typeof row.meta === 'object' && !Array.isArray(row.meta)
    ? row.meta.threshold
    : null;
  const probability = isFiniteNumber(row.value) ? row.value : null;
  const text = formatScore(threshold, 2);
  if (text === null) {
    return <span className="missing" title="No threshold in this row's metadata">threshold not provided</span>;
  }
  if (row.kind === 'breach_prob' && probability !== null) {
    return (
      <span className="threshold-cell">
        <span>threshold {text}</span>
        <StatusBadge tone={probability >= threshold ? 'alert' : 'info'}>
          {probability >= threshold ? 'Above threshold' : 'Below threshold'}
        </StatusBadge>
      </span>
    );
  }
  return <span>threshold {text}</span>;
}

function horizonCell(row) {
  const horizon = row.meta && typeof row.meta === 'object' && !Array.isArray(row.meta)
    ? row.meta.horizon_s
    : null;
  if (!isFiniteNumber(horizon)) {
    return <Value text={null} note="No horizon_s in this row's metadata" />;
  }
  return <span>+{horizon}s</span>;
}

function PredictionTable({ rows }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">
          Breach-prediction rows from the read API, in the API's order (newest first)
        </caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Service</th>
            <th scope="col">Signal</th>
            <th scope="col">Value</th>
            <th scope="col">Threshold</th>
            <th scope="col">Horizon</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const value = describeValue(row);
            return (
              <tr key={`${row.ts}-${row.service}-${row.kind}-${index}`}>
                <td><Timestamp ts={row.ts} /></td>
                <td className="service-cell">{typeof row.service === 'string' ? row.service : '—'}</td>
                <td>
                  <span className="kind-label" title={`Contract-A kind: ${row.kind}`}>
                    {KIND_LABELS[row.kind] || row.kind}
                  </span>
                </td>
                <td><Value text={value.text} note="No value returned for this prediction (null)" /></td>
                <td>{thresholdCell(row)}</td>
                <td>{horizonCell(row)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function PredictionAlerts({ read }) {
  const state = useResource(read, 'predictions');
  return (
    <section aria-labelledby="predictions-heading">
      <header className="view-header">
        <h2 id="predictions-heading">Prediction alerts</h2>
        <p>
          Near-term SLO-breach estimates from the <code>predict</code> module. A probability
          is model output at the stated horizon — an estimate, not a measured breach; the
          threshold shown is the one the row carries.
        </p>
      </header>
      <AsyncBody
        state={state}
        loadingLabel="Loading prediction rows…"
        errorTitle="Could not load prediction alerts"
        emptyTitle="No prediction rows"
        emptyDetail="The read API answered successfully with an empty array — the predictor has not written rows for any retained window. That is a valid result, not an error."
      >
        {(rows) => <PredictionTable rows={rows} />}
      </AsyncBody>
    </section>
  );
}
