import { useState } from "react";
import { Sparkles, ArrowUp, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface ChatComposerProps {
  onSubmit: (question: string) => void;
  suggestions: string[];
  disabled?: boolean;
  sending?: boolean;
  placeholder?: string;
  /** Hide the suggestion chips (e.g. once a conversation is underway). */
  showSuggestions?: boolean;
}

/**
 * Persistent Genie-style composer: suggested-question chips above a textarea
 * with a send button. Enter submits, Shift+Enter inserts a newline.
 */
export function ChatComposer({
  onSubmit,
  suggestions,
  disabled,
  sending,
  placeholder = "Ask Genie about your data…",
  showSuggestions = true,
}: ChatComposerProps) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    const text = draft.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setDraft("");
  };

  return (
    <div className="space-y-2.5">
      {showSuggestions && suggestions.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            <Lightbulb className="h-3 w-3" />
            Try
          </span>
          {suggestions.map((s, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onSubmit(s)}
              disabled={disabled}
              className="text-[12px] px-3 py-1 rounded-full border border-slate-200 bg-white text-slate-600 transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)] hover:text-[var(--brand-strong)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {s.length > 48 ? s.slice(0, 45) + "…" : s}
            </button>
          ))}
        </div>
      )}

      <div
        className={cn(
          "rounded-xl border border-slate-200 bg-white shadow-sm transition-shadow",
          "focus-within:border-[var(--brand)] focus-within:ring-2 focus-within:ring-[var(--brand-soft)]",
        )}
      >
        <Textarea
          rows={2}
          value={draft}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="border-0 shadow-none resize-none focus-visible:ring-0 text-sm min-h-0 bg-transparent"
        />
        <div className="flex items-center justify-between px-3 pb-2.5 pt-0.5">
          <span className="text-[10px] text-slate-400 select-none">
            Enter to send · Shift+Enter for newline
          </span>
          <Button
            size="sm"
            onClick={submit}
            disabled={disabled || !draft.trim()}
            className="h-8 gap-1.5 text-white hover:opacity-90"
            style={{ background: "var(--brand)" }}
          >
            {sending ? (
              <Sparkles className="h-4 w-4 animate-pulse" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
            Ask
          </Button>
        </div>
      </div>
    </div>
  );
}
