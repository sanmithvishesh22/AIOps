// One place decides where reads come from, so no view talks to fetch directly.
// 'live' wraps the GET-only reader; anything else resolves to the offline mock
// fixtures (App never passes an unknown mode — invalid configuration is
// rejected before rendering).
import { createLiveReader } from './live.js';
import { createMockReader } from './mock.js';

export function createClient(mode, options = {}) {
  if (mode === 'live') {
    return Object.freeze({ mode: 'live', read: createLiveReader(options) });
  }
  return Object.freeze({ mode: 'mock', read: createMockReader() });
}
