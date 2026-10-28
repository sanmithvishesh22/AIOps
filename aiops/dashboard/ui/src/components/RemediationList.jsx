import EvidenceBundle from './EvidenceBundle.jsx';
import StatusBadge from './StatusBadge.jsx';
import Timestamp from './Timestamp.jsx';
import Value from './Value.jsx';
import { prettyJson } from '../lib/format.js';

// The audit row's status vocabulary (experiment/schema.sql §4.4). The label
// spells out what each state does and does not mean — displayed status is the
// only evidence an action was approved or applied.
export const STATUS_TONES = {
  proposed: 'pending',
  approved: 'approved',
  applied: 'applied',
  rejected: 'rejected',
  failed: 'failed',
};

export function statusLabel(status) {
  switch (status) {
    case 'proposed': return 'Proposed — pending decision';
    case 'approved': return 'Approved — not yet applied';
    case 'applied': return 'Applied';
    case 'rejected': return 'Rejected (terminal)';
    case 'failed': return 'Failed';
    default: return status || 'unknown status';
  }
}

function DecisionCell({ row, simulated }) {
  if (!row.decided_by) {
    return <span className="missing">Not decided yet — a decision is an explicit human action.</span>;
  }
  return (
    <>
      <strong>{row.decided_by}</strong>
      {' · decided '}
      <Timestamp ts={row.decided_at} />
      {simulated ? <span className="self-reported"> (self-reported name, not authentication)</span> : null}
    </>
  );
}

function AppliedCell({ row }) {
  if (row.applied_at !== null && row.applied_at !== undefined) {
    return <Timestamp ts={row.applied_at} />;
  }
  if (row.status === 'failed') {
    return <span className="missing">not applied — a failed execution or timeout is never success</span>;
  }
  return <span className="missing">not applied</span>;
}

function ActionCard({ row, simulated, actions }) {
  return (
    <article className="action-card" aria-label={`Action #${row.action_id} for ${row.service}`}>
      <header className="action-card-head">
        <div>
          <h3>
            #{row.action_id}
            {' · '}
            {row.service}
          </h3>
          <p className="action-badges">
            <StatusBadge tone={STATUS_TONES[row.status] || 'neutral'}>
              {statusLabel(row.status)}
            </StatusBadge>
            <StatusBadge tone="neutral">{row.action_type}</StatusBadge>
            {simulated ? <StatusBadge tone="simulated">Simulated</StatusBadge> : null}
            <span className="action-proposed">
              proposed <Timestamp ts={row.proposed_at} />
            </span>
          </p>
        </div>
      </header>
      <dl className="action-fields">
        <div>
          <dt>Params</dt>
          <dd>
            {prettyJson(row.params)
              ? <pre className="json">{prettyJson(row.params)}</pre>
              : <span className="missing">none</span>}
          </dd>
        </div>
        <div>
          <dt>Decision</dt>
          <dd><DecisionCell row={row} simulated={simulated} /></dd>
        </div>
        <div>
          <dt>Applied</dt>
          <dd><AppliedCell row={row} /></dd>
        </div>
        <div>
          <dt>Outcome</dt>
          <dd><Value text={row.outcome} note="No outcome was recorded for this action" /></dd>
        </div>
        <div>
          <dt>Experiment run</dt>
          <dd><Value text={row.run_id === null || row.run_id === undefined ? null : String(row.run_id)} note="This action is not linked to an experiment run" /></dd>
        </div>
      </dl>
      <EvidenceBundle evidence={row.evidence} />
      {actions ? <div className="action-controls">{actions}</div> : null}
    </article>
  );
}

// The shared remediation presentation for both modes. `actions` is the row's
// control area (mock: enabled transitions; live: disabled controls), so the
// queue renders identically and only the controls differ.
export default function RemediationList({ rows, simulated = false, actionsFor }) {
  return (
    <div className="action-list">
      {rows.map((row) => (
        <ActionCard
          key={row.action_id}
          row={row}
          simulated={simulated}
          actions={actionsFor ? actionsFor(row) : null}
        />
      ))}
    </div>
  );
}
