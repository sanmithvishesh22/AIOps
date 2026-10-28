// The mock-only remediation workflow (ticket D4-003 §5).
//
// It mirrors the D4-001 lifecycle exactly — the legal moves are the same set
// audited by aiops/remediate/audit.py (`_TRANSITIONS`) and enforced by the
// remediation_audit_guard trigger in experiment/schema.sql:
//
//     proposed -> approved | rejected        (an explicit human decision, name required)
//     approved -> applied                    (a separate, explicit execution step)
//
// Differences, stated plainly: every change here is browser memory. There is no
// network call in this module, nothing is written to the audit database, and
// nothing is sent to Kubernetes. Rejection is terminal; execution is refused
// until the action has been explicitly approved; duplicate or out-of-order
// decisions are refused with a message the UI shows to the operator.
import { deepCopy } from '../lib/clone.js';
import { FIXTURES } from './fixtures.js';

export const MOCK_TRANSITIONS = Object.freeze({
  proposed: Object.freeze(['approved', 'rejected']),
  approved: Object.freeze(['applied']),
  applied: Object.freeze([]),
  rejected: Object.freeze([]),
  failed: Object.freeze([]),
});

export class MockTransitionError extends Error {
  constructor(message) {
    super(message);
    this.name = 'MockTransitionError';
  }
}

const nowSeconds = () => Date.now() / 1000;

export function createMockRemediationStore(seedRows = FIXTURES.remediations) {
  const rows = new Map();
  for (const seed of seedRows) rows.set(seed.action_id, deepCopy(seed));

  function requireRow(actionId) {
    const row = rows.get(actionId);
    if (!row) {
      throw new MockTransitionError(
        `Unknown action #${actionId} — it is not part of this mock session.`,
      );
    }
    return row;
  }

  function requireOperator(operator) {
    const name = typeof operator === 'string' ? operator.trim() : '';
    if (!name) {
      throw new MockTransitionError(
        'An operator name is required for a mock decision. The name is self-reported and is '
        + 'not authentication — it only labels this browser session.',
      );
    }
    return name;
  }

  function decide(actionId, decision, operator) {
    if (decision !== 'approved' && decision !== 'rejected') {
      throw new MockTransitionError(`Unknown decision ${JSON.stringify(decision)}.`);
    }
    const name = requireOperator(operator);
    const row = requireRow(actionId);
    if (row.status !== 'proposed') {
      throw new MockTransitionError(
        `Action #${actionId} is '${row.status}'; only 'proposed' actions can be approved or `
        + 'rejected (it may already have been decided).',
      );
    }
    row.status = decision;
    row.decided_by = name;
    row.decided_at = nowSeconds();
    return deepCopy(row);
  }

  return Object.freeze({
    /** Audit-style listing: proposed_at descending, then action_id descending. */
    list() {
      return [...rows.values()]
        .sort((a, b) => ((Number(b.proposed_at) || 0) - (Number(a.proposed_at) || 0))
          || ((Number(b.action_id) || 0) - (Number(a.action_id) || 0)))
        .map(deepCopy);
    },

    get(actionId) {
      const row = rows.get(actionId);
      return row ? deepCopy(row) : null;
    },

    /** The human gate — the only path from 'proposed' to 'approved'/'rejected'. */
    decide,

    approve(actionId, operator) {
      return decide(actionId, 'approved', operator);
    },

    reject(actionId, operator) {
      return decide(actionId, 'rejected', operator);
    },

    /**
     * Explicit execution step. Refused unless the action is 'approved' — the
     * mock state machine cannot execute before an explicit approval, exactly
     * like D4-001. Success is recorded as 'applied' in this browser session only.
     */
    execute(actionId) {
      const row = requireRow(actionId);
      if (row.status !== 'approved') {
        throw new MockTransitionError(
          `Action #${actionId} is '${row.status}'; execution is only possible after explicit `
          + 'approval.',
        );
      }
      row.status = 'applied';
      row.applied_at = nowSeconds();
      row.outcome = null;
      return deepCopy(row);
    },
  });
}
