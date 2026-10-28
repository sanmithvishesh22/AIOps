import { useId, useState } from 'react';

import EmptyState from '../components/EmptyState.jsx';
import RemediationList from '../components/RemediationList.jsx';

const TERMINAL_NOTES = {
  rejected: 'Rejected — rejection is terminal: this action can no longer be approved or executed.',
  applied: 'Applied in simulation only — no Kubernetes change was made and no audit row was written.',
  failed: 'Failed — a failed or timed-out execution is never treated as applied.',
};

// The mock-only approval queue (ticket D4-003 §5). Approve/reject and execute
// are separate explicit operator actions; the store refuses any other move, and
// every decision is simulated in this browser only.
export default function MockRemediationQueue({ store }) {
  const [rows, setRows] = useState(() => store.list());
  const [operator, setOperator] = useState('');
  const [feedback, setFeedback] = useState(null);
  const operatorId = useId();
  const hintId = useId();

  const refresh = () => setRows(store.list());

  function reportRefusal(error) {
    refresh();
    setFeedback({
      kind: 'error',
      message: error && error.message ? error.message : 'The mock transition was refused.',
    });
  }

  function decide(row, decision) {
    const name = operator.trim();
    if (!name) {
      setFeedback({
        kind: 'error',
        message: `Enter an operator name before ${decision === 'approve' ? 'approving' : 'rejecting'} an `
          + 'action. A typed name is self-reported and is not authentication.',
      });
      return;
    }
    try {
      const updated = decision === 'approve'
        ? store.approve(row.action_id, name)
        : store.reject(row.action_id, name);
      refresh();
      setFeedback({
        kind: 'ok',
        message: `Simulated: action #${updated.action_id} ${updated.status} in this browser session `
          + `as “${name}”. Nothing was written to the audit database and nothing was sent to Kubernetes.`,
      });
    } catch (error) {
      reportRefusal(error);
    }
  }

  function execute(row) {
    try {
      const updated = store.execute(row.action_id);
      refresh();
      setFeedback({
        kind: 'ok',
        message: `Simulated: action #${updated.action_id} applied in this browser session only. `
          + 'No Kubernetes call was made and no audit row was written.',
      });
    } catch (error) {
      reportRefusal(error);
    }
  }

  function actionsFor(row) {
    if (row.status === 'proposed') {
      return (
        <>
          <button
            type="button"
            className="button button-primary"
            aria-label={`Approve action #${row.action_id} (simulated)`}
            onClick={() => decide(row, 'approve')}
          >
            Approve (simulated)
          </button>
          <button
            type="button"
            className="button button-danger"
            aria-label={`Reject action #${row.action_id} (simulated)`}
            onClick={() => decide(row, 'reject')}
          >
            Reject (simulated)
          </button>
          <span className="control-note">Execution unlocks only after an explicit approval.</span>
        </>
      );
    }
    if (row.status === 'approved') {
      return (
        <>
          <button
            type="button"
            className="button button-primary"
            aria-label={`Execute action #${row.action_id} (simulated)`}
            onClick={() => execute(row)}
          >
            Execute (simulated)
          </button>
          <span className="control-note">
            Execution is a separate, explicit step — it never happens automatically.
          </span>
        </>
      );
    }
    return <p className="control-note">{TERMINAL_NOTES[row.status] || 'This action is terminal.'}</p>;
  }

  return (
    <section aria-labelledby="remediations-heading">
      <header className="view-header">
        <h2 id="remediations-heading">Remediation queue</h2>
        <p>
          Proposed actions and their audit decisions from the <code>remediation_action</code> log.
          Displaying a proposal never means it was approved or executed — the Status field is the
          record of what actually happened. Approval is accountability, not safety.
        </p>
      </header>
      <div className="notice notice-mock">
        <h3>Mock workflow — simulated in this browser only</h3>
        <p>
          Every decision and execution on this page is held in browser memory. Nothing is written
          to the audit database and nothing is sent to Kubernetes. Real approvals go through the
          audited D4-001 flow with a real identity; the name typed here is self-reported and is
          not authentication.
        </p>
      </div>
      <div className="operator-field">
        <label htmlFor={operatorId}>Operator name for mock decisions</label>
        <input
          id={operatorId}
          type="text"
          value={operator}
          placeholder="e.g. a.operator"
          autoComplete="off"
          aria-describedby={hintId}
          onChange={(event) => setOperator(event.target.value)}
        />
        <p id={hintId} className="field-hint">
          Self-reported and unverified — typing a name is not authentication. It labels this
          browser session&apos;s simulated decision only.
        </p>
      </div>
      {feedback && feedback.kind === 'error'
        ? <p className="feedback feedback-error" role="alert">{feedback.message}</p>
        : null}
      {feedback && feedback.kind === 'ok'
        ? <p className="feedback feedback-ok" role="status">{feedback.message}</p>
        : null}
      {rows.length === 0
        ? (
          <EmptyState
            title="No proposed actions"
            detail="This mock session has no remediation records."
          />
        )
        : <RemediationList rows={rows} simulated actionsFor={actionsFor} />}
    </section>
  );
}
