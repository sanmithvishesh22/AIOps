// Ticket D4-003 §8 items 7–11: the mock approval workflow — operator name
// required, execution only after approval, rejection terminal, duplicates and
// invalid transitions refused, everything marked simulated.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MOCK_TRANSITIONS, createMockRemediationStore } from '../src/mock/remediationStore.js';
import MockRemediationQueue from '../src/views/MockRemediationQueue.jsx';

function renderQueue(store = createMockRemediationStore()) {
  render(<MockRemediationQueue store={store} />);
  return store;
}

function cardFor(actionId) {
  return screen.getByRole('article', { name: new RegExp(`Action #${actionId}`) });
}

function typeOperator(name) {
  fireEvent.change(screen.getByLabelText('Operator name for mock decisions'), {
    target: { value: name },
  });
}

describe('mock approval requires an operator name', () => {
  it('refuses approve and reject with an empty name, and accepts a non-empty one', async () => {
    const store = renderQueue();

    fireEvent.click(screen.getByRole('button', { name: 'Approve action #7001 (simulated)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter an operator name/);
    expect(store.get(7001).status).toBe('proposed');
    expect(store.get(7001).decided_by).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Reject action #7002 (simulated)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter an operator name/);
    expect(store.get(7002).status).toBe('proposed');

    typeOperator('  a.tester  ');
    fireEvent.click(screen.getByRole('button', { name: 'Approve action #7001 (simulated)' }));
    expect(store.get(7001).status).toBe('approved');
    expect(store.get(7001).decided_by).toBe('a.tester');

    const card = cardFor(7001);
    expect(within(card).getByText('Approved — not yet applied')).toBeInTheDocument();
    expect(within(card).getByText('a.tester')).toBeInTheDocument();
  });

  it('states in the UI that the typed name is not authentication', () => {
    renderQueue();
    expect(screen.getByText(/Self-reported and unverified — typing a name is not authentication/))
      .toBeInTheDocument();
    expect(screen.getByText(/the name typed here is self-reported and is\s+not authentication/))
      .toBeInTheDocument();
  });

  it('refuses a whitespace-only name at the store level too', () => {
    const store = createMockRemediationStore();
    expect(() => store.approve(7001, '   ')).toThrow(/operator name is required/);
    expect(() => store.reject(7001, '')).toThrow(/operator name is required/);
    expect(store.get(7001).status).toBe('proposed');
  });
});

describe('mock execution requires a prior, explicit approval', () => {
  it('offers no Execute control for a proposed action and refuses the transition', () => {
    const store = renderQueue();
    const card = cardFor(7002);

    expect(within(card).queryByRole('button', { name: /Execute action/ })).toBeNull();
    expect(within(card).getByText('Execution unlocks only after an explicit approval.'))
      .toBeInTheDocument();
    expect(() => store.execute(7002)).toThrow(/execution is only possible after explicit approval/);
    expect(store.get(7002).status).toBe('proposed');
    expect(store.get(7002).applied_at).toBeNull();
  });

  it('applies only through a separate explicit Execute action after approval', () => {
    const store = renderQueue();

    // #7003 is seeded as approved history: approval alone never applied it.
    expect(store.get(7003).status).toBe('approved');
    expect(store.get(7003).applied_at).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Execute action #7003 (simulated)' }));
    expect(store.get(7003).status).toBe('applied');
    expect(store.get(7003).applied_at).not.toBeNull();
    expect(store.get(7003).outcome).toBeNull();

    const card = cardFor(7003);
    expect(within(card).getByText('Applied', { selector: '.status-badge' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /Execute action/ })).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Simulated: action #7003 applied in this browser session only.',
    );
  });
});

describe('mock rejection is terminal', () => {
  it('rejects the reject-then-approve and reject-then-execute paths', async () => {
    const store = renderQueue();

    typeOperator('b.tester');
    fireEvent.click(screen.getByRole('button', { name: 'Reject action #7002 (simulated)' }));
    expect(store.get(7002).status).toBe('rejected');

    const card = cardFor(7002);
    expect(within(card).getByText(/rejection is terminal/)).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /Approve action/ })).toBeNull();
    expect(within(card).queryByRole('button', { name: /Execute action/ })).toBeNull();

    expect(() => store.approve(7002, 'b.tester')).toThrow(/only 'proposed' actions/);
    expect(() => store.reject(7002, 'b.tester')).toThrow(/only 'proposed' actions/);
    expect(() => store.execute(7002)).toThrow(/is 'rejected'/);
    expect(store.get(7002).status).toBe('rejected');
  });
});

describe('duplicate and invalid mock transitions are refused with feedback', () => {
  it('surfaces a stale decision race and does not overwrite the recorded decision', async () => {
    const store = renderQueue();

    // Another operator decides the same action after this page rendered.
    store.approve(7001, 'first-operator');

    typeOperator('second-operator');
    fireEvent.click(screen.getByRole('button', { name: 'Approve action #7001 (simulated)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /is 'approved'; only 'proposed' actions can be approved or rejected/,
    );
    expect(store.get(7001).decided_by).toBe('first-operator');
    expect(store.get(7001).status).toBe('approved');
  });

  it('refuses unknown actions and unknown decisions', () => {
    const store = createMockRemediationStore();
    expect(() => store.approve(9999, 'someone')).toThrow(/Unknown action #9999/);
    expect(() => store.execute(9999)).toThrow(/Unknown action #9999/);
    expect(() => store.decide(7001, 'applied', 'someone')).toThrow(/Unknown decision/);
  });

  it('declares no outgoing transitions from terminal states', () => {
    expect(MOCK_TRANSITIONS.proposed).toEqual(['approved', 'rejected']);
    expect(MOCK_TRANSITIONS.approved).toEqual(['applied']);
    expect(MOCK_TRANSITIONS.applied).toEqual([]);
    expect(MOCK_TRANSITIONS.rejected).toEqual([]);
    expect(MOCK_TRANSITIONS.failed).toEqual([]);
  });
});

describe('mock decisions are clearly marked as simulated', () => {
  it('marks the workflow, every card, and every outcome message', async () => {
    const store = renderQueue();

    expect(screen.getByText(/Mock workflow — simulated in this browser only/)).toBeInTheDocument();
    expect(screen.getAllByText('Simulated')).toHaveLength(6); // one chip per seeded action
    expect(screen.getAllByText(/\(simulated\)$/)).toHaveLength(5); // the enabled controls

    typeOperator('c.tester');
    fireEvent.click(screen.getByRole('button', { name: 'Approve action #7001 (simulated)' }));

    expect(await screen.findByText(/Simulated: action #7001 approved in this browser session/))
      .toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(
      /Nothing was written to the audit database and nothing was sent to Kubernetes/,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Execute action #7001 (simulated)' }));
    expect(store.get(7001).status).toBe('applied');
    expect(screen.getByRole('status')).toHaveTextContent(
      /No Kubernetes call was made and no audit row was written/,
    );
  });
});
