/**
 * Tiny CSV utilities — no dependency.
 *
 * - `toCsv(rows, columns)`: build CSV text from an array of records and a
 *   column spec. Quoting follows RFC 4180: any cell containing a comma,
 *   quote, CR, or LF is wrapped in double quotes; embedded quotes are doubled.
 * - `downloadCsv(filename, csv)`: trigger a browser download via Blob URL.
 */

export interface CsvColumn<T> {
  header: string;
  /** Accessor returning either a primitive or a stringifiable value. */
  accessor: (row: T) => string | number | boolean | null | undefined;
}

const escapeCell = (val: string | number | boolean | null | undefined): string => {
  if (val === null || val === undefined) return '';
  const s = String(val);
  if (s === '') return '';
  // Quote if it contains any of: comma, double-quote, CR, LF
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
};

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const header = columns.map(c => escapeCell(c.header)).join(',');
  const body = rows
    .map(row => columns.map(c => escapeCell(c.accessor(row))).join(','))
    .join('\r\n');
  return header + '\r\n' + body + '\r\n';
}

/**
 * Trigger a browser download for the given CSV string.
 * Uses a transient <a> element with a Blob URL.
 */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  // Give the browser a tick to start the download before revoking the URL
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);
}

/** Build a filename with current ET date for sortability. */
export function timestampedFilename(prefix: string, ext = 'csv'): string {
  const now = new Date();
  const stamp = now.toLocaleString('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).replace(/[\/,:]/g, '-').replace(/\s/g, '_');
  return `${prefix}_${stamp}.${ext}`;
}
