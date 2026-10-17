// Display formatting for Contract-A / Contract-D records.
//
// Rules this module enforces everywhere:
//   - null / undefined / non-finite numbers are *missing*, not zero and not a
//     placeholder value: every formatter returns null and the components render
//     an explicit "—" with a title explaining the null.
//   - values keep their meaning: ranks stay ranks, probabilities become
//     percentages, durations become durations, p95 values become milliseconds.

export function isMissing(value) {
  return value === null || value === undefined;
}

export function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function pad2(value) {
  return String(value).padStart(2, '0');
}

// A timestamp is rendered as local wall-clock text, with the exact ISO UTC
// instant in the `dateTime` attribute and the raw unix seconds in the tooltip.
export function timestampParts(ts) {
  if (!isFiniteNumber(ts)) return null;
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return null;
  return {
    raw: ts,
    iso: date.toISOString(),
    text: `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} `
      + `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`,
  };
}

export function formatScore(value, digits = 3) {
  return isFiniteNumber(value) ? value.toFixed(digits) : null;
}

export function formatProbability(value) {
  return isFiniteNumber(value) ? `${(value * 100).toFixed(1)}%` : null;
}

export function formatDuration(seconds) {
  if (!isFiniteNumber(seconds)) return null;
  const rounded = Math.round(seconds * 10) / 10;
  if (rounded < 60) return `${rounded}s`;
  const minutes = Math.floor(rounded / 60);
  const rest = Math.round((rounded - minutes * 60) * 10) / 10;
  return `${minutes}m ${rest}s`;
}

export function formatMilliseconds(value) {
  if (!isFiniteNumber(value)) return null;
  return `${Number(value.toFixed(1))} ms`;
}

export function formatCount(value) {
  return isFiniteNumber(value) ? String(value) : null;
}

// Per-kind display text for a Contract-A row value. Unknown kinds fall back to
// the raw value — never dropped, never invented.
export function describeValue(row) {
  const value = row ? row.value : null;
  switch (row && row.kind) {
    case 'anomaly_flag':
      if (!isFiniteNumber(value)) return { text: null };
      if (value === 0) return { text: 'Clear' };
      if (value === 1) return { text: 'Flagged' };
      return { text: `Flagged (${value})` };
    case 'anomaly_score':
    case 'anomaly_score_seq':
      return { text: formatScore(value) };
    case 'culprit_rank':
      return { text: formatCount(value) };
    case 'breach_prob':
      return { text: formatProbability(value) };
    case 'breach_duration_est':
      return { text: formatDuration(value) };
    case 'forecast_p95':
    case 'forecast_p95_snaive':
    case 'forecast_p95_tree':
      return { text: formatMilliseconds(value) };
    default:
      return { text: isMissing(value) ? null : String(value) };
  }
}

// meta is a stored JSONB bag; only entries that exist are shown.
function metaPlainValue(value) {
  if (isMissing(value)) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const scalarList = value.every((item) => isMissing(item)
      || ['string', 'number', 'boolean'].includes(typeof item));
    if (scalarList) return value.map(metaPlainValue).join(', ');
  }
  try {
    return JSON.stringify(value);
  } catch {
    return '[unserializable]';
  }
}

export function metaEntries(meta) {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return [];
  return Object.entries(meta).map(([key, value]) => [key, metaPlainValue(value)]);
}

export function prettyJson(value) {
  if (isMissing(value)) return null;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return null;
  }
}

// `graph_edges` arrives as [[from, to], ...] in Contract-A meta; render edges
// readably, and fall back to the raw value for any other shape.
export function edgeTexts(edges) {
  if (!Array.isArray(edges)) return [];
  return edges.map((edge) => {
    if (Array.isArray(edge) && edge.length >= 2
      && typeof edge[0] === 'string' && typeof edge[1] === 'string') {
      return `${edge[0]} → ${edge[1]}`;
    }
    return metaPlainValue(edge);
  });
}
