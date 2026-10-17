import StatusBadge from './StatusBadge.jsx';

const MODE_EXPLANATION = {
  mock:
    'Synthetic fixtures held in this browser. No backend, database, or cluster is contacted, and every mock decision is simulated — nothing is written to the audit database or sent to Kubernetes.',
  live:
    'Reading GET /api/* from the local Express read-API through the Vite proxy (127.0.0.1:8081). Reads only; no write requests are sent.',
};

function ModeControl({ mode, onChange }) {
  return (
    <div className="mode-control">
      <span className={`mode-badge mode-${mode}`} role="status">
        {mode === 'mock' ? 'Mock data' : 'Live read-API'}
      </span>
      <div className="mode-toggle" role="group" aria-label="Data mode">
        <button
          type="button"
          aria-pressed={mode === 'mock'}
          onClick={() => onChange('mock')}
        >
          Mock
        </button>
        <button
          type="button"
          aria-pressed={mode === 'live'}
          onClick={() => onChange('live')}
        >
          Live
        </button>
      </div>
      <p className="mode-explanation">{MODE_EXPLANATION[mode]}</p>
    </div>
  );
}

// The dashboard shell: title + subtitle, the mock/live indicator, navigation for
// the five views, and the footer that states the v1 posture.
export default function Shell({ mode, onModeChange, views, activeViewId, onNavigate, children }) {
  return (
    <div className="shell">
      <a className="skip-link" href="#dashboard-main">Skip to dashboard content</a>
      <header className="shell-header">
        <div className="shell-title-row">
          <div className="shell-titles">
            <p className="eyebrow">AIOps platform · Dev 4 surface</p>
            <h1>AIOps dashboard</h1>
            <p className="subtitle">
              Read-only observability over the Contract-E API: anomaly feed, RCA ranking,
              prediction alerts, forecasts, and the remediation approval queue.
            </p>
          </div>
          <ModeControl mode={mode} onChange={onModeChange} />
        </div>
        <nav className="view-nav" aria-label="Dashboard views">
          <ul>
            {views.map((view) => {
              const active = view.id === activeViewId;
              return (
                <li key={view.id}>
                  <button
                    type="button"
                    className={active ? 'view-tab is-active' : 'view-tab'}
                    aria-current={active ? 'page' : undefined}
                    onClick={() => onNavigate(view.id)}
                  >
                    {view.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>
      <main id="dashboard-main" className="shell-main">
        {children}
      </main>
      <footer className="shell-footer">
        <p>
          Local research instrument. The read-API is unauthenticated and localhost-only by
          deliberate v1 design, and remediation is human-approved, never autonomous —
          approval is accountability, not safety.
        </p>
        <p>
          <StatusBadge tone="info">Read-only API</StatusBadge>{' '}
          <StatusBadge tone="pending">Human-approved remediation</StatusBadge>
        </p>
      </footer>
    </div>
  );
}
