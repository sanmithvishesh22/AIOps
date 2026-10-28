// Fixed, sanitized read failures for the live adapter.
//
// A read failure in live mode maps to a constant code and message from this
// module. Response bodies, status text, and exception messages are never
// forwarded — an error shown on screen is assembled only from our own strings,
// so nothing from the server (SQL, DSN, stack trace) can reach the browser UI
// (same sanitization rule as the Express API itself, D4-002).
export const READ_ERROR_MESSAGES = Object.freeze({
  network:
    'Could not reach the read API. Start the Express server (aiops/dashboard: npm start) or switch back to mock mode.',
  http_400: 'The read API rejected the request (HTTP 400, invalid_request).',
  http_404: 'The read API does not serve that resource (HTTP 404, not_found).',
  http_503:
    'The read API is reachable but the database read failed (HTTP 503, read_failed). An empty database answers 200 with [] — this is a different state.',
  http_500: 'The read API hit an unexpected internal error (HTTP 500, internal_error).',
  http_other: 'The read API answered an unexpected status.',
  malformed:
    'The read API returned an unexpected payload. This view expects a JSON array of records (Contract E).',
  unknown: 'The read failed for an unclassified reason.',
});

// `detail` must be a constant string built by our own code (e.g. "HTTP 502"),
// never text taken from a response.
export function readError(code, detail) {
  const base = READ_ERROR_MESSAGES[code] || READ_ERROR_MESSAGES.unknown;
  return { code, message: detail ? `${base} (${detail})` : base };
}

export function normalizeReadError(error) {
  if (error && typeof error === 'object' && typeof error.code === 'string'
    && READ_ERROR_MESSAGES[error.code]) {
    return readError(error.code, error.detail);
  }
  return readError('unknown');
}
