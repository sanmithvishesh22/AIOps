// The only network code in the UI: GET reads against the Contract-E read-API
// (the six documented endpoints, including experiments for evaluation/reporting).
//
// There is deliberately no write path in this module: nothing here can approve,
// reject, or execute anything, in any mode. Live remediation control is deferred
// to a future loopback-only control adapter (aiops/dashboard/CONTROL_ADAPTER.md,
// design only).
import { readError } from './errors.js';

export const API_BASE = '/api';

function statusCode(status) {
  if (status === 400) return 'http_400';
  if (status === 404) return 'http_404';
  if (status === 503) return 'http_503';
  if (status === 500) return 'http_500';
  return 'http_other';
}

export function createLiveReader({ fetchImpl } = {}) {
  const doFetch = fetchImpl || ((...args) => globalThis.fetch(...args));
  return async function read(resource) {
    let response;
    try {
      response = await doFetch(`${API_BASE}/${resource}`, {
        method: 'GET',
        headers: { accept: 'application/json' },
      });
    } catch {
      throw readError('network');
    }
    if (!response || !response.ok) {
      const status = response && Number.isInteger(response.status) ? response.status : null;
      throw readError(statusCode(status), status === null ? undefined : `HTTP ${status}`);
    }
    let body;
    try {
      body = await response.json();
    } catch {
      throw readError('malformed');
    }
    const isRecordArray = Array.isArray(body)
      && body.every((row) => row !== null && typeof row === 'object' && !Array.isArray(row));
    if (!isRecordArray) throw readError('malformed');
    return body;
  };
}
