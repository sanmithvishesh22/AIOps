import { useResource } from '../api/useResource.js';
import AsyncBody from '../components/AsyncBody.jsx';
import RemediationList from '../components/RemediationList.jsx';

// Live mode is read-only for remediation in D4-003: the queue is shown from
// GET /api/remediations, and approve/reject/execute are disabled with the reason
// stated next to them. Nothing on this page sends a write request.
const DISABLED_NOTE = 'Live control integration is not enabled (D4-003).';
const DISABLED_TITLE = 'Disabled — live approve, reject, and execute are not enabled in this ticket';

function DisabledControls() {
  return (
    <>
      <button type="button" className="button" disabled title={DISABLED_TITLE}>Approve</button>
      <button type="button" className="button" disabled title={DISABLED_TITLE}>Reject</button>
      <button type="button" className="button" disabled title={DISABLED_TITLE}>Execute</button>
      <span className="control-note">
        {DISABLED_NOTE} Live control is deferred to a future loopback-only control adapter
        (design only — <code>aiops/dashboard/CONTROL_ADAPTER.md</code>).
      </span>
    </>
  );
}

export default function LiveRemediationQueue({ read }) {
  const state = useResource(read, 'remediations');
  return (
    <section aria-labelledby="remediations-heading">
      <header className="view-header">
        <h2 id="remediations-heading">Remediation queue</h2>
        <p>
          Audit records from <code>GET /api/remediations</code> — every proposed action and the
          decision recorded against it. Displaying a proposal never means it was approved or
          executed; the Status field is the record.
        </p>
      </header>
      <div className="notice notice-info">
        <h3>Read-only queue — live control is not enabled</h3>
        <p>
          This view sends reads only. The Express read-API exposes no write route, and this UI
          never sends approve, reject, or execute requests: live control integration is deferred
          to a future loopback-only control adapter (design, not code — see{' '}
          <code>aiops/dashboard/CONTROL_ADAPTER.md</code>) pending owner review. The live
          controls below are disabled on purpose.
        </p>
      </div>
      <AsyncBody
        state={state}
        loadingLabel="Loading remediation records…"
        errorTitle="Could not load the remediation queue"
        emptyTitle="No remediation records"
        emptyDetail="GET /api/remediations answered successfully with an empty array — no action has been proposed yet, or none is retained. That is a valid result, not an error."
      >
        {(rows) => <RemediationList rows={rows} actionsFor={() => <DisabledControls />} />}
      </AsyncBody>
    </section>
  );
}
