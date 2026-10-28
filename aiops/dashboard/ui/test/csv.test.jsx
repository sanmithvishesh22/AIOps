// Focused coverage for the CSV download helper (ticket D4-006): the Blob URL
// must outlive click() so the browser can start the download before it is
// revoked. Named .test.jsx like the other UI tests so the Express package's
// node:test discovery does not pick it up.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { downloadCsv } from '../src/lib/csv.js';

const BLOB_URL = 'blob:csv-download-test';

describe('downloadCsv', () => {
  let originalCreateObjectURL;
  let originalRevokeObjectURL;
  let originalAnchorClick;

  beforeEach(() => {
    vi.useFakeTimers();
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    originalAnchorClick = HTMLAnchorElement.prototype.click;
    URL.createObjectURL = vi.fn(() => BLOB_URL);
    URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    HTMLAnchorElement.prototype.click = originalAnchorClick;
  });

  it('defers revoking the Blob URL until after click() so the download can start', () => {
    expect(downloadCsv('runs.csv', 'run_id\r\n1\r\n')).toBe(true);

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();

    vi.runAllTimers();

    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(BLOB_URL);
  });
});
