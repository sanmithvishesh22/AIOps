import { useResource } from '../api/useResource.js';
import AsyncBody from '../components/AsyncBody.jsx';
import Timestamp from '../components/Timestamp.jsx';
import Value from '../components/Value.jsx';
import { describeValue, isFiniteNumber } from '../lib/format.js';

// Contract-A rows from the forecast module.
const SERIES_LABELS = {
  forecast_p95: 'Forecast p95 (model)',
  forecast_p95_snaive: 'Seasonal-naive baseline',
  forecast_p95_tree: 'Tree baseline',
};

function horizonText(meta) {
  const horizon = meta && typeof meta === 'object' && !Array.isArray(meta) ? meta.horizon_s : null;
  return isFiniteNumber(horizon) ? `+${horizon}s` : null;
}

function modelText(meta) {
  const model = meta && typeof meta === 'object' && !Array.isArray(meta) ? meta.model : null;
  return typeof model === 'string' && model ? model : null;
}

function ForecastTable({ rows }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">
          Forecast rows from the read API, in the API's order (newest first)
        </caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Service</th>
            <th scope="col">Series</th>
            <th scope="col">Forecast p95</th>
            <th scope="col">Horizon</th>
            <th scope="col">Model</th>
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
                    {SERIES_LABELS[row.kind] || row.kind}
                  </span>
                </td>
                <td><Value text={value.text} note="No forecast value on this row (null)" /></td>
                <td><Value text={horizonText(row.meta)} note="No horizon_s in this row's metadata" /></td>
                <td><Value text={modelText(row.meta)} note="No model in this row's metadata" /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ForecastView({ read }) {
  const state = useResource(read, 'forecasts');
  return (
    <section aria-labelledby="forecasts-heading">
      <header className="view-header">
        <h2 id="forecasts-heading">Forecast</h2>
        <p>
          Forecast p95 latency and its baselines from the <code>forecast</code> module.
          Horizon and model are shown only when the row's metadata provides them.
        </p>
      </header>
      <p className="semantic-label">Instrument metric, not reliability proof.</p>
      <p className="semantic-note">
        A forecast is model output about one instrument metric at the stated horizon. It does
        not demonstrate that the system is reliable, and no threshold or SLO is inferred here
        — the experiment, not this view, judges policy quality.
      </p>
      <AsyncBody
        state={state}
        loadingLabel="Loading forecast rows…"
        errorTitle="Could not load the forecast view"
        emptyTitle="No forecast rows"
        emptyDetail="The read API answered successfully with an empty array — the forecaster has not written rows for any retained window. That is a valid result, not an error."
      >
        {(rows) => <ForecastTable rows={rows} />}
      </AsyncBody>
    </section>
  );
}
