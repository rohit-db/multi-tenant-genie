import { Network, Plug } from "lucide-react";
import type { AskTransport } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TransportToggleProps {
  value: AskTransport;
  onChange: (t: AskTransport) => void;
  disabled?: boolean;
}

const OPTIONS: { id: AskTransport; label: string; icon: typeof Network }[] = [
  { id: "rest", label: "REST", icon: Network },
  { id: "mcp", label: "Managed MCP", icon: Plug },
];

/**
 * Segmented control that picks the Genie transport for each ask.
 * "rest" uses the Genie Conversation API; "mcp" routes through Databricks
 * managed MCP. The selected value is appended to /genie/ask as ?transport=…
 */
export function TransportToggle({
  value,
  onChange,
  disabled,
}: TransportToggleProps) {
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-0.5">
      <span className="pl-2 pr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400 select-none">
        Transport
      </span>
      {OPTIONS.map((o) => {
        const Icon = o.icon;
        const active = value === o.id;
        return (
          <button
            key={o.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(o.id)}
            aria-pressed={active}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
              active
                ? "bg-white text-indigo-700 shadow-sm ring-1 ring-slate-200"
                : "text-slate-500 hover:text-slate-800",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
