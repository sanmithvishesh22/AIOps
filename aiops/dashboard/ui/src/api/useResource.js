import { useEffect, useState } from 'react';

import { normalizeReadError } from './errors.js';

const LOADING = Object.freeze({ status: 'loading', rows: null, error: null });

// Loads one read-API resource and reports a four-state result:
//
//   loading  — request in flight
//   empty    — a 200 with [] (a valid, successful answer, never an error)
//   ready    — a non-empty array of records
//   error    — a sanitized failure (see api/errors.js)
//
// A state change (mode switch, retry) re-runs the read; a result that arrives
// after unmount or after a newer request is discarded.
export function useResource(read, resource) {
  const [state, setState] = useState(LOADING);

  useEffect(() => {
    let cancelled = false;
    setState(LOADING);
    Promise.resolve()
      .then(() => read(resource))
      .then(
        (rows) => {
          if (cancelled) return;
          if (!Array.isArray(rows)) {
            setState({ status: 'error', rows: null, error: normalizeReadError({ code: 'malformed' }) });
            return;
          }
          setState({ status: rows.length === 0 ? 'empty' : 'ready', rows, error: null });
        },
        (error) => {
          if (cancelled) return;
          setState({ status: 'error', rows: null, error: normalizeReadError(error) });
        },
      )
      .catch(() => {
        if (cancelled) return;
        setState({ status: 'error', rows: null, error: normalizeReadError({ code: 'unknown' }) });
      });
    return () => { cancelled = true; };
  }, [read, resource]);

  return state;
}
