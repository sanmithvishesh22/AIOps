// Data-mode configuration (ticket D4-003 §4).
//
// VITE_API_MODE selects where the UI reads from:
//   'mock' (default) — synthetic in-browser fixtures; no backend required
//   'live'           — GET /api/* from the local Express read-API (Vite proxy)
//
// Unset/empty means mock, so a new local install runs with no backend. Any other
// value is a configuration error the UI shows loudly: silently falling back to
// mock could make synthetic rows look like live data, which is exactly the
// confusion this dashboard must not create.
export const MODES = Object.freeze(['mock', 'live']);

export function parseApiMode(raw) {
  if (raw === undefined || raw === null || raw === '') return 'mock';
  return MODES.includes(raw) ? raw : 'invalid';
}

export function modeConfigErrorMessage(raw) {
  return `VITE_API_MODE is set to ${JSON.stringify(raw)}, which is not a known mode. Use "mock" or "live" (or leave it unset to default to mock).`;
}
