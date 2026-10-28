import { useResource } from '../api/useResource.js';
import AsyncBody from '../components/AsyncBody.jsx';
import MetaEntries from '../components/MetaEntries.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Timestamp from '../components/Timestamp.jsx';
import Value from '../components/Value.jsx';
import { describeValue } from '../lib/format.js';

// Contract-A rows from the detect module. The three documented kinds:
// anomaly_score, anomaly_score_seq, anomaly_flag.
const KIND_LABELS = {
  anomaly_score: 'Anomaly score',
  anomaly_score_seq: 'Anomaly score (sequence)',
  anomaly_flag: 'Anomaly flag',
};

function AnomalyTable({ rows }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">
          Anomaly rows from the read API, in the API's order (newest first)
        </caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Service</th>
            <th scope="col">Kind</th>
            <th scope="col">Value</th>
            <th scope="col">Metadata</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const value = describeValue(row);
            const isFlag = row.kind === 'anomaly_flag';
            const flagTone = isFlag && typeof row.value === 'number' && Number.isFinite(row.value)
              ? (row.value === 0 ? 'info' : 'alert')
              : null;
            return (
              <tr key={`${row.ts}-${row.service}-${row.kind}-${index}`}>
                <td><Timestamp ts={row.ts} /></td>
                <td className="service-cell">{typeof row.service === 'string' ? row.service : '—'}</td>
                <td>
                  <span className="kind-label" title={`Contract-A kind: ${row.kind}`}>
                    {KIND_LABELS[row.kind] || row.kind}
                  </span>
                </td>
                <td>
                  {flagTone
                    ? <StatusBadge tone={flagTone}>{value.text}</StatusBadge>
                    : <Value text={value.text} />}
                </td>
                <td><MetaEntries meta={row.meta} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function AnomalyFeed({ read }) {
  const state = useResource(read, 'anomalies');
  return (
    <section aria-labelledby="anomalies-heading">
      <header className="view-header">
        <h2 id="anomalies-heading">Anomaly feed</h2>
        <p>
          Detector rows from the <code>detect</code> module — flags and scores, newest first.
          A score is model output for one window: it ranks attention, it does not diagnose
          the system.
        </p>
      </header>
      <AsyncBody
        state={state}
        loadingLabel="Loading anomaly rows…"
        errorTitle="Could not load the anomaly feed"
        emptyTitle="No anomaly rows"
        emptyDetail="The read API answered successfully with an empty array — the detector has not written rows for any retained window. That is a valid result, not an error."
      >
        {(rows) => <AnomalyTable rows={rows} />}
      </AsyncBody>
    </section>
  );
}
