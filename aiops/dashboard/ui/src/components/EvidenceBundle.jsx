import { useState } from 'react';

import MetaEntries from './MetaEntries.jsx';
import Timestamp from './Timestamp.jsx';
import Value from './Value.jsx';
import { describeValue } from '../lib/format.js';

const SLOT_LABELS = {
  anomaly: 'Anomaly row',
  rca: 'Ranked culprit row',
  prediction: 'Prediction row',
  forecast: 'Forecast row',
};
const SLOTS = ['anomaly', 'rca', 'prediction', 'forecast'];

function EvidenceSlot({ slot, row }) {
  if (!row || typeof row !== 'object') {
    return (
      <section className="evidence-slot">
        <h4>{SLOT_LABELS[slot]}</h4>
        <p className="missing">Not included in this bundle.</p>
      </section>
    );
  }
  return (
    <section className="evidence-slot">
      <h4>
        {SLOT_LABELS[slot]}{' '}
        <code className="kind-tag">{row.module}/{row.kind}</code>
      </h4>
      <dl className="evidence-fields">
        <div>
          <dt>Time</dt>
          <dd><Timestamp ts={row.ts} /></dd>
        </div>
        <div>
          <dt>Value</dt>
          <dd><Value text={describeValue(row).text} /></dd>
        </div>
        <div>
          <dt>Meta</dt>
          <dd><MetaEntries meta={row.meta} /></dd>
        </div>
      </dl>
    </section>
  );
}

// The Contract-F evidence bundle, expanded on request. The API returns it
// exactly as stored; this component reads it and adds nothing.
export default function EvidenceBundle({ evidence }) {
  const [open, setOpen] = useState(false);
  const hasBundle = evidence !== null && typeof evidence === 'object' && !Array.isArray(evidence);
  const presentSlots = hasBundle ? SLOTS.filter((slot) => evidence[slot]) : [];

  return (
    <div className="evidence">
      <button
        type="button"
        className="evidence-toggle"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {open
          ? 'Hide evidence'
          : `Show evidence${presentSlots.length ? ` (${presentSlots.length} row${presentSlots.length === 1 ? '' : 's'})` : ''}`}
      </button>
      {open && (hasBundle ? (
        <div className="evidence-body">
          <dl className="evidence-fields">
            <div>
              <dt>Service</dt>
              <dd>{typeof evidence.service === 'string' ? evidence.service : '—'}</dd>
            </div>
            <div>
              <dt>As of</dt>
              <dd><Timestamp ts={evidence.as_of} /></dd>
            </div>
          </dl>
          {SLOTS.map((slot) => (
            <EvidenceSlot key={slot} slot={slot} row={evidence[slot]} />
          ))}
        </div>
      ) : (
        <p className="evidence-missing">
          No evidence bundle attached to this record (the read API returns
          {' '}<code>evidence</code> exactly as stored).
        </p>
      ))}
    </div>
  );
}
