import LiveRemediationQueue from './LiveRemediationQueue.jsx';
import MockRemediationQueue from './MockRemediationQueue.jsx';

// The queue is the one view with mode-dependent behaviour, which lives in two
// separate components:
//
//   mock — the in-browser workflow on the mock store (explicit approve/reject,
//          then a separate explicit execute; all simulated);
//   live — GET /api/remediations rendered read-only, with disabled controls.
//
// The live component never receives the mock store, so a mock action cannot be
// sent to the live backend even by accident.
export default function RemediationQueue({ mode, read, store }) {
  if (mode === 'mock') return <MockRemediationQueue store={store} />;
  return <LiveRemediationQueue read={read} />;
}
