import { useState } from "react";
import type { InspectorPayload } from "@/lib/api";
import { cn } from "@/lib/utils";

interface InspectorProps {
  payload: InspectorPayload;
}

const ROW_FILTER_STEP_NAME = "Apply row filter";

export function Inspector({ payload }: InspectorProps) {
  const [openStep, setOpenStep] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Request flow inspector
        </div>
        <div className="text-[10px] font-mono text-muted-foreground">
          req_{payload.request_id.slice(0, 8)}
        </div>
      </div>

      {/* Six-step strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {payload.steps.map((step) => {
          const isOpen = openStep === step.n;
          const isHero = step.name === ROW_FILTER_STEP_NAME;
          const hasError = step.error !== null;
          return (
            <button
              key={step.n}
              type="button"
              onClick={() => setOpenStep(isOpen ? null : step.n)}
              className={cn(
                "rounded-md border px-2.5 py-2 text-left transition-colors duration-100",
                "focus:outline-none focus:ring-2 focus:ring-offset-1",
                hasError
                  ? "border-rose-300 bg-rose-50 hover:bg-rose-100 focus:ring-rose-300"
                  : isHero
                  ? "border-amber-300 bg-amber-50 hover:bg-amber-100 focus:ring-amber-300"
                  : "border-slate-200 bg-white hover:bg-slate-50 focus:ring-slate-300",
                isOpen && "ring-2 ring-offset-1",
                isOpen && (hasError
                  ? "ring-rose-300"
                  : isHero
                  ? "ring-amber-300"
                  : "ring-slate-300"),
              )}
            >
              <div className="flex items-baseline gap-1.5 text-[10px] font-mono text-muted-foreground">
                <span>{`step ${step.n}`}</span>
                <span className="ml-auto">
                  {hasError ? "error" : `${step.duration_ms} ms`}
                </span>
              </div>
              <div className="mt-1 text-xs font-medium leading-tight">
                {step.name}
              </div>
            </button>
          );
        })}
      </div>

      {/* Expansion panel */}
      {openStep !== null && (
        <ExpansionPanel step={payload.steps.find((s) => s.n === openStep)!} />
      )}
    </div>
  );
}

function ExpansionPanel({ step }: { step: InspectorPayload["steps"][number] }) {
  return (
    <div
      className="rounded-md border bg-white p-4 space-y-3"
      style={{ animation: "fadeIn 100ms ease-out" }}
    >
      <div className="flex items-baseline justify-between">
        <div className="text-sm font-semibold">
          {`Step ${step.n} — ${step.name}`}
        </div>
        <div className="text-[11px] font-mono text-muted-foreground">
          {step.error ? "error" : `${step.duration_ms} ms`}
        </div>
      </div>

      {step.error ? (
        <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2 font-mono whitespace-pre-wrap break-all">
          {step.error}
        </div>
      ) : null}

      <Field label="Summary" value={step.summary} />
      <CodeField label="Code" value={step.code_snippet} />
      <PayloadField label="Input payload" value={step.payload_in} />
      <PayloadField label="Output payload" value={step.payload_out} />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="text-xs mt-0.5 text-slate-800">{value ?? "—"}</div>
    </div>
  );
}

function CodeField({ label, value }: { label: string; value: string | null }) {
  if (!value) return <Field label={label} value={null} />;
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <pre className="mt-0.5 text-[11px] bg-slate-50 border border-slate-200 rounded px-3 py-2 overflow-x-auto whitespace-pre-wrap break-all font-mono text-slate-800">
        {value}
      </pre>
    </div>
  );
}

function PayloadField({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown> | null;
}) {
  if (!value || Object.keys(value).length === 0) {
    return <Field label={label} value={null} />;
  }
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <pre className="mt-0.5 text-[11px] bg-slate-50 border border-slate-200 rounded px-3 py-2 overflow-x-auto whitespace-pre-wrap break-all font-mono text-slate-800">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
