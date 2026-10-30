// Ticket D4-006: evaluation/reporting view, metric integrity, negative-control
// separation, and CSV export behaviour.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import App from '../src/App.jsx';
import { csvEscape } from '../src/lib/csv.js';
import {
  EXPERIMENT_CSV_HEADER,
  UNAVAILABLE_METRIC,
  buildExperimentCsv,
} from '../src/lib/evaluation.js';
import EvaluationReporting from '../src/views/EvaluationReporting.jsx';
import { arrayReader, failingReader, pendingReader } from './helpers.jsx';

const TS = 1767050000;

const RESULT = Object.freeze({
  slo_breach_duration_s: 12.5,
  breaching_requests: 40,
  breaching_request_ratio: 0.25,
  pod_minutes: 3.5,
  scaling_actions: 2,
  oscillations: 1,
  mttd_s: 4.0,
  rca_top1_correct: true,
  remediation_success: true,
  extra: { note: 'synthetic test fixture' },
});

function experiment({
  runId = 701,
  negative = false,
  result = undefined,
  run = {},
} = {}) {
  return {
    run: {
      run_id: runId,
      started_at: TS,
      ended_at: TS + 1200,
      pair_id: 'p-test-1',
      policy: 'forecast_hybrid',
      workload_regime: 'spike',
      fault_class: 'cpu_stress',
      is_negative_control: negative,
      seed: 7,
      slo_p95_ms: 300,
      slo_error_rate: 0.01,
      horizon_s: 120,
      notes: 'target_util=0.70',
      ...run,
    },
    result: result === undefined ? { ...RESULT } : result,
  };
}

