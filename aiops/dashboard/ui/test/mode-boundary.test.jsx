// Ticket D4-003 §8 items 6, 12, 13: mock mode needs no network; live mode shows
// remediation records but never sends approve/reject/execute; switching modes
// cannot leak a mock action into live mode.
import fs from 'node:fs';
import path from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from '../src/App.jsx';
import { parseApiMode } from '../src/api/mode.js';
import { liveRemediationRow, makeFetchStub } from './helpers.jsx';

// Under the jsdom environment Vitest rewrites import.meta.url to an http URL,
// so derive the source directory from the project root (vitest's cwd) instead.
const SRC_DIR = path.resolve(process.cwd(), 'src');

const liveRoutes = () => ({
  '/api/anomalies': [
    { ts: 1767050000, module: 'detect', service: 'live-svc', kind: 'anomaly_flag',
      value: 1, meta: { detector: 'iforest' } },
  ],
  '/api/remediations': [liveRemediationRow({ action_id: 9100, service: 'live-svc' })],
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseApiMode', () => {
  it('defaults to mock, accepts exactly mock|live, and flags anything else', () => {
    expect(parseApiMode(undefined)).toBe('mock');
    expect(parseApiMode('')).toBe('mock');
    expect(parseApiMode('mock')).toBe('mock');
    expect(parseApiMode('live')).toBe('live');
    for (const bad of ['LIVE', 'prod', 'true', 42]) {
      expect(parseApiMode(bad), `parseApiMode(${JSON.stringify(bad)})`).toBe('invalid');
    }
  });
});

describe('mock mode works with no network at all', () => {
  it('renders every view without calling fetch', async () => {
    const fetchSpy = vi.fn(() => { throw new Error('network access attempted in mock mode'); });
    vi.stubGlobal('fetch', fetchSpy);

    render(<App initialMode="mock" />);
    await screen.findAllByText('front-end');

    const probes = [
      ['RCA ranking', 'Ranking, not causality.'],
      ['Prediction alerts', '82.0%'],
      ['Forecast', 'Instrument metric, not reliability proof.'],
      ['Remediation queue', 'Mock workflow — simulated in this browser only'],
      ['Evaluation & reporting', 'Instrument metrics, not reliability proof.'],
      ['Anomaly feed', 'Flagged'],
    ];
    for (const [label, probe] of probes) {
      fireEvent.click(screen.getByRole('button', { name: label }));
      expect(await screen.findByText(probe)).toBeInTheDocument();
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('live mode is read-only for remediation', () => {
  it('shows live records, disables the controls with the reason, and sends GETs only', async () => {
    const stub = makeFetchStub(liveRoutes());
    render(<App initialMode="live" fetchImpl={stub} />);

    expect(screen.getByText('Live read-API')).toBeInTheDocument();
    expect(await screen.findByText('live-svc')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Remediation queue' }));
    const card = await screen.findByRole('article', { name: /Action #9100/ });
    expect(within(card).getByText('Proposed — pending decision')).toBeInTheDocument();
    expect(screen.getByText(/Read-only queue — live control is not enabled/)).toBeInTheDocument();

    const approve = within(card).getByRole('button', { name: 'Approve' });
    const reject = within(card).getByRole('button', { name: 'Reject' });
    const execute = within(card).getByRole('button', { name: 'Execute' });
    for (const control of [approve, reject, execute]) {
      expect(control).toBeDisabled();
      expect(control.getAttribute('title')).toContain('not enabled');
    }
    expect(within(card).getByText(/live control integration is not enabled/i)).toBeInTheDocument();

    const callsBefore = stub.calls.length;
    fireEvent.click(approve);
    fireEvent.click(reject);
    fireEvent.click(execute);
    expect(stub.calls.length).toBe(callsBefore);

    expect(stub.calls.length).toBeGreaterThan(0);
    for (const call of stub.calls) {
      expect(call.method).toBe('GET');
      expect(call.url.startsWith('/api/')).toBe(true);
    }
    expect(new Set(stub.calls.map((call) => call.url))).toEqual(
      new Set(['/api/anomalies', '/api/remediations']),
    );
  });
});

describe('switching modes cannot leak mock actions into live mode', () => {
  it('keeps mock decisions local and never re-sends them when live is active', async () => {
    const stub = makeFetchStub(liveRoutes());
    render(<App initialMode="mock" fetchImpl={stub} />);
    await screen.findAllByText('front-end');

    // Make a mock decision in the browser session.
    fireEvent.click(screen.getByRole('button', { name: 'Remediation queue' }));
    const mockCard = await screen.findByRole('article', { name: /Action #7001/ });
    fireEvent.change(screen.getByLabelText('Operator name for mock decisions'), {
      target: { value: 'mock-operator' },
    });
    fireEvent.click(within(mockCard).getByRole('button', { name: 'Approve action #7001 (simulated)' }));
    expect(await screen.findByText(/Simulated: action #7001 approved/)).toBeInTheDocument();

    // Switch to live: only the live queue from the stub is shown.
    fireEvent.click(screen.getByRole('button', { name: 'Live' }));
    expect(screen.getByText('Live read-API')).toBeInTheDocument();

    const liveCard = await screen.findByRole('article', { name: /Action #9100/ });
    expect(within(liveCard).getByText('Proposed — pending decision')).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: /Action #7001/ })).toBeNull();
    expect(screen.queryByText(/#7001/)).toBeNull();
    expect(screen.queryByText(/Simulated: action #7001 approved/)).toBeNull();
    for (const call of stub.calls) expect(call.method).toBe('GET');

    // Back to mock: the decision never left the browser session.
    fireEvent.click(screen.getByRole('button', { name: 'Mock' }));
    const backCard = await screen.findByRole('article', { name: /Action #7001/ });
    expect(within(backCard).getByText('Approved — not yet applied')).toBeInTheDocument();
    for (const call of stub.calls) expect(call.method).toBe('GET');
  });
});

describe('the UI sources expose no write surface', () => {
  it('mentions no HTTP method other than GET, and only the live adapter touches fetch', () => {
    const files = fs.readdirSync(SRC_DIR, { recursive: true })
      .filter((entry) => typeof entry === 'string' && /\.(js|jsx)$/.test(entry));
    expect(files.length).toBeGreaterThan(10);

    const violations = [];
    const fetchUsers = [];
    for (const file of files) {
      const text = fs.readFileSync(path.join(SRC_DIR, file), 'utf8');
      for (const match of text.matchAll(/method:\s*['"]([A-Za-z]+)['"]/g)) {
        if (match[1] !== 'GET') violations.push(`${file}: ${match[1]}`);
      }
      if (/\bfetch\s*\(|globalThis\.fetch/.test(text)) fetchUsers.push(file);
    }
    expect(violations).toEqual([]);
    expect(fetchUsers.map((file) => file.replaceAll('\\', '/'))).toEqual(['api/live.js']);
  });
});
