import { useResource } from '../api/useResource.js';
import AsyncBody from '../components/AsyncBody.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Timestamp from '../components/Timestamp.jsx';
import Value from '../components/Value.jsx';
import { edgeTexts, formatScore, isFiniteNumber } from '../lib/format.js';

function sortRankedRows(rows) {
  return [...rows].sort((a, b) => {
    const tsA = isFiniteNumber(a.ts) ? a.ts : -Infinity;
    const tsB = isFiniteNumber(b.ts) ? b.ts : -Infinity;
    if (tsA !== tsB) return tsB - tsA;
    const rankA = isFiniteNumber(a.value) ? a.value : Infinity;
    const rankB = isFiniteNumber(b.value) ? b.value : Infinity;
    if (rankA !== rankB) return rankA - rankB;
    const serviceA = String(a.service ?? '');
    const serviceB = String(b.service ?? '');
    return serviceA < serviceB ? -1 : serviceA > serviceB ? 1 : 0;
  });
}

function RcaTable({ rows }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="sr-only">
          Culprit-rank rows from the read API, sorted by time then rank
        </caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Rank</th>
            <th scope="col">Service</th>
            <th scope="col">Score</th>
            <th scope="col">Incident</th>
            <th scope="col">Graph edges</th>
          </tr>
        </thead>
        <tbody>
          {sortRankedRows(rows).map((row, index) => {
            const rank = isFiniteNumber(row.value) ? row.value : null;
            const score = row.meta && typeof row.meta === 'object' && !Array.isArray(row.meta)
              ? formatScore(row.meta.score)
              : null;
            const incident = row.meta && typeof row.meta.incident_id === 'string'
              ? row.meta.incident_id
              : null;
            const edges = row.meta && typeof row.meta === 'object' ? edgeTexts(row.meta.graph_edges) : [];
            return (
              <tr key={`${row.ts}-${row.service}-${row.value}-${index}`}>
                <td><Timestamp ts={row.ts} /></td>
                <td>
                  {rank === null
                    ? <Value text={null} note="No rank value returned for this row" />
                    : (
                      <StatusBadge tone={rank === 1 ? 'info' : 'neutral'}>
                        #{rank}
                      </StatusBadge>
                    )}
                </td>
                <td className="service-cell">{typeof row.service === 'string' ? row.service : '—'}</td>
                <td><Value text={score} note="No numeric score in this row's metadata" /></td>
                <td><Value text={incident} note="No incident id in this row's metadata" /></td>
                <td>
                  {edges.length === 0
                    ? <span className="missing" title="No graph_edges in this row's metadata">—</span>
                    : (
                      <ul className="edge-list">
                        {edges.map((edge, edgeIndex) => <li key={edgeIndex}>{edge}</li>)}
                      </ul>
                    )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function RcaRanking({ read }) {
  const state = useResource(read, 'rca');
  return (
    <section aria-labelledby="rca-heading">
      <header className="view-header">
        <h2 id="rca-heading">RCA ranking</h2>
        <p>
          <code>culprit_rank</code> rows from the <code>rca</code> module, sorted by time
          (newest first) and then by rank. A rank of 1 is the highest-ranked service in its
          incident window.
        </p>
      </header>
      <p className="semantic-label">Ranking, not causality.</p>
      <p className="semantic-note">
        A ranked list orders services by the module's score for a window. It does not prove
        that a service caused the incident, and rank 1 is not a verified root cause.
      </p>
      <AsyncBody
        state={state}
        loadingLabel="Loading RCA rows…"
        errorTitle="Could not load the RCA ranking"
        emptyTitle="No ranked rows"
        emptyDetail="The read API answered successfully with an empty array — no culprit_rank rows have been written for any retained window. That is a valid result, not an error."
      >
        {(rows) => <RcaTable rows={rows} />}
      </AsyncBody>
    </section>
  );
}