// Small RFC-4180 reader used only by these tests, so quoted commas/quotes and
// embedded newlines are checked as records rather than by eyeballing the string.
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\r' && text[index + 1] === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      index += 1;
    } else {
      field += char;
    }
  }

  if (quoted) throw new Error('unterminated CSV quote');
  if (field !== '' || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function columnIndex(header, name) {
  const index = header.indexOf(name);
  if (index === -1) throw new Error(`missing CSV column ${name}`);
  return index;
}

describe('Evaluation & reporting — navigation and states', () => {
  it('is reachable from the navigation and shows the required disclaimer', async () => {
    render(<App initialMode="mock" />);
    await screen.findAllByText('front-end');

    fireEvent.click(screen.getByRole('button', { name: 'Evaluation & reporting' }));

    expect(screen.getByRole('heading', { level: 2, name: 'Evaluation & reporting' })).toBeInTheDocument();
    expect(screen.getByText('Instrument metrics, not reliability proof.')).toBeInTheDocument();
    expect(await screen.findByRole('table', { name: /Normal-policy experiment runs/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export normal-policy runs (CSV)' })).toBeInTheDocument();
  });

  it('shows the loading state while the experiments read is in flight', () => {
    render(<EvaluationReporting read={pendingReader()} />);
    expect(screen.getByRole('status')).toHaveTextContent(/Loading experiment runs/);
  });

  it('shows a sanitized API error state', async () => {
    render(<EvaluationReporting read={failingReader('http_503')} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not load the evaluation view');
    expect(alert).toHaveTextContent('read_failed');
  });

  it('shows an empty state for a successful empty dataset — not sample data', async () => {
    render(<EvaluationReporting read={arrayReader([])} />);

    expect(await screen.findByText('No experiment runs')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('button', { name: /Export/ })).toBeNull();
  });
});

describe('Evaluation & reporting — metric integrity', () => {
  it('labels unsupported D3-008 metrics as unavailable instead of inventing values', async () => {
    render(<EvaluationReporting read={arrayReader([experiment()])} />);
    const coverage = await screen.findByRole('table', { name: /Evaluation metrics/ });

    expect(within(coverage).getByText('PR-AUC')).toBeInTheDocument();
    expect(within(coverage).getByText('Precision at the ≥70% target')).toBeInTheDocument();
    expect(within(coverage).getByText('Forecast error vs seasonal-naive')).toBeInTheDocument();
    expect(within(coverage).getByText('Forecast error vs tree baseline')).toBeInTheDocument();
    expect(within(coverage).getByText('95% confidence intervals for primary outcomes')).toBeInTheDocument();
    expect(within(coverage).getByText('Effect sizes for primary outcomes')).toBeInTheDocument();
    expect(within(coverage).getAllByText(UNAVAILABLE_METRIC)).toHaveLength(6);
  });

  it('preserves a result:null run and marks its measurements unavailable, never zero', async () => {
    render(<EvaluationReporting read={arrayReader([experiment({ runId: 711, result: null })])} />);
    const table = await screen.findByRole('table', { name: /Normal-policy experiment runs/ });
    const row = within(table).getByText('#711').closest('tr');
    const headers = within(table).getAllByRole('columnheader').map((cell) => cell.textContent);

    expect(within(table).getByText('No scorecard (result: null)')).toBeInTheDocument();
    const mttd = row.cells[columnIndex(headers, 'MTTD')];
    expect(mttd).toHaveTextContent('Unavailable');
    expect(mttd).not.toHaveTextContent('0');
    expect(row.cells[columnIndex(headers, 'SLO breach duration')]).toHaveTextContent('Unavailable');
    expect(row.cells[columnIndex(headers, 'RCA top-1')]).toHaveTextContent('Unavailable');
  });

  it('renders a measured zero as zero but a null measurement as unavailable', async () => {
    const result = {
      ...RESULT,
      slo_breach_duration_s: 0,
      mttd_s: null,
      rca_top1_correct: null,
      remediation_success: null,
    };
    render(<EvaluationReporting read={arrayReader([experiment({ runId: 712, result })])} />);
    const table = await screen.findByRole('table', { name: /Normal-policy experiment runs/ });
    const row = within(table).getByText('#712').closest('tr');
    const headers = within(table).getAllByRole('columnheader').map((cell) => cell.textContent);

    expect(row.cells[columnIndex(headers, 'SLO breach duration')]).toHaveTextContent('0s');
    expect(row.cells[columnIndex(headers, 'MTTD')]).toHaveTextContent('Unavailable');
    expect(row.cells[columnIndex(headers, 'RCA top-1')]).toHaveTextContent('Unavailable');
    expect(row.cells[columnIndex(headers, 'Remediation success')]).toHaveTextContent('Unavailable');
  });

  it('reports negative controls in their own table and excludes them from the normal-policy table', async () => {
    render(<EvaluationReporting read={arrayReader([
      experiment({ runId: 801 }),
      experiment({ runId: 802, negative: true }),
    ])} />);

    const normalTable = await screen.findByRole('table', { name: /Normal-policy experiment runs/ });
    const negativeTable = screen.getByRole('table', { name: /Negative-control experiment runs/ });

    expect(within(normalTable).getByText('#801')).toBeInTheDocument();
    expect(within(normalTable).queryByText('#802')).toBeNull();
    expect(within(negativeTable).getByText('#802')).toBeInTheDocument();
    expect(within(negativeTable).queryByText('#801')).toBeNull();
    expect(within(normalTable).getByText('Normal policy')).toBeInTheDocument();
    expect(within(negativeTable).getByText('Negative control')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Negative controls — reported separately' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export negative-control runs (CSV)' })).toBeInTheDocument();

    const coverage = screen.getByRole('table', { name: /Evaluation metrics/ });
    expect(within(coverage).getAllByText(/\(1 normal-policy, 1 negative-control\)/).length).toBeGreaterThan(0);
  });
});

describe('Evaluation & reporting — CSV export', () => {
  it('escapes commas, quotes, and newlines (CR/LF) correctly', () => {
    expect(csvEscape('plain')).toBe('plain');
    expect(csvEscape('a,b')).toBe('"a,b"');
    expect(csvEscape('a"b')).toBe('"a""b"');
    expect(csvEscape('a\nb')).toBe('"a\nb"');
    expect(csvEscape('a\r\nb')).toBe('"a\r\nb"');
    expect(csvEscape(null)).toBe('');
    expect(csvEscape(undefined)).toBe('');
    expect(csvEscape(0)).toBe('0');
  });

  it('keeps quoted commas, quotes, and newlines inside one CSV record', () => {
    const notes = 'comma, "quoted"\nnext line';
    const csv = buildExperimentCsv([experiment({ runId: 901, run: { notes } })]);
    const rows = parseCsv(csv);
    const header = rows[0];

    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveLength(header.length);
    expect(rows[1][columnIndex(header, 'notes')]).toBe(notes);
    expect(csv).toContain('"comma, ""quoted""\nnext line"');
  });

  it('retains missing results and null measurements as empty fields without corrupting rows', () => {
    const noResult = experiment({ runId: 902, result: null });
    const partial = experiment({
      runId: 903,
      result: { ...RESULT, mttd_s: null, rca_top1_correct: null },
    });
    const rows = parseCsv(buildExperimentCsv([noResult, partial]));
    const header = rows[0];

    expect(rows).toHaveLength(3);
    for (const row of rows) expect(row).toHaveLength(header.length);

    const nullRow = rows[1];
    expect(nullRow[columnIndex(header, 'result_status')]).toBe('unavailable');
    for (const field of [
      'slo_breach_duration_s',
      'breaching_requests',
      'breaching_request_ratio',
      'pod_minutes',
      'scaling_actions',
      'oscillations',
      'mttd_s',
      'rca_top1_correct',
      'remediation_success',
      'extra_json',
    ]) {
      expect(nullRow[columnIndex(header, field)]).toBe('');
    }

    const partialRow = rows[2];
    expect(partialRow[columnIndex(header, 'result_status')]).toBe('available');
    expect(partialRow[columnIndex(header, 'slo_breach_duration_s')]).toBe('12.5');
    expect(partialRow[columnIndex(header, 'mttd_s')]).toBe('');
    expect(partialRow[columnIndex(header, 'rca_top1_correct')]).toBe('');
  });

  it('identifies the cohort in every exported row', () => {
    const rows = parseCsv(buildExperimentCsv([
      experiment({ runId: 904 }),
      experiment({ runId: 905, negative: true }),
    ]));
    const header = rows[0];

    expect(rows[1][columnIndex(header, 'cohort')]).toBe('normal_policy');
    expect(rows[2][columnIndex(header, 'cohort')]).toBe('negative_control');
    expect(rows[2][columnIndex(header, 'is_negative_control')]).toBe('true');
    expect(EXPERIMENT_CSV_HEADER).toContain('cohort');
  });

  it('downloads one CSV per displayed cohort without mixing their rows', async () => {
    const blobs = [];
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const originalClick = HTMLAnchorElement.prototype.click;
    URL.createObjectURL = vi.fn((blob) => {
      blobs.push(blob);
      return 'blob:test';
    });
    URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();

    try {
      render(<EvaluationReporting read={arrayReader([
        experiment({ runId: 906 }),
        experiment({ runId: 907, negative: true }),
      ])} />);

      fireEvent.click(await screen.findByRole('button', { name: 'Export normal-policy runs (CSV)' }));
      fireEvent.click(screen.getByRole('button', { name: 'Export negative-control runs (CSV)' }));

      expect(blobs).toHaveLength(2);
      const normalRows = parseCsv(await blobs[0].text());
      const negativeRows = parseCsv(await blobs[1].text());
      const header = normalRows[0];

      expect(normalRows).toHaveLength(2);
      expect(normalRows[1][columnIndex(header, 'run_id')]).toBe('906');
      expect(normalRows[1][columnIndex(header, 'cohort')]).toBe('normal_policy');
      expect(normalRows.some((row) => row[columnIndex(header, 'run_id')] === '907')).toBe(false);

      expect(negativeRows).toHaveLength(2);
      expect(negativeRows[1][columnIndex(header, 'run_id')]).toBe('907');
      expect(negativeRows[1][columnIndex(header, 'cohort')]).toBe('negative_control');
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      HTMLAnchorElement.prototype.click = originalClick;
    }
  });
});
