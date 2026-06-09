import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";
import { BarChart3, TableIcon } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  inferViz,
  toNumber,
  prettyLabel,
  formatStat,
  CHART_COLORS,
  type VizSpec,
} from "@/lib/viz";

interface AnswerVizProps {
  columns: string[];
  rows: (string | number | null)[][];
  /** Cap the number of rows the table renders. */
  maxRows?: number;
}

/**
 * Renders a Genie-style result: a single headline stat, an auto-inferred
 * chart with a Chart/Table toggle, or a plain table — whichever fits the
 * shape of the data best.
 */
export function AnswerViz({ columns, rows, maxRows = 50 }: AnswerVizProps) {
  const cols = columns.length
    ? columns
    : rows[0]?.map((_, i) => `c${i}`) ?? [];
  const spec = useMemo(() => inferViz(cols, rows), [cols, rows]);
  const [view, setView] = useState<"chart" | "table">(
    spec.kind === "none" || spec.kind === "stat" ? "table" : "chart",
  );

  if (!rows.length) return null;

  if (spec.kind === "stat") {
    return <StatBlock cols={cols} rows={rows} spec={spec} />;
  }

  const hasChart = spec.kind !== "none";

  return (
    <div className="space-y-2">
      {hasChart && (
        <div className="flex items-center justify-end">
          <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
            <ToggleBtn
              active={view === "chart"}
              onClick={() => setView("chart")}
              icon={<BarChart3 className="h-3.5 w-3.5" />}
              label="Chart"
            />
            <ToggleBtn
              active={view === "table"}
              onClick={() => setView("table")}
              icon={<TableIcon className="h-3.5 w-3.5" />}
              label="Table"
            />
          </div>
        </div>
      )}

      {hasChart && view === "chart" ? (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <ChartView cols={cols} rows={rows} spec={spec} />
        </div>
      ) : (
        <ResultTable cols={cols} rows={rows} maxRows={maxRows} />
      )}
    </div>
  );
}

function ToggleBtn({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
        active
          ? "bg-white text-slate-900 shadow-sm"
          : "text-slate-500 hover:text-slate-700",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function StatBlock({
  cols,
  rows,
  spec,
}: {
  cols: string[];
  rows: (string | number | null)[][];
  spec: VizSpec;
}) {
  const row = rows[0] ?? [];
  return (
    <div className="flex flex-wrap gap-3">
      {spec.valueIndices.map((vi) => (
        <div
          key={vi}
          className="min-w-[140px] flex-1 rounded-xl border border-slate-200 bg-gradient-to-br from-[var(--brand-soft)]/60 to-white px-4 py-3"
        >
          <div className="text-[11px] uppercase tracking-wider text-slate-500">
            {prettyLabel(cols[vi] ?? "Value")}
          </div>
          <div className="mt-0.5 text-3xl font-semibold tracking-tight tabular-nums text-[var(--brand-strong)]">
            {formatStat(row[vi])}
          </div>
        </div>
      ))}
    </div>
  );
}

function ChartView({
  cols,
  rows,
  spec,
}: {
  cols: string[];
  rows: (string | number | null)[][];
  spec: VizSpec;
}) {
  const data = useMemo(
    () =>
      rows.map((r) => {
        const o: Record<string, string | number> = {
          __label: String(r[spec.labelIndex] ?? ""),
        };
        for (const vi of spec.valueIndices) o[cols[vi]] = toNumber(r[vi]);
        return o;
      }),
    [rows, cols, spec],
  );

  const axisTick = { fontSize: 11, fill: "#64748b" };
  const tooltipStyle = {
    fontSize: 12,
    border: "1px solid #e2e8f0",
    borderRadius: 6,
  };

  if (spec.kind === "pie") {
    const key = cols[spec.valueIndices[0]];
    return (
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={data}
            dataKey={key}
            nameKey="__label"
            cx="50%"
            cy="50%"
            innerRadius={52}
            outerRadius={84}
            paddingAngle={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Legend
            verticalAlign="bottom"
            height={28}
            iconSize={8}
            wrapperStyle={{ fontSize: 11, color: "#64748b" }}
          />
          <Tooltip contentStyle={tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (spec.kind === "line") {
    return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 10, right: 12, left: -12, bottom: 0 }}>
          <CartesianGrid stroke="#f1f5f9" vertical={false} />
          <XAxis dataKey="__label" tick={axisTick} tickLine={false} axisLine={{ stroke: "#e2e8f0" }} />
          <YAxis tick={axisTick} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={tooltipStyle} />
          {spec.valueIndices.length > 1 && (
            <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: "#64748b" }} />
          )}
          {spec.valueIndices.map((vi, i) => (
            <Line
              key={vi}
              type="monotone"
              dataKey={cols[vi]}
              stroke={CHART_COLORS[i % CHART_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 2.5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // bar
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 10, right: 12, left: -12, bottom: 0 }}>
        <CartesianGrid stroke="#f1f5f9" vertical={false} />
        <XAxis
          dataKey="__label"
          tick={axisTick}
          tickLine={false}
          axisLine={{ stroke: "#e2e8f0" }}
          interval={0}
          angle={data.length > 6 ? -20 : 0}
          textAnchor={data.length > 6 ? "end" : "middle"}
          height={data.length > 6 ? 48 : 24}
        />
        <YAxis tick={axisTick} tickLine={false} axisLine={false} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#f8fafc" }} />
        {spec.valueIndices.length > 1 && (
          <Legend iconSize={8} wrapperStyle={{ fontSize: 11, color: "#64748b" }} />
        )}
        {spec.valueIndices.map((vi, i) => (
          <Bar
            key={vi}
            dataKey={cols[vi]}
            fill={CHART_COLORS[i % CHART_COLORS.length]}
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function ResultTable({
  cols,
  rows,
  maxRows,
}: {
  cols: string[];
  rows: (string | number | null)[][];
  maxRows: number;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <Table>
        <TableHeader>
          <TableRow>
            {cols.map((c) => (
              <TableHead key={c} className="whitespace-nowrap">
                {prettyLabel(c)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, maxRows).map((r, i) => (
            <TableRow key={i}>
              {r.map((v, j) => (
                <TableCell key={j} className="whitespace-nowrap font-mono text-xs">
                  {formatCell(v)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function formatCell(v: string | number | null): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toLocaleString();
  const n = Number(v);
  if (Number.isFinite(n) && /^-?\d/.test(String(v))) {
    if (Number.isInteger(n)) return n.toLocaleString();
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(v);
}
