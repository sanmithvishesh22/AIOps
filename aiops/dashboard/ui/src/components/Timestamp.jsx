import { isMissing, timestampParts } from '../lib/format.js';

// One consistent timestamp treatment: readable local time plus the exact ISO
// instant in `dateTime` and the raw unix seconds in the tooltip.
export default function Timestamp({ ts, label }) {
  const parts = timestampParts(ts);
  if (!parts) {
    return (
      <span
        className="missing"
        title={`No usable timestamp${label ? ` for ${label}` : ''} (null or non-numeric)`}
      >
        —
      </span>
    );
  }
  return (
    <time dateTime={parts.iso} title={`${parts.raw} unix seconds`}>
      {parts.text}
    </time>
  );
}
