// Ticket D4-003 §8 item 5: loading, empty-array, HTTP-error, and
// malformed-response behaviour for every view, through the real live adapter.
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { createLiveReader } from '../src/api/live.js';
import AnomalyFeed from '../src/views/AnomalyFeed.jsx';
import ForecastView from '../src/views/ForecastView.jsx';
import LiveRemediationQueue from '../src/views/LiveRemediationQueue.jsx';
import PredictionAlerts from '../src/views/PredictionAlerts.jsx';
import RcaRanking from '../src/views/RcaRanking.jsx';
import { arrayReader, httpErrorResponse, jsonResponse, pendingReader } from './helpers.jsx';

const viewCases = [
  {
    name: 'anomaly feed',
    render: (read) => <AnomalyFeed read={read} />,
    loading: /Loading anomaly rows/,
    empty: 'No anomaly rows',
    errorTitle: 'Could not load the anomaly feed',
  },
  {
    name: 'RCA ranking',
    render: (read) => <RcaRanking read={read} />,
    loading: /Loading RCA rows/,
    empty: 'No ranked rows',
    errorTitle: 'Could not load the RCA ranking',
  },
  {
    name: 'prediction alerts',
    render: (read) => <PredictionAlerts read={read} />,
    loading: /Loading prediction rows/,
    empty: 'No prediction rows',
    errorTitle: 'Could not load prediction alerts',
  },
  {
    name: 'forecast view',
    render: (read) => <ForecastView read={read} />,
    loading: /Loading forecast rows/,
    empty: 'No forecast rows',
    errorTitle: 'Could not load the forecast view',
  },
  {
    name: 'remediation queue (live)',
    render: (read) => <LiveRemediationQueue read={read} />,
    loading: /Loading remediation records/,
    empty: 'No remediation records',
    errorTitle: 'Could not load the remediation queue',
  },
];

describe.each(viewCases)('$name: loading / empty / error / malformed', (viewCase) => {
  it('shows a loading state while the read is in flight', () => {
    const { unmount } = render(viewCase.render(pendingReader()));
    expect(screen.getByRole('status')).toHaveTextContent(viewCase.loading);
    unmount();
  });

  it('shows an empty state — not an error, not sample data — for a successful []', async () => {
    render(viewCase.render(arrayReader([])));

    expect(await screen.findByText(viewCase.empty)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('shows a sanitized error for an HTTP failure and never reads the body', async () => {
    const failure = httpErrorResponse(503);
    const read = createLiveReader({ fetchImpl: async () => failure });
    render(viewCase.render(read));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(viewCase.errorTitle);
    expect(alert).toHaveTextContent('read_failed');
    expect(failure.json).not.toHaveBeenCalled();
  });

  it('shows a malformed-payload error for a non-array JSON body', async () => {
    const body = { error: 'not an array', hint: 'postgresql://should-never-be-shown' };
    const read = createLiveReader({ fetchImpl: async () => jsonResponse(body) });
    render(viewCase.render(read));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('unexpected payload');
    expect(alert).not.toHaveTextContent('should-never-be-shown');
  });
});

describe('live adapter failure classification', () => {
  it('reports an unreachable server as a network error', async () => {
    const read = createLiveReader({ fetchImpl: async () => { throw new Error('ECONNREFUSED'); } });
    render(<AnomalyFeed read={read} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not reach the read API');
    expect(alert).not.toHaveTextContent('ECONNREFUSED');
  });

  it('reports an unparseable body as malformed', async () => {
    const badBody = {
      ok: true,
      status: 200,
      json: async () => { throw new SyntaxError('Unexpected token'); },
    };
    const read = createLiveReader({ fetchImpl: async () => badBody });
    render(<AnomalyFeed read={read} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('unexpected payload');
    expect(alert).not.toHaveTextContent('Unexpected token');
  });

  it('maps 400 to invalid_request and passes a valid array through', async () => {
    const bad = createLiveReader({ fetchImpl: async () => httpErrorResponse(400) });
    const { unmount } = render(<AnomalyFeed read={bad} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid_request');
    unmount();

    const row = { ts: 1, module: 'detect', service: 'svc', kind: 'anomaly_flag', value: 0, meta: null };
    const good = createLiveReader({ fetchImpl: async () => jsonResponse([row]) });
    render(<AnomalyFeed read={good} />);
    expect(await screen.findByText('svc')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
