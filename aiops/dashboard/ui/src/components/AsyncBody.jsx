import EmptyState from './EmptyState.jsx';

// Loading / error / empty / ready in one place, so every view handles all four
// states the same way. An empty array from a successful read is an empty state —
// never an error and never sample data.
function LoadingState({ label }) {
  return (
    <div className="state-block" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

function ErrorState({ title, error }) {
  return (
    <div className="state-block state-error" role="alert">
      <h3>{title}</h3>
      <p>{error && error.message ? error.message : 'The read failed.'}</p>
      <p className="state-hint">
        Sanitized error — server text is never forwarded to the browser.
      </p>
    </div>
  );
}

export default function AsyncBody({
  state, loadingLabel, errorTitle, emptyTitle, emptyDetail, children,
}) {
  if (state.status === 'loading') return <LoadingState label={loadingLabel} />;
  if (state.status === 'error') return <ErrorState title={errorTitle} error={state.error} />;
  if (state.status === 'empty') {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }
  return children(state.rows);
}
