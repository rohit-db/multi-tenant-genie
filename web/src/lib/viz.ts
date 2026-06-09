// Lightweight result -> chart inference, so Genie answers can auto-visualize
// the way the real AI/BI Genie surface does (bar / line / pie / single stat).

export type ChartKind = "bar" | "line" | "pie" | "stat" | "none";

export interface VizSpec {
  kind: ChartKind;
  labelIndex: number; // x / category column
  valueIndices: number[]; // numeric series columns
}

const TEMPORAL_RE =
  /^(\d{4}([-/]\d{1,2}([-/]\d{1,2})?)?|\d{4}\s?q[1-4]|q[1-4]\s?\d{4})$/i;
const MONTHISH_RE = /(month|date|day|week|quarter|year|period|time|_at|_on)$/i;

function isNumericValue(v: unknown): boolean {
  if (v === null || v === undefined || v === "") return false;
  if (typeof v === "number") return Number.isFinite(v);
  const n = Number(String(v).replace(/[$,%\s]/g, ""));
  return Number.isFinite(n) && /\d/.test(String(v));
}

export function toNumber(v: unknown): number {
  if (typeof v === "number") return v;
  if (v === null || v === undefined) return 0;
  const n = Number(String(v).replace(/[$,%\s]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function columnIsNumeric(
  rows: (string | number | null)[][],
  i: number,
): boolean {
  let seen = 0;
  let numeric = 0;
  for (const r of rows) {
    const v = r[i];
    if (v === null || v === undefined || v === "") continue;
    seen += 1;
    if (isNumericValue(v)) numeric += 1;
  }
  return seen > 0 && numeric / seen >= 0.8;
}

function columnIsTemporal(
  columns: string[],
  rows: (string | number | null)[][],
  i: number,
): boolean {
  if (MONTHISH_RE.test(columns[i] ?? "")) return true;
  let temporal = 0;
  let seen = 0;
  for (const r of rows.slice(0, 12)) {
    const v = r[i];
    if (v === null || v === undefined || v === "") continue;
    seen += 1;
    if (TEMPORAL_RE.test(String(v).trim())) temporal += 1;
  }
  return seen > 0 && temporal / seen >= 0.6;
}

/**
 * Infer a sensible chart for a tabular result. Returns `kind: "none"` when a
 * plain table is the better representation (no numeric series, too many rows,
 * etc.) and `kind: "stat"` for a single scalar answer.
 */
export function inferViz(
  columns: string[],
  rows: (string | number | null)[][],
): VizSpec {
  const none: VizSpec = { kind: "none", labelIndex: 0, valueIndices: [] };
  if (!rows.length || !columns.length) return none;

  const numericCols: number[] = [];
  const nonNumericCols: number[] = [];
  for (let i = 0; i < columns.length; i++) {
    if (columnIsNumeric(rows, i)) numericCols.push(i);
    else nonNumericCols.push(i);
  }

  // Single scalar -> headline stat.
  if (rows.length === 1 && columns.length === 1 && numericCols.length === 1) {
    return { kind: "stat", labelIndex: 0, valueIndices: [0] };
  }
  if (rows.length === 1 && numericCols.length === 1 && columns.length <= 3) {
    return { kind: "stat", labelIndex: 0, valueIndices: numericCols };
  }

  if (numericCols.length === 0) return none;

  // Need a category/label column distinct from the numeric series.
  const labelIndex = nonNumericCols.length ? nonNumericCols[0] : 0;
  const valueIndices = numericCols.filter((i) => i !== labelIndex);
  if (!valueIndices.length) return none;

  // Too many categories reads better as a table.
  if (rows.length > 40) return none;

  // Temporal x-axis -> line.
  if (columnIsTemporal(columns, rows, labelIndex)) {
    return { kind: "line", labelIndex, valueIndices };
  }

  // Small single-series categorical -> pie reads nicely (mix/share).
  if (valueIndices.length === 1 && rows.length >= 2 && rows.length <= 6) {
    return { kind: "pie", labelIndex, valueIndices };
  }

  return { kind: "bar", labelIndex, valueIndices };
}

export const CHART_COLORS = [
  "#6366f1",
  "#22c55e",
  "#f59e0b",
  "#06b6d4",
  "#ef4444",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
];

export function prettyLabel(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bUsd\b/i, "USD")
    .replace(/\bId\b/, "ID");
}

export function formatStat(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = toNumber(v);
  if (!Number.isFinite(n)) return String(v);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(0)}k`;
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
