import { useState } from "react";
import {
  Sparkles,
  User,
  Code2,
  Clock,
  Columns,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  AlertCircle,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { AnswerViz } from "@/components/ask/AnswerViz";
import { Inspector } from "@/components/ask/Inspector";
import type { AskResponse, AskTransport } from "@/lib/api";

export interface ChatMessage {
  id: string;
  question: string;
  answer: AskResponse | null;
  pending: boolean;
  error?: string;
  /** Optional — only set when a surface wants to surface the Genie transport
   * (e.g. the operator diagnostics). The customer chat omits it. */
  transport?: AskTransport;
}

interface ChatThreadProps {
  messages: ChatMessage[];
  /** id of the message whose Inspector should be expanded by default. */
  latestInspectorId?: string | null;
}

export function ChatThread({ messages, latestInspectorId }: ChatThreadProps) {
  return (
    <div className="space-y-7">
      {messages.map((m) => (
        <Turn
          key={m.id}
          m={m}
          defaultInspectorOpen={m.id === latestInspectorId}
        />
      ))}
    </div>
  );
}

function Turn({
  m,
  defaultInspectorOpen,
}: {
  m: ChatMessage;
  defaultInspectorOpen: boolean;
}) {
  return (
    <div className="space-y-3.5">
      {/* User question — right aligned bubble */}
      <div className="flex justify-end">
        <div className="flex max-w-[82%] flex-row-reverse items-start gap-2.5">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200">
            <User className="h-3.5 w-3.5 text-slate-600" />
          </span>
          <div
            className="rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm"
            style={{ background: "var(--brand)" }}
          >
            {m.question}
          </div>
        </div>
      </div>

      {/* Genie response — left aligned block */}
      <div className="flex items-start gap-2.5">
        <span
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full shadow-sm"
          style={{
            background: "linear-gradient(135deg, var(--brand), var(--brand-strong))",
          }}
        >
          <Sparkles className="h-3.5 w-3.5 text-white" />
        </span>
        <div className="min-w-0 flex-1">
          {m.pending ? (
            <Thinking transport={m.transport} />
          ) : m.error ? (
            <ErrorBlock error={m.error} />
          ) : m.answer ? (
            <GenieAnswer
              a={m.answer}
              transport={m.transport}
              defaultInspectorOpen={defaultInspectorOpen}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Thinking({ transport }: { transport?: AskTransport }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-500 shadow-sm">
      <span className="flex gap-1">
        <Dot delay="0ms" />
        <Dot delay="150ms" />
        <Dot delay="300ms" />
      </span>
      Thinking
      {transport && (
        <span className="font-mono text-[10px] uppercase tracking-wide text-slate-400">
          · {transport === "mcp" ? "managed mcp" : "rest"}
        </span>
      )}
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="h-1.5 w-1.5 rounded-full bg-slate-400 animate-bounce"
      style={{ animationDelay: delay }}
    />
  );
}

function ErrorBlock({ error }: { error: string }) {
  return (
    <div className="flex items-start gap-2 rounded-2xl rounded-tl-sm border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 shadow-sm">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 break-words">{error}</div>
    </div>
  );
}

function GenieAnswer({
  a,
  transport,
  defaultInspectorOpen,
}: {
  a: AskResponse;
  transport?: AskTransport;
  defaultInspectorOpen: boolean;
}) {
  return (
    <div className="space-y-3 rounded-2xl rounded-tl-sm border border-slate-200 bg-white p-4 shadow-sm">
      {/* Meta badges */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className="border-emerald-200 bg-emerald-50 font-mono text-[11px] text-emerald-700"
        >
          <ShieldCheck className="mr-1 h-3 w-3" />
          {a.status}
        </Badge>
        <Badge variant="secondary" className="font-mono text-[11px]">
          <Clock className="mr-1 h-3 w-3" />
          {a.latency_ms} ms
        </Badge>
        <Badge variant="secondary" className="font-mono text-[11px]">
          <Columns className="mr-1 h-3 w-3" />
          {a.rows.length} row{a.rows.length === 1 ? "" : "s"}
        </Badge>
        {transport && (
          <Badge
            variant="outline"
            className="font-mono text-[11px] text-slate-500"
          >
            {transport === "mcp" ? "managed mcp" : "rest"}
          </Badge>
        )}
        {a.deep_link && (
          <a
            href={a.deep_link}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-[var(--brand-strong)] hover:underline"
          >
            Open in Databricks
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>

      {/* Natural-language answer */}
      {a.answer_text && (
        <div className="text-sm leading-relaxed text-slate-800">
          {a.answer_text}
        </div>
      )}

      {/* Collapsible generated SQL */}
      {a.sql && (
        <details className="rounded-md border border-slate-200 bg-slate-50">
          <summary className="flex cursor-pointer select-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-600">
            <Code2 className="h-3.5 w-3.5" />
            Generated SQL
          </summary>
          <pre className="overflow-x-auto whitespace-pre-wrap px-3 pb-3 text-[11px] font-mono text-slate-800">
            {a.sql}
          </pre>
        </details>
      )}

      {/* Result — auto chart / table toggle */}
      {a.rows.length > 0 && <AnswerViz columns={a.columns} rows={a.rows} />}

      {/* Request flow inspector — the proof of isolation */}
      {a.inspector && (
        <InspectorPanel
          payload={a.inspector}
          defaultOpen={defaultInspectorOpen}
        />
      )}
    </div>
  );
}

function InspectorPanel({
  payload,
  defaultOpen,
}: {
  payload: NonNullable<AskResponse["inspector"]>;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-amber-800"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        <ShieldCheck className="h-3.5 w-3.5" />
        Request flow inspector
        <span className="ml-auto font-mono text-[10px] font-normal text-amber-600">
          step 4 = row filter
        </span>
      </button>
      {open && (
        <div className="border-t border-amber-200 bg-white p-3">
          <Inspector payload={payload} />
        </div>
      )}
    </div>
  );
}

