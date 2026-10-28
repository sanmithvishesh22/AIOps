// The offline data source (mock mode): clearly synthetic fixtures held in the
// browser. It returns a fresh copy of the same shape the live adapter returns,
// so the views run with zero backend, database, or cluster.
import { deepCopy } from '../lib/clone.js';
import { FIXTURES } from '../mock/fixtures.js';

export function createMockReader(fixtures = FIXTURES) {
  return async function read(resource) {
    const rows = fixtures[resource];
    if (!rows) throw new Error(`mock fixtures have no '${resource}' resource`);
    return deepCopy(rows);
  };
}
