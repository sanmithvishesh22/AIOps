import { isMissing } from '../lib/format.js';

// Renders a formatted string, or an explicit missing-value marker when the
// formatter returned null (null / non-finite input). The tooltip explains the
// gap — a missing value is never silently replaced with 0 or a placeholder.
export default function Value({ text, note }) {
  if (isMissing(text)) {
    return (
      <span className="missing" title={note || 'The API returned null (no value) for this field'}>
        —
      </span>
    );
  }
  return <span>{text}</span>;
}
