import { metaEntries } from '../lib/format.js';

// The `meta` JSONB bag, shown only as far as it is present. No defaults are
// invented: a row without meta says so.
export default function MetaEntries({ meta, emptyLabel = 'none' }) {
  const entries = metaEntries(meta);
  if (entries.length === 0) {
    return (
      <span className="missing" title="This row carries no meta object">
        {emptyLabel}
      </span>
    );
  }
  return (
    <ul className="meta-list">
      {entries.map(([key, text]) => (
        <li key={key}>
          <span className="meta-key">{key}</span>
          <span className="meta-value">{text}</span>
        </li>
      ))}
    </ul>
  );
}
