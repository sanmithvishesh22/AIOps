// Ticket D4-003 §8 item 1: the shell and each of the five views render.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from '../src/App.jsx';

async function renderApp() {
  render(<App initialMode="mock" />);
  await screen.findAllByText('front-end');
}

describe('dashboard shell', () => {
  it('shows the title, subtitle, mode indicator, navigation, and footer posture', async () => {
    await renderApp();

    expect(screen.getByRole('heading', { level: 1, name: 'AIOps dashboard' })).toBeInTheDocument();
    expect(screen.getByText(/Read-only observability over the Contract-E API/)).toBeInTheDocument();
    expect(screen.getByText('Mock data')).toBeInTheDocument();
    for (const label of ['Anomaly feed', 'RCA ranking', 'Prediction alerts', 'Forecast', 'Remediation queue']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText(/approval is accountability, not safety/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Anomaly feed' })).toHaveAttribute('aria-current', 'page');
  });

  it('renders the anomaly feed with Contract-A fields from the mock fixtures', async () => {
    await renderApp();

    expect(screen.getByRole('heading', { level: 2, name: 'Anomaly feed' })).toBeInTheDocument();
    expect((await screen.findAllByText('Anomaly flag')).length).toBeGreaterThan(0);
    expect(screen.getByText('Anomaly score (sequence)')).toBeInTheDocument();
    expect(screen.getAllByText('front-end').length).toBeGreaterThan(0);
    expect(screen.getByText('Flagged')).toBeInTheDocument();
    expect(screen.getByText('Clear')).toBeInTheDocument();
  });

  it('renders the RCA ranking with its semantic label', async () => {
    await renderApp();
    fireEvent.click(screen.getByRole('button', { name: 'RCA ranking' }));

    expect(screen.getByRole('heading', { level: 2, name: 'RCA ranking' })).toBeInTheDocument();
    expect(screen.getByText('Ranking, not causality.')).toBeInTheDocument();
    expect((await screen.findAllByText('#1')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('inc-mock-a').length).toBeGreaterThan(0);
  });

  it('renders prediction alerts with probability, threshold state, and duration', async () => {
    await renderApp();
    fireEvent.click(screen.getByRole('button', { name: 'Prediction alerts' }));

    expect(screen.getByRole('heading', { level: 2, name: 'Prediction alerts' })).toBeInTheDocument();
    expect(await screen.findByText('82.0%')).toBeInTheDocument();
    expect(screen.getByText('Above threshold')).toBeInTheDocument();
    expect(screen.getByText('Below threshold')).toBeInTheDocument();
    expect(screen.getByText('1m 35.5s')).toBeInTheDocument();
  });

  it('renders the forecast view with its disclaimer and both baselines', async () => {
    await renderApp();
    fireEvent.click(screen.getByRole('button', { name: 'Forecast' }));

    expect(screen.getByRole('heading', { level: 2, name: 'Forecast' })).toBeInTheDocument();
    expect(screen.getByText('Instrument metric, not reliability proof.')).toBeInTheDocument();
    expect(await screen.findByText('462 ms')).toBeInTheDocument();
    expect(screen.getAllByText('Seasonal-naive baseline').length).toBeGreaterThan(0);
    expect(screen.getByText('Tree baseline')).toBeInTheDocument();
    expect(screen.getAllByText('+120s').length).toBeGreaterThan(0);
  });

  it('renders the remediation queue with all five lifecycle states from the fixtures', async () => {
    await renderApp();
    fireEvent.click(screen.getByRole('button', { name: 'Remediation queue' }));

    expect(screen.getByRole('heading', { level: 2, name: 'Remediation queue' })).toBeInTheDocument();
    const card = await screen.findByRole('article', { name: /Action #7001/ });
    expect(within(card).getByText('Proposed — pending decision')).toBeInTheDocument();
    expect(screen.getByText('Approved — not yet applied')).toBeInTheDocument();
    expect(screen.getByText('Rejected (terminal)')).toBeInTheDocument();
    expect(screen.getByText('Applied', { selector: '.status-badge' })).toBeInTheDocument();
    expect(screen.getByText('Failed', { selector: '.status-badge' })).toBeInTheDocument();
    expect(screen.getByText(/Mock workflow — simulated in this browser only/)).toBeInTheDocument();
  });

  it('keeps the mode indicator visible on every view and switches views without a reload', async () => {
    await renderApp();
    for (const label of ['RCA ranking', 'Prediction alerts', 'Forecast', 'Remediation queue', 'Anomaly feed']) {
      fireEvent.click(screen.getByRole('button', { name: label }));
      expect(screen.getByText('Mock data')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-current', 'page');
    }
  });
});
