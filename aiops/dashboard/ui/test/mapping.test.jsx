// Ticket D4-003 §8 items 2, 3, 4: API records map to the displayed fields, and
// the two mandatory semantic labels are present.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import AnomalyFeed from '../src/views/AnomalyFeed.jsx';
import ForecastView from '../src/views/ForecastView.jsx';
import LiveRemediationQueue from '../src/views/LiveRemediationQueue.jsx';
import PredictionAlerts from '../src/views/PredictionAlerts.jsx';
import RcaRanking from '../src/views/RcaRanking.jsx';
import { arrayReader, liveRemediationRow } from './helpers.jsx';

const TS = 1767050000; // 2025-12-29T23:13:20.000Z

describe('anomaly feed — field mapping', () => {
  const rows = [
    { ts: TS, module: 'detect', service: 'svc-alpha', kind: 'anomaly_flag',
      value: 1, meta: { detector: 'iforest', threshold: 0.8 } },
    { ts: TS - 15, module: 'detect', service: 'svc-beta', kind: 'anomaly_score',
      value: 0.4261, meta: { features: ['p95_ms', 'error_rate'] } },
    { ts: TS - 30, module: 'detect', service: 'svc-gamma', kind: 'anomaly_score_seq',
      value: null, meta: null },
    { ts: TS - 45, module: 'detect', service: 'svc-delta', kind: 'brand_new_kind',
      value: 5, meta: null },
  ];

  it('maps ts, service, kind, value, and meta without renaming or dropping rows', async () => {
    const { container } = render(<AnomalyFeed read={arrayReader(rows)} />);
    await screen.findByText('svc-alpha');

    const time = container.querySelector('time');
    expect(time).toHaveAttribute('dateTime', '2025-12-29T23:13:20.000Z');
    expect(time.textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);

    expect(screen.getByText('svc-beta')).toBeInTheDocument();
    expect(screen.getByText('Flagged')).toBeInTheDocument();
    expect(screen.getByText('0.426')).toBeInTheDocument();
    expect(screen.getByText('p95_ms, error_rate')).toBeInTheDocument();
    expect(screen.getByText('detector')).toBeInTheDocument();
    expect(screen.getByText('iforest')).toBeInTheDocument();
    // A kind outside the documented three is still shown, labelled as it is.
    expect(screen.getByText('brand_new_kind')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('renders a null value as an explicit missing marker, never as zero', async () => {
    render(<AnomalyFeed read={arrayReader(rows)} />);
    await screen.findByText('svc-gamma');

    expect(screen.getByTitle('The API returned null (no value) for this field')).toBeInTheDocument();
    expect(screen.queryByText('0.000')).toBeNull();
  });
});

describe('RCA view — field mapping and semantics', () => {
  const rows = [
    { ts: TS, module: 'rca', service: 'svc-third', kind: 'culprit_rank',
      value: 3, meta: { score: 0.31, incident_id: 'inc-1' } },
    { ts: TS, module: 'rca', service: 'svc-first', kind: 'culprit_rank',
      value: 1, meta: { score: 0.71, incident_id: 'inc-1', graph_edges: [['svc-first', 'svc-third']] } },
    { ts: TS, module: 'rca', service: 'svc-second', kind: 'culprit_rank',
      value: 2, meta: { score: 0.48, incident_id: 'inc-1' } },
    { ts: TS - 60, module: 'rca', service: 'svc-unranked', kind: 'culprit_rank',
      value: null, meta: { incident_id: 'inc-1' } },
  ];

  it('displays the exact label "Ranking, not causality." and avoids causal claims', async () => {
    render(<RcaRanking read={arrayReader(rows)} />);
    await screen.findByText('svc-first');

    expect(screen.getByText('Ranking, not causality.')).toBeInTheDocument();
    expect(screen.getByText(/does not prove\s+that a service caused the incident/)).toBeInTheDocument();
  });

  it('orders rank ascending within a timestamp and shows rank, score, incident, and edges', async () => {
    const { container } = render(<RcaRanking read={arrayReader(rows)} />);
    await screen.findByText('svc-first');

    const dataRows = container.querySelectorAll('tbody tr');
    expect(dataRows[0].textContent).toContain('svc-first');
    expect(dataRows[1].textContent).toContain('svc-second');
    expect(dataRows[2].textContent).toContain('svc-third');
    expect(dataRows[3].textContent).toContain('svc-unranked');

    const ranks = screen.getAllByText(/^#\d$/).map((node) => node.textContent);
    expect(ranks).toEqual(['#1', '#2', '#3']);
    expect(screen.getByText('0.710')).toBeInTheDocument();
    expect(screen.getAllByText('inc-1').length).toBe(4);
    expect(screen.getByText('svc-first → svc-third')).toBeInTheDocument();
    // The unranked row gets an explicit marker instead of a fabricated rank.
    expect(screen.getByTitle('No rank value returned for this row')).toBeInTheDocument();
  });
});

describe('prediction view — field mapping', () => {
  const rows = [
    { ts: TS, module: 'predict', service: 'svc-alpha', kind: 'breach_prob',
      value: 0.82, meta: { horizon_s: 120, threshold: 0.5 } },
    { ts: TS - 15, module: 'predict', service: 'svc-beta', kind: 'breach_prob',
      value: 0.3, meta: { threshold: 0.5 } },
    { ts: TS - 30, module: 'predict', service: 'svc-alpha', kind: 'breach_duration_est',
      value: 95.5, meta: { horizon_s: 120 } },
    { ts: TS - 45, module: 'predict', service: 'svc-gamma', kind: 'breach_prob',
      value: null, meta: { horizon_s: 120, threshold: 0.5 } },
    { ts: TS - 60, module: 'predict', service: 'svc-delta', kind: 'breach_prob',
      value: 0.6, meta: { horizon_s: 120 } },
  ];

  it('formats probability, duration, threshold state, and horizon by meaning', async () => {
    render(<PredictionAlerts read={arrayReader(rows)} />);
    await screen.findAllByText('svc-alpha');

    expect(screen.getByText('82.0%')).toBeInTheDocument();
    expect(screen.getByText('30.0%')).toBeInTheDocument();
    expect(screen.getByText('1m 35.5s')).toBeInTheDocument();
    expect(screen.getAllByText('Breach probability').length).toBeGreaterThan(0);
    expect(screen.getByText('Estimated breach duration')).toBeInTheDocument();

    const above = screen.getByText('Above threshold');
    expect(above.closest('tr').textContent).toContain('threshold 0.50');
    expect(screen.getByText('Below threshold')).toBeInTheDocument();
    expect(screen.getAllByText('+120s').length).toBeGreaterThan(0);
  });

  it('states a missing threshold and a null probability honestly, with no comparison chip', async () => {
    render(<PredictionAlerts read={arrayReader(rows)} />);
    await screen.findByText('svc-gamma');

    expect(screen.getAllByText('threshold not provided')).toHaveLength(2);
    // Only the numeric probabilities produced a comparison chip.
    expect(screen.getAllByText(/^(Above|Below) threshold$/)).toHaveLength(2);
    expect(screen.getByTitle('No value returned for this prediction (null)')).toBeInTheDocument();
  });
});

describe('forecast view — field mapping and disclaimer', () => {
  const rows = [
    { ts: TS, module: 'forecast', service: 'svc-alpha', kind: 'forecast_p95',
      value: 462, meta: { horizon_s: 120, model: 'prophet' } },
    { ts: TS - 15, module: 'forecast', service: 'svc-alpha', kind: 'forecast_p95_snaive',
      value: 388, meta: { horizon_s: 120, model: 'seasonal_naive' } },
    { ts: TS - 30, module: 'forecast', service: 'svc-alpha', kind: 'forecast_p95_tree',
      value: 421.5, meta: { horizon_s: 120, model: 'gradient_boosting' } },
    { ts: TS - 45, module: 'forecast', service: 'svc-beta', kind: 'forecast_p95',
      value: null, meta: {} },
  ];

  it('displays the exact disclaimer "Instrument metric, not reliability proof."', async () => {
    render(<ForecastView read={arrayReader(rows)} />);
    await screen.findByText('462 ms');

    expect(screen.getByText('Instrument metric, not reliability proof.')).toBeInTheDocument();
  });

  it('shows model, horizon, and value per kind without inventing missing metadata', async () => {
    render(<ForecastView read={arrayReader(rows)} />);
    await screen.findByText('462 ms');

    expect(screen.getByText('388 ms')).toBeInTheDocument();
    expect(screen.getByText('421.5 ms')).toBeInTheDocument();
    expect(screen.getByText('prophet')).toBeInTheDocument();
    expect(screen.getByText('seasonal_naive')).toBeInTheDocument();
    expect(screen.getAllByText('+120s').length).toBe(3);
    expect(screen.getByTitle("No forecast value on this row (null)")).toBeInTheDocument();
    expect(screen.getByTitle("No horizon_s in this row's metadata")).toBeInTheDocument();
    expect(screen.getByTitle("No model in this row's metadata")).toBeInTheDocument();
  });
});

describe('remediation queue (live) — audit-record mapping', () => {
  it('renders every documented audit field and the expandable evidence bundle', async () => {
    const row = liveRemediationRow({
      action_id: 9001,
      status: 'approved',
      decided_by: 'someone',
      decided_at: TS + 30,
      params: { replicas: 4 },
    });
    render(<LiveRemediationQueue read={arrayReader([row])} />);
    const card = await screen.findByRole('article', { name: /Action #9001/ });

    expect(within(card).getByText('Approved — not yet applied')).toBeInTheDocument();
    expect(within(card).getByText('scale')).toBeInTheDocument();
    expect(within(card).getByText(/"replicas": 4/)).toBeInTheDocument();
    expect(within(card).getByText('someone')).toBeInTheDocument();
    expect(within(card).getByText('not applied')).toBeInTheDocument();
    expect(within(card).getByTitle('No outcome was recorded for this action')).toBeInTheDocument();
    expect(within(card).getByText('7')).toBeInTheDocument();

    // Evidence is expandable: hidden until requested.
    expect(within(card).queryByText('Anomaly row')).toBeNull();
    fireEvent.click(within(card).getByRole('button', { name: 'Show evidence (3 rows)' }));
    expect(within(card).getByText('Anomaly row')).toBeInTheDocument();
    expect(within(card).getByText('detect/anomaly_flag')).toBeInTheDocument();
    expect(within(card).getByText('Ranked culprit row')).toBeInTheDocument();
    expect(within(card).getByText('70.0%')).toBeInTheDocument();
    expect(within(card).getByText('Not included in this bundle.')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Hide evidence' }));
    expect(within(card).queryByText('Anomaly row')).toBeNull();
  });

  it('says so when a record carries no evidence bundle', async () => {
    const row = liveRemediationRow({ action_id: 9002, evidence: null });
    render(<LiveRemediationQueue read={arrayReader([row])} />);
    const card = await screen.findByRole('article', { name: /Action #9002/ });

    fireEvent.click(within(card).getByRole('button', { name: 'Show evidence' }));
    expect(within(card).getByText(/No evidence bundle attached to this record/)).toBeInTheDocument();
  });
});
