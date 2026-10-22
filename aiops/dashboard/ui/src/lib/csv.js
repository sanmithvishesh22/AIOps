// Minimal CSV support for the evaluation export (ticket D4-006).
//
// RFC 4180-style quoting only: a cell containing a comma, quote, CR, or LF is
// wrapped in double quotes, and embedded quotes are doubled. Missing values are
// emitted as empty fields — never as 0 or a fabricated placeholder. Rows are
// separated by CRLF so spreadsheet tools agree on record boundaries even when a
// quoted field contains a newline.

export function csvEscape(value) {
  if (value === null || value === undefined) return '';
  const text = String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv(header, rows) {
  return [header, ...rows]
    .map((row) => row.map(csvEscape).join(','))
    .join('\r\n') + '\r\n';
}

// How long the Blob URL stays alive after click() before it is revoked. Some
// browsers (notably Safari and older Firefox) abort a blob download when the
// object URL is revoked in the same task as the click, so cleanup is deferred
// long enough for the download to begin.
const DOWNLOAD_CLEANUP_DELAY_MS = 1000;

// Browser download helper. Kept separate from the serializer so the CSV shape
// is testable without a DOM. Returns false when no DOM/Blob URL support exists
// (for example in a non-browser test runtime).
export function downloadCsv(filename, csv) {
  if (typeof document === 'undefined' || typeof URL === 'undefined'
    || typeof URL.createObjectURL !== 'function') {
    return false;
  }
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking synchronously after click() can cancel the transfer before the
  // browser starts reading the Blob URL, so release it on a short delay.
  setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_CLEANUP_DELAY_MS);
  return true;
}
